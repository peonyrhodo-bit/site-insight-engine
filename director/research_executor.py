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
        plan.operations = [
            op for op in plan.operations
            if op.operation != "search_videos"
            or any(
                (str(op.inputs.get("query") or "").strip().casefold(), language)
                in planned_queries
                for language in (op.inputs.get("languages") or [op.inputs.get("language") or ""])
            )
        ]
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
        plan.metadata.setdefault("operation_contract_version", 1)
        plan.metadata["operations"] = [operation.to_dict() for operation in plan.operations]
        return plan

    async def execute(self, plan: Any, *, project_id: str | None = None) -> dict[str, Any]:
        if plan is None:
            return {"status": "blocked", "reason": "research_plan_missing"}

        mcp_url = (
            os.getenv("YOUTUBE_MCP_URL")
            or os.getenv("MCP_URL")
            or "http://youtube-mcp:8000/mcp"
        ).rstrip("/")

        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception as exc:
            return {
                "status": "blocked",
                "reason": "mcp_client_unavailable",
                "error": str(exc),
            }

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
        for operation in list(getattr(plan, "operations", []) or []):
            if str(getattr(operation, "operation", "")) in {
                "search_videos", "register_queries", "register_research_set",
                "collect_video_snapshots", "link_research_data", "collect_channels",
            }:
                operation.status = ResearchOperationStatus.RUNNING
                operation.started_at = _now()
                operation.error = None
        successful_queries = 0
        failed_queries = 0
        errors: list[str] = []

        try:
            async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
    
                    for index, planned_query in enumerate(plan.queries):
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
    
                        # A Research -> Query relation exists even when the
                        # query returns zero videos. It describes the research
                        # operation itself, not the search result.
                        if relations is not None:
                            relations.link_research_query(research, query)
    
                        try:
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
    
                                if relations is not None:
                                    relations.link_query_video(query, video)
                                    relations.link_research_video(research, video)
                                    relations.link_research_snapshot(research, snapshot)
                                    relations.link_video_snapshot(video, snapshot)
    
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
    
                            query.status = "completed"
                            successful_queries += 1
    
                        except Exception as exc:
                            query.status = "failed"
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
                "queries_planned": len(plan.queries),
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

        # A successful MCP response is a gathered data point even when
        # it contains zero items. Empty search results are a valid research
        # outcome and must not be confused with data that was never collected.
        if collected_queries:
            research.mark_data_gathered("queries")
        research.mark_data_gathered("research_set")

        successful_response_count = successful_queries
        if successful_response_count:
            research.mark_data_gathered("videos", "video_snapshots")

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

        missing_expected = research.missing_expected_data()
        if missing_expected:
            research.mark_data_missing(*missing_expected)

        if failed_queries or missing_expected:
            research.mark_partial()
        else:
            research.mark_complete()

        if self.storage is not None:
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

        execution_summary = {
            "status": research.status,
            "persisted": self.storage is not None,
            "research_id": plan.research_id,
            "queries_planned": len(plan.queries),
            "queries_collected": successful_queries,
            "queries_failed": failed_queries,
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
        execution_summary["operation_results"] = operation_results
        execution_summary["operations_planned"] = len(operation_results)
        execution_summary["operations_succeeded"] = sum(item["status"] == "succeeded" for item in operation_results)
        execution_summary["operations_partial"] = sum(item["status"] == "partial" for item in operation_results)
        execution_summary["operations_blocked"] = sum(item["status"] == "blocked" for item in operation_results)
        execution_summary["operations_failed"] = sum(item["status"] == "failed" for item in operation_results)

        # Persist the final operation ledger with the research set, after results
        # are known. A successful transport response alone is not completion.
        if self.storage is not None:
            research.metadata["operation_results"] = operation_results
            await _maybe_await(self.storage.save_research_data(
                project_id=project_id,
                queries=[],
                research_sets=[research.to_dict()],
                relations=[],
            ))
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
                if query_count > 0 and persisted:
                    status = ResearchOperationStatus.SUCCEEDED
                elif query_count > 0:
                    status = ResearchOperationStatus.PARTIAL
                    error = "query_results_not_confirmed_persisted"
                else:
                    status = ResearchOperationStatus.BLOCKED
                    error = "no_successful_query_records"
                result = {"queries_succeeded": query_count, "persisted": persisted}
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
            if getattr(operation, "started_at", None) is None:
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
