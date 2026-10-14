"""Execute Director research plans through the YouTube MCP and persist DATA."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

from data.youtube import (
    YouTubeQuery,
    YouTubeSnapshot,
    YouTubeVideo,
    snapshot_from_mapping,
    video_from_mapping,
)
from data.research_sets import ResearchSet
from data.opportunity_entities import YouTubeChannel
from director.research import (
    ResearchOperation,
    ResearchOperationStatus,
    ResearchPlan,
    build_research_plan,
    plan_from_requirements,
    research_from_gaps,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _mcp_error_details(exc: BaseException) -> list[str]:
    """Extract actionable HTTP/MCP details, including nested ExceptionGroups."""
    details: list[str] = []
    stack = [exc]
    while stack:
        current = stack.pop()
        if isinstance(current, BaseExceptionGroup):
            stack.extend(reversed(current.exceptions))
            continue
        if isinstance(current, httpx.HTTPStatusError):
            response = current.response
            body = response.text[:2000] if response is not None else ""
            retry_after = response.headers.get("retry-after") if response is not None else None
            details.append(
                "HTTPStatusError status=%s url=%s retry_after=%s body=%r headers=%s"
                % (
                    response.status_code if response is not None else None,
                    response.request.url if response is not None else None,
                    retry_after,
                    body,
                    dict(response.headers) if response is not None else {},
                )
            )
        else:
            details.append(f"{type(current).__name__}: {current}")
    return details


def _tool_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured

    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured

    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload

    return {}


def _research_objects_for_persistence(
    registry: Any,
    research: Any,
) -> tuple[list[Any], list[Any]]:
    """Resolve only this research's objects through indexed registry lookups."""
    videos = [
        video
        for video_id in dict.fromkeys(research.video_ids)
        if (video := registry.get_video(video_id)) is not None
    ]
    snapshots = [
        snapshot
        for snapshot_id in dict.fromkeys(research.snapshot_ids)
        if (snapshot := registry.get_snapshot(snapshot_id)) is not None
    ]
    return videos, snapshots


class YouTubeResearchExecutor:
    """Research execution layer: Director decides, this layer collects."""

    def __init__(self, *, data_adapter: Any, storage: Any = None) -> None:
        self.data = data_adapter
        self.storage = storage

    def plan(self, *, objective: str, context: dict[str, Any] | None = None) -> ResearchPlan:
        """Build a research plan from Director's current, explicit data requirements."""
        context = dict(context or {})
        metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
        requirements = metadata.get("data_requirements") or context.get("data_requirements") or []
        languages = context.get("languages") or metadata.get("preferred_languages") or ("en", "ru")

        if requirements:
            plan = plan_from_requirements(
                objective=objective,
                requirements=requirements,
                context=context,
                preferred_languages=languages,
            )
        else:
            gaps = context.get("missing_data") or []
            plan = research_from_gaps(
                gaps,
                objective=objective,
                languages=languages,
            )

        self.sync_plan_operations(plan)

        plan.metadata.setdefault("operation_contract_version", 1)
        plan.metadata["operations"] = [operation.to_dict() for operation in plan.operations]
        return plan

    @staticmethod
    def sync_plan_operations(plan: ResearchPlan) -> ResearchPlan:
        """Ensure each planned query is represented by an auditable operation."""
        planned_queries = {
            (str(query.query or "").strip().casefold(), str(query.language or "").casefold())
            for query in plan.queries
        }
        # Drop search operations for queries removed by quota capping. Dependent
        # operations will be blocked explicitly if they reference a removed ID.
        retained_operations: list[ResearchOperation] = []
        for operation in plan.operations:
            if operation.operation != "search_videos":
                retained_operations.append(operation)
                continue
            query_text = str(operation.inputs.get("query") or "").strip().casefold()
            available_languages = sorted(
                language
                for text, language in planned_queries
                if text == query_text
            )
            if not available_languages:
                continue
            operation.inputs["languages"] = available_languages
            retained_operations.append(operation)
        plan.operations = retained_operations
        represented = {
            (
                str(op.inputs.get("query") or "").strip().casefold(),
                {str(language).casefold() for language in (op.inputs.get("languages") or [op.inputs.get("language") or ""])},
            )
            for op in plan.operations
            if op.operation == "search_videos"
        }
        for query in plan.queries:
            query_text = str(query.query or "").strip().casefold()
            query_language = str(query.language or "").casefold()
            if any(text == query_text and query_language in langs for text, langs in represented):
                continue
            operation = ResearchOperation(
                operation_id=f"search_videos_{uuid4().hex[:12]}",
                operation="search_videos",
                requirement_key=str((query.metadata or {}).get("requirement_key") or "videos"),
                inputs={
                    "query": query.query,
                    "language": query.language,
                    "region_code": query.region_code,
                    "max_results": query.max_results,
                    "purpose": query.purpose,
                    "reuse_policy": (query.metadata or {}).get("reuse_policy", "reuse_existing_video_ids"),
                },
                dependencies=[],
                expected_result="video search response and persisted query record",
                completion_criterion="query response is valid; data outcome is recorded even when zero relevant items are returned",
                quota_requirements={"bucket": "search", "estimated_calls": 1},
            )
            plan.operations.append(operation)
            represented.add((query_text, {query_language}))

        # The current executor always creates query records, a research-set
        # record, snapshots for returned videos, and relation records as part
        # of its collection transaction. Keep those side effects explicit in
        # the plan even when the Director supplied only search-oriented gaps.
        def ensure_operation(name: str, requirement_key: str, expected: str, criterion: str) -> ResearchOperation:
            existing = next((item for item in plan.operations if item.operation == name), None)
            if existing is not None:
                return existing
            item = ResearchOperation(
                operation_id=f"{name}_{uuid4().hex[:12]}",
                operation=name,
                requirement_key=requirement_key,
                inputs={"research_id": plan.research_id},
                dependencies=[],
                expected_result=expected,
                completion_criterion=criterion,
                quota_requirements={"bucket": "none"},
            )
            plan.operations.append(item)
            return item

        search_operations = [item for item in plan.operations if item.operation == "search_videos"]
        if search_operations:
            query_operation = ensure_operation(
                "register_queries", "queries", "persisted query records",
                "every attempted query has a persisted record and outcome",
            )
            research_operation = ensure_operation(
                "register_research_set", "research_sets", "persisted research-set record",
                "research-set record is saved and can be retrieved",
            )
            snapshot_operation = ensure_operation(
                "collect_video_snapshots", "video_snapshots", "video metric snapshots",
                "snapshots are saved for returned videos; zero-result searches remain explicitly partial",
            )
            link_operation = ensure_operation(
                "link_research_data", "relations", "persisted research relations",
                "available research, query, video and snapshot relations are saved",
            )
            snapshot_operation.dependencies = [item.operation_id for item in search_operations]
            link_operation.dependencies = [
                item.operation_id for item in [query_operation, research_operation, snapshot_operation, *search_operations]
            ]

        plan.metadata.setdefault("operation_contract_version", 1)
        plan.metadata["operations"] = [operation.to_dict() for operation in plan.operations]
        return plan

    @staticmethod
    def _mark_operation_started(
        plan: Any,
        operation_name: str,
        *,
        query: Any = None,
    ) -> None:
        """Record the first real side effect for an operation."""
        query_text = str(getattr(query, "query", "") or "").strip().casefold()
        query_language = str(getattr(query, "language", "") or "").casefold()
        for operation in list(getattr(plan, "operations", []) or []):
            if operation.operation != operation_name:
                continue
            if operation.status not in {ResearchOperationStatus.PLANNED, ResearchOperationStatus.RUNNING}:
                continue
            if operation_name == "search_videos":
                inputs = operation.inputs or {}
                if str(inputs.get("query") or "").strip().casefold() != query_text:
                    continue
                languages = {
                    str(value).casefold()
                    for value in (inputs.get("languages") or [inputs.get("language") or ""])
                }
                if languages and query_language not in languages:
                    continue
            operation.status = ResearchOperationStatus.RUNNING
            if not operation.started_at:
                operation.started_at = _now()

    @staticmethod
    def _queries_for_operations(plan: ResearchPlan) -> list[Any]:
        """Select only queries represented by operations that still need execution."""
        by_id = {operation.operation_id: operation for operation in (plan.operations or [])}
        operations = [
            operation for operation in (plan.operations or [])
            if operation.operation == "search_videos"
            and operation.status in {
                ResearchOperationStatus.PLANNED,
                ResearchOperationStatus.RUNNING,
                ResearchOperationStatus.PARTIAL,
                ResearchOperationStatus.FAILED,
            }
            and all(
                dependency in by_id
                and by_id[dependency].status == ResearchOperationStatus.SUCCEEDED
                for dependency in (operation.dependencies or [])
            )
        ]
        selected: list[Any] = []
        seen: set[tuple[str, str, str | None]] = set()
        for operation in operations:
            inputs = operation.inputs or {}
            query_text = str(inputs.get("query") or "").strip().casefold()
            languages = {
                str(value).casefold()
                for value in (inputs.get("languages") or [inputs.get("language") or ""])
            }
            prior_queries = (operation.result or {}).get("queries", [])
            already_succeeded = {
                (str(item.get("query") or "").strip().casefold(), str(item.get("language") or "").casefold())
                for item in prior_queries
                if isinstance(item, dict) and item.get("status") == "completed"
            }
            for query in plan.queries:
                key = (
                    str(query.query or "").strip().casefold(),
                    str(query.language or "").casefold(),
                )
                if query_text and key[0] != query_text:
                    continue
                if languages and key[1] not in languages:
                    continue
                if key in already_succeeded:
                    continue
                unique_key = (key[0], key[1], getattr(query, "region_code", None))
                if unique_key in seen:
                    continue
                seen.add(unique_key)
                selected.append(query)
        return selected

    async def execute(self, plan: Any, *, project_id: str | None = None) -> dict[str, Any]:
        if plan is None:
            return {"status": "blocked", "reason": "research_plan_missing"}
        if isinstance(plan, ResearchPlan):
            self.sync_plan_operations(plan)
            executable_queries = self._queries_for_operations(plan)
        else:
            executable_queries = list(getattr(plan, "queries", []) or [])

        if not executable_queries:
            for operation in list(getattr(plan, "operations", []) or []):
                if getattr(operation, "status", None) in {
                    ResearchOperationStatus.PLANNED,
                    ResearchOperationStatus.RUNNING,
                }:
                    operation.status = ResearchOperationStatus.BLOCKED
                    operation.error = "no_executable_search_query_for_current_operation_handler"
                    operation.completed_at = _now()
            operation_results = [
                operation.to_dict() if hasattr(operation, "to_dict") else {
                    "operation_id": str(getattr(operation, "operation_id", "")),
                    "operation": str(getattr(operation, "operation", "")),
                    "status": str(getattr(getattr(operation, "status", "blocked"), "value", getattr(operation, "status", "blocked"))),
                    "result": dict(getattr(operation, "result", {}) or {}),
                    "error": getattr(operation, "error", None),
                }
                for operation in (getattr(plan, "operations", []) or [])
            ]
            plan.metadata["operations"] = operation_results
            plan.metadata["operation_results"] = operation_results
            return {
                "status": "skipped" if operation_results and all(item["status"] in {"succeeded", "skipped"} for item in operation_results) else "blocked",
                "reason": "no_pending_search_operations",
                "research_id": getattr(plan, "research_id", None),
                "queries_planned": 0,
                "queries_collected": 0,
                "operation_results": operation_results,
                "operations_planned": len(operation_results),
            }

        mcp_url = (
            os.getenv("YOUTUBE_MCP_URL")
            or os.getenv("MCP_URL")
            or "http://youtube-mcp:8000/mcp"
        ).rstrip("/")

        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception as exc:
            blocked_summary = {
                "status": "blocked",
                "persisted": False,
                "research_id": getattr(plan, "research_id", None),
                "queries_planned": len(getattr(plan, "queries", []) or []),
                "queries_collected": 0,
                "queries_failed": 0,
                "videos_collected": 0,
                "snapshots_collected": 0,
                "relations_created": 0,
                "errors": [f"mcp_client_unavailable: {type(exc).__name__}: {exc}"],
            }
            operation_results = self._finalize_operations(plan, blocked_summary)
            blocked_summary["operation_results"] = operation_results
            blocked_summary["operations_planned"] = len(operation_results)
            blocked_summary["reason"] = "mcp_client_unavailable"
            return blocked_summary

        project_id = project_id or getattr(self.data, "project_id", None) or "default"
        registry = self.data.youtube_registry
        research_manager = self.data.research_manager
        relations = self.data.relations
        opportunity_registry = self.data.opportunity_registry

        research = ResearchSet(
            research_id=plan.research_id,
            name=f"Director research {plan.research_id}",
            objective=plan.objective,
            languages=list(plan.languages or []),
            regions=[
                q.region_code
                for q in plan.queries
                if getattr(q, "region_code", None)
            ],
            source="youtube-mcp",
            status="collecting",
            expected_data=[
                "videos",
                "video_snapshots",
                "queries",
                "research_set",
                "relations",
            ],
        )

        if research_manager is not None:
            research_manager.add(research)

        collected_queries: list[YouTubeQuery] = []
        channels: list[YouTubeChannel] = []
        self._mark_operation_started(plan, "register_research_set")
        successful_queries = 0
        failed_queries = 0
        errors: list[str] = []

        try:
            async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
    
                    for index, planned_query in enumerate(executable_queries):
                        text = str(getattr(planned_query, "query", "") or "").strip()
                        if not text:
                            continue
    
                        query_id = f"{plan.research_id}_q_{index + 1}"
                        query = YouTubeQuery(
                            query_id=query_id,
                            text=text,
                            language=getattr(planned_query, "language", None),
                            region=getattr(planned_query, "region_code", None),
                            source="director",
                            status="running",
                            metadata={
                                "research_id": plan.research_id,
                                "purpose": getattr(planned_query, "purpose", ""),
                                "priority": str(getattr(planned_query, "priority", "medium")),
                                "quota": {
                                    "search_calls": None,
                                    "search_list_calls": None,
                                    "videos_list_calls": None,
                                    "other_units": None,
                                    "accounting_status": "pending",
                                },
                            },
                        )
                        registry.add_query(query)
                        collected_queries.append(query)
                        research.add_query(query)
                        self._mark_operation_started(plan, "register_queries")
    
                        # A Research -> Query relation exists even when the
                        # query returns zero videos. It describes the research
                        # operation itself, not the search result.
                        if relations is not None:
                            relations.link_research_query(research, query)
    
                        query_video_count = 0
                        try:
                            self._mark_operation_started(plan, "search_videos", query=planned_query)
                            result = await session.call_tool(
                                "search_videos",
                                {
                                    "query": text,
                                    "max_results": int(getattr(planned_query, "max_results", 25) or 25),
                                    "region_code": getattr(planned_query, "region_code", None),
                                    "relevance_language": getattr(planned_query, "language", None),
                                    "order": "relevance",
                                },
                            )
                            payload = _tool_payload(result)
                            quota_report = payload.get("_quota") if isinstance(payload, dict) else None
                            quota_report = quota_report if isinstance(quota_report, dict) else {}
                            def reported_nonnegative_int(key: str) -> int | None:
                                value = quota_report.get(key)
                                if value is None:
                                    return None
                                try:
                                    return max(int(value), 0)
                                except (TypeError, ValueError):
                                    return None

                            search_calls = reported_nonnegative_int("search_calls")
                            search_list_calls = reported_nonnegative_int("search_list_calls")
                            videos_list_calls = reported_nonnegative_int("videos_list_calls")
                            other_units = reported_nonnegative_int("other_units")
                            accounting_status = (
                                "observed_method_calls"
                                if search_list_calls is not None and videos_list_calls is not None
                                else "partial_or_unavailable"
                            )
                            query.metadata["quota"] = {
                                "search_calls": search_calls,
                                "other_units": other_units,
                                "search_list_calls": search_list_calls,
                                "videos_list_calls": videos_list_calls,
                                "accounting_status": accounting_status,
                                "estimated": accounting_status != "observed_method_calls",
                            }
                            logger.info(
                                "YOUTUBE QUOTA USAGE: research_id=%s query_id=%s search=%r quota=%s",
                                plan.research_id, query.query_id, text, query.metadata["quota"],
                            )
                            # Persist each observed quota report immediately. If a later
                            # query crashes or the worker restarts, earlier call counts
                            # must not disappear with the in-memory registry.
                            if self.storage is not None:
                                try:
                                    await _maybe_await(self.storage.save_research_data(
                                        project_id=project_id,
                                        queries=[query.to_dict()],
                                        research_sets=[],
                                        relations=[],
                                    ))
                                except Exception:
                                    logger.exception(
                                        "Failed to persist quota usage immediately: research_id=%s query_id=%s",
                                        plan.research_id, query.query_id,
                                    )
                            if payload.get("error"):
                                raise ValueError(
                                    f"youtube_mcp_api_error: {payload.get('error')}"
                                )
                            if "items" not in payload or not isinstance(payload.get("items"), list):
                                raise ValueError(
                                    "youtube_mcp_invalid_response: expected 'items' list"
                                )
                            items = payload["items"]
    
                            for item in items:
                                if not isinstance(item, dict):
                                    continue
    
                                raw_id = (
                                    item.get("id", {}).get("videoId")
                                    if isinstance(item.get("id"), dict)
                                    else item.get("video_id")
                                )
                                if not raw_id:
                                    raw_id = item.get("youtube_id") or item.get("id")
                                if not raw_id:
                                    continue
    
                                video = video_from_mapping(
                                    item,
                                    video_id=str(raw_id),
                                    source="youtube-mcp",
                                )
                                video = registry.add_video(video)
                                research.add_video(video)
                                query_video_count += 1
    
                                snapshot = snapshot_from_mapping(
                                    item,
                                    snapshot_id=f"{plan.research_id}_s_{uuid4().hex[:12]}",
                                    video_id=video.video_id,
                                    research_id=plan.research_id,
                                    query_ids=[query.query_id],
                                    source="youtube-mcp",
                                )
                                registry.add_snapshot(snapshot)
                                research.add_snapshot(snapshot)
                                self._mark_operation_started(plan, "collect_video_snapshots")
    
                                if relations is not None:
                                    relations.link_query_video(query, video)
                                    relations.link_research_video(research, video)
                                    relations.link_research_snapshot(research, snapshot)
                                    relations.link_video_snapshot(video, snapshot)
                                    self._mark_operation_started(plan, "link_research_data")
    
                                snippet = item.get("snippet") or {}
                                channel_id = snippet.get("channelId") or video.channel_id
                                if channel_id and opportunity_registry is not None:
                                    channel = YouTubeChannel(
                                        channel_id=str(channel_id),
                                        title=str(
                                            snippet.get("channelTitle")
                                            or video.channel_title
                                            or ""
                                        ),
                                        data={
                                            "source": "youtube-mcp",
                                            "last_research_id": plan.research_id,
                                        },
                                    )
                                    opportunity_registry.add_channel(channel)
                                    channels.append(channel)
                                    self._mark_operation_started(plan, "collect_channels")
    
                            query.status = "completed"
                            query.metadata["result_count"] = query_video_count
                            query.metadata["execution_error"] = None
                            successful_queries += 1
    
                        except Exception as exc:
                            query.status = "failed"
                            query.metadata["execution_error"] = f"{type(exc).__name__}: {exc}"
                            query.metadata["result_count"] = query_video_count
                            failed_queries += 1
                            errors.append(f"{text}: {type(exc).__name__}: {exc}")
                            if self.storage is not None:
                                try:
                                    await _maybe_await(self.storage.save_research_data(
                                        project_id=project_id,
                                        queries=[query.to_dict()],
                                        research_sets=[],
                                        relations=[],
                                    ))
                                except Exception:
                                    logger.exception(
                                        "Failed to persist failed query/quota metadata: research_id=%s query_id=%s",
                                        plan.research_id, query.query_id,
                                    )
    
        except Exception as exc:
            details = _mcp_error_details(exc)
            logger.error(
                "YOUTUBE MCP REQUEST FAILED: url=%s error_type=%s details=%s",
                mcp_url,
                type(exc).__name__,
                details,
                exc_info=True,
            )
            research.status = "blocked"
            errors.append(f"mcp_transport: {type(exc).__name__}: {exc}")
            blocked_summary = {
                "status": "blocked",
                "persisted": False,
                "research_id": plan.research_id,
                "queries_planned": len(executable_queries),
                "queries_collected": successful_queries,
                "queries_failed": failed_queries,
                "videos_collected": len(research.video_ids),
                "snapshots_collected": len(research.snapshot_ids),
                "relations_created": 0,
                "gathered_data": list(research.gathered_data),
                "missing_data": list(research.missing_data),
                "expected_data": list(research.expected_data),
                "missing_expected_data": research.missing_expected_data(),
                "completeness": research.completeness,
                "research": research.to_dict(),
                "errors": errors,
                "source": "youtube-mcp",
                "mcp_url": mcp_url,
                "completed_at": _now(),
            }
            operation_results = self._finalize_operations(plan, blocked_summary)
            blocked_summary["operation_results"] = operation_results
            blocked_summary["operations_planned"] = len(operation_results)
            return blocked_summary

        # Query execution and evidence acquisition are distinct facts.
        # An empty successful search records the query outcome, but does not
        # satisfy requirements for videos or video snapshots.
        if collected_queries:
            research.mark_data_gathered("queries")
        if research.video_ids:
            research.mark_data_gathered("videos")
        else:
            research.mark_data_missing("videos")
        if research.snapshot_ids:
            research.mark_data_gathered("video_snapshots")
        else:
            research.mark_data_missing("video_snapshots")

        current_relation_objects = []
        if relations is not None:
            query_ids = set(research.query_ids)
            video_ids = set(research.video_ids)
            snapshot_ids = set(research.snapshot_ids)

            for relation in relations.all_relations():
                if (
                    (relation.source_type == "research" and relation.source_id == research.research_id)
                    or relation.source_id in query_ids
                    or relation.target_id in query_ids
                    or relation.source_id in video_ids
                    or relation.target_id in video_ids
                    or relation.source_id in snapshot_ids
                    or relation.target_id in snapshot_ids
                ):
                    current_relation_objects.append(relation)

        if current_relation_objects:
            research.mark_data_gathered("relations")

        persistence_confirmed = False
        if self.storage is not None:
            try:
                # Persist only objects referenced by this research run. Resolve IDs
                # through the registry indexes rather than scanning process-wide
                # history, which grows across cycles.
                research_videos, research_snapshots = _research_objects_for_persistence(
                    registry, research
                )
                await _maybe_await(
                    self.storage.save_youtube_data(
                        project_id=project_id,
                        videos=[video.to_dict() for video in research_videos],
                        snapshots=[snapshot.to_dict() for snapshot in research_snapshots],
                    )
                )

                await _maybe_await(
                    self.storage.save_research_data(
                        project_id=project_id,
                        queries=[query.to_dict() for query in collected_queries],
                        research_sets=[research.to_dict()],
                        relations=[
                            relation.to_dict()
                            for relation in current_relation_objects
                        ],
                    )
                )

                if opportunity_registry is not None and channels:
                    new_channels = []
                    seen_channel_ids = set()
                    for channel in channels:
                        channel_id = str(getattr(channel, "channel_id", "") or "")
                        if not channel_id or channel_id in seen_channel_ids:
                            continue
                        seen_channel_ids.add(channel_id)
                        new_channels.append(channel.to_dict())

                    if new_channels:
                        await _maybe_await(
                            self.storage.save_opportunity_data(
                                project_id=project_id,
                                data={
                                    "channels": new_channels,
                                    "channel_snapshots": [],
                                    "niches": [],
                                    "niche_snapshots": [],
                                },
                            )
                        )

                persistence_confirmed = True
            except Exception as exc:
                research.mark_partial()
                errors.append(f"persistence: {type(exc).__name__}: {exc}")
                logger.exception("Failed to persist research result: research_id=%s", plan.research_id)

        if persistence_confirmed:
            research.mark_data_gathered("research_set")
        else:
            research.mark_data_missing("research_set")
        missing_expected = research.missing_expected_data()
        if missing_expected:
            research.mark_data_missing(*missing_expected)
        if failed_queries or missing_expected or not persistence_confirmed:
            research.mark_partial()
        else:
            research.mark_complete()

        execution_summary = {
            "status": research.status,
            "persisted": persistence_confirmed,
            "research_id": plan.research_id,
            "queries_planned": len(plan.queries),
            "queries_collected": successful_queries,
            "queries_failed": failed_queries,
            "query_results": [
                {
                    "query_id": query.query_id,
                    "query": query.text,
                    "language": query.language,
                    "status": query.status,
                    "result_count": int((query.metadata or {}).get("result_count", 0) or 0),
                    "error": (query.metadata or {}).get("execution_error"),
                }
                for query in collected_queries
            ],
            "videos_collected": len(research.video_ids),
            "snapshots_collected": len(research.snapshot_ids),
            "relations_created": len(current_relation_objects),
            "gathered_data": list(research.gathered_data),
            "missing_data": list(research.missing_data),
            "expected_data": list(research.expected_data),
            "missing_expected_data": research.missing_expected_data(),
            "completeness": research.completeness,
            "research": research.to_dict(),
            "errors": errors,
            "quota": {
                "search_calls": sum(int((query.metadata.get("quota") or {}).get("search_calls", 0) or 0) for query in collected_queries),
                "other_units": sum(int((query.metadata.get("quota") or {}).get("other_units", 0) or 0) for query in collected_queries),
            },
            "source": "youtube-mcp",
            "mcp_url": mcp_url,
            "completed_at": _now(),
        }
        operation_results = self._finalize_operations(plan, execution_summary)
        plan.metadata["operations"] = [operation.to_dict() for operation in plan.operations]
        plan.metadata["operation_results"] = operation_results
        execution_summary["operation_results"] = operation_results
        execution_summary["operations_planned"] = len(operation_results)
        execution_summary["operations_succeeded"] = sum(item["status"] == "succeeded" for item in operation_results)
        execution_summary["operations_partial"] = sum(item["status"] == "partial" for item in operation_results)
        execution_summary["operations_blocked"] = sum(item["status"] == "blocked" for item in operation_results)
        execution_summary["operations_failed"] = sum(item["status"] == "failed" for item in operation_results)

        # Persist the final operation ledger with the research set, after results
        # are known. A successful transport response alone is not completion.
        execution_summary["operation_ledger_persisted"] = False
        if self.storage is not None:
            research.metadata["operation_results"] = operation_results
            try:
                await _maybe_await(self.storage.save_research_data(
                    project_id=project_id,
                    queries=[],
                    research_sets=[research.to_dict()],
                    relations=[],
                ))
                execution_summary["operation_ledger_persisted"] = True
            except Exception as exc:
                errors.append(f"operation_ledger_persistence: {type(exc).__name__}: {exc}")
                execution_summary["errors"] = errors
                logger.exception("Failed to persist operation ledger: research_id=%s", plan.research_id)
        execution_summary["research"] = research.to_dict()
        execution_summary["errors"] = errors
        return execution_summary

    @staticmethod
    def _finalize_operations(plan: Any, summary: dict[str, Any]) -> list[dict[str, Any]]:
        operations = list(getattr(plan, "operations", []) or [])
        if not operations:
            return []

        by_id = {str(getattr(item, "operation_id", "")): item for item in operations}
        results: list[dict[str, Any]] = []
        video_count = int(summary.get("videos_collected", 0) or 0)
        snapshot_count = int(summary.get("snapshots_collected", 0) or 0)
        query_count = int(summary.get("queries_collected", 0) or 0)
        query_failed = int(summary.get("queries_failed", 0) or 0)
        persisted = bool(summary.get("persisted"))
        query_results = list(summary.get("query_results") or [])
        relation_count = int(summary.get("relations_created", 0) or 0)
        channel_count = len(summary.get("research", {}).get("metadata", {}).get("channel_ids", []) or [])
        errors = list(summary.get("errors") or [])

        for operation in operations:
            operation_id = str(getattr(operation, "operation_id", ""))
            dependencies = list(getattr(operation, "dependencies", []) or [])
            name = str(getattr(operation, "operation", ""))
            status = ResearchOperationStatus.BLOCKED
            result: dict[str, Any] = {}
            error = None

            if name == "search_videos":
                inputs = getattr(operation, "inputs", {}) or {}
                planned_text = str(inputs.get("query") or "").strip().casefold()
                planned_languages = {
                    str(value).casefold()
                    for value in (inputs.get("languages") or [inputs.get("language") or ""])
                }
                matched = [
                    item for item in query_results
                    if (not planned_text or str(item.get("query") or "").strip().casefold() == planned_text)
                    and (not planned_languages or str(item.get("language") or "").casefold() in planned_languages)
                ]
                if matched:
                    matched_success = [item for item in matched if item.get("status") == "completed"]
                    matched_failed = [item for item in matched if item.get("status") != "completed"]
                    matched_videos = sum(int(item.get("result_count") or 0) for item in matched)
                    if matched_videos > 0 and matched_failed:
                        status = ResearchOperationStatus.PARTIAL
                        error = "some_planned_queries_failed_after_partial_collection"
                    elif matched_success and matched_videos > 0:
                        status = ResearchOperationStatus.SUCCEEDED
                    elif matched_success:
                        status = ResearchOperationStatus.PARTIAL
                        error = "search_completed_without_relevant_video_results"
                    else:
                        status = ResearchOperationStatus.FAILED
                        error = "; ".join(str(item.get("error") or "query_failed") for item in matched[:5])
                    result = {
                        "queries": matched,
                        "queries_succeeded": len(matched_success),
                        "queries_failed": len(matched_failed),
                        "videos_collected": matched_videos,
                    }
                else:
                    if query_count > 0 and query_failed == 0 and video_count > 0:
                        status = ResearchOperationStatus.SUCCEEDED
                    elif query_count > 0 or video_count > 0:
                        status = ResearchOperationStatus.PARTIAL
                    elif errors:
                        status = ResearchOperationStatus.FAILED
                        error = "; ".join(errors[:5])
                    else:
                        status = ResearchOperationStatus.PARTIAL
                        error = "search_completed_without_relevant_video_results"
                    result = {"queries_succeeded": query_count, "queries_failed": query_failed, "videos_collected": video_count}
            elif name == "collect_video_snapshots":
                if snapshot_count > 0 and persisted:
                    status = ResearchOperationStatus.SUCCEEDED
                elif snapshot_count > 0:
                    status = ResearchOperationStatus.PARTIAL
                    error = "snapshots_collected_but_persistence_not_confirmed"
                else:
                    status = ResearchOperationStatus.BLOCKED
                    error = "no_video_snapshots_collected"
                result = {"snapshots_collected": snapshot_count, "persisted": persisted}
            elif name == "register_queries":
                attempted_queries = query_count + query_failed
                if attempted_queries > 0 and persisted:
                    status = ResearchOperationStatus.SUCCEEDED
                elif attempted_queries > 0:
                    status = ResearchOperationStatus.PARTIAL
                    error = "query_records_not_confirmed_persisted"
                else:
                    status = ResearchOperationStatus.BLOCKED
                    error = "no_query_records_created"
                result = {"queries_succeeded": query_count, "queries_failed": query_failed, "persisted": persisted}
            elif name == "register_research_set":
                if summary.get("research_id") and persisted:
                    status = ResearchOperationStatus.SUCCEEDED
                else:
                    status = ResearchOperationStatus.PARTIAL
                    error = "research_set_persistence_not_confirmed"
                result = {"research_id": summary.get("research_id"), "persisted": persisted}
            elif name == "link_research_data":
                if relation_count > 0 and persisted:
                    status = ResearchOperationStatus.SUCCEEDED
                elif persisted:
                    status = ResearchOperationStatus.PARTIAL
                    error = "no_research_relations_confirmed"
                else:
                    status = ResearchOperationStatus.BLOCKED
                    error = "relation_persistence_not_confirmed"
                result = {"relations_created": relation_count, "persisted": persisted}
            elif name == "collect_channels":
                # The current collection path derives channel identities from found videos.
                if video_count > 0 and persisted:
                    status = ResearchOperationStatus.PARTIAL
                    error = "channel_identity_enrichment_only; dedicated channel search is not implemented"
                else:
                    status = ResearchOperationStatus.BLOCKED
                    error = "dedicated_channel_collection_not_implemented"
                result = {"videos_collected": video_count, "persisted": persisted}
            elif name in {"collect_channel_snapshots", "collect_niche_evidence", "build_niche_snapshots"}:
                status = ResearchOperationStatus.BLOCKED
                error = f"operation_handler_not_implemented: {name}"
            else:
                status = ResearchOperationStatus.BLOCKED
                error = f"unknown_operation_type: {name}"

            operation.status = status
            operation.result = result
            operation.error = error
            operation.completed_at = _now()
            if (
                getattr(operation, "started_at", None) is None
                and operation.status not in {ResearchOperationStatus.BLOCKED, ResearchOperationStatus.SKIPPED}
            ):
                operation.started_at = operation.completed_at

        # Apply dependency blocking only after all operation outcomes have been
        # determined, so dependencies later in the plan are evaluated correctly.
        for operation in operations:
            dependencies = list(getattr(operation, "dependencies", []) or [])
            failed_dependencies = [
                dependency for dependency in dependencies
                if dependency not in by_id or getattr(by_id[dependency], "status", ResearchOperationStatus.PLANNED)
                not in {ResearchOperationStatus.SUCCEEDED, "succeeded"}
            ]
            if failed_dependencies:
                operation.status = ResearchOperationStatus.BLOCKED
                operation.error = "blocked_by_dependencies: " + ", ".join(failed_dependencies)
                operation.result = dict(getattr(operation, "result", {}) or {})
                operation.result["blocked_dependencies"] = failed_dependencies

        for operation in operations:
            results.append(operation.to_dict() if hasattr(operation, "to_dict") else {
                "operation_id": str(getattr(operation, "operation_id", "")),
                "operation": str(getattr(operation, "operation", "")),
                "status": str(getattr(getattr(operation, "status", "blocked"), "value", getattr(operation, "status", "blocked"))),
                "result": dict(getattr(operation, "result", {}) or {}),
                "error": getattr(operation, "error", None),
            })
        return results
