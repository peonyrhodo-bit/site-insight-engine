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
from data.opportunity_entities import ChannelSnapshot, YouTubeChannel
from director.research import (
    ResearchOperation,
    ResearchOperationStatus,
    ResearchPlan,
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

    def __init__(self, *, data_adapter: Any, storage: Any = None, quota_manager: Any = None) -> None:
        self.data = data_adapter
        self.storage = storage
        self.quota_manager = quota_manager

    def _quota_preflight(
        self, *, bucket: str, operation: str, method: str, units: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Authorize and account for an API attempt before calling the MCP tool."""
        if self.quota_manager is None:
            # Runtime injects the manager; None is retained for isolated unit tests.
            return None
        self.quota_manager.record_planned_call(
            bucket=bucket, operation=operation, method=method, units=units, metadata=metadata,
        )
        return self.quota_manager.authorize_call(
            bucket=bucket, operation=operation, method=method, units=units, metadata=metadata,
        )

    def _quota_finish(
        self, token: dict[str, Any] | None, *, status: str, reason: str | None = None,
    ) -> None:
        if token is None or self.quota_manager is None:
            return
        event_id = token.get("event_id")
        if event_id is not None:
            self.quota_manager.finish_call(int(event_id), status=status, reason=reason)

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
                frozenset(str(language).casefold() for language in (op.inputs.get("languages") or [op.inputs.get("language") or ""])),
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
            represented.add((query_text, frozenset({query_language})))

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

        if any(item.operation == "collect_video_snapshots" for item in plan.operations):
            ensure_operation(
                "refresh_existing_video_stats",
                "video_snapshots",
                "fresh snapshots for known videos with stale or missing statistics",
                "each known video is independently checked against its latest successful snapshot and stale IDs are refreshed without search.list",
            )

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

    @staticmethod
    def _known_videos_needing_refresh(
        payload: dict[str, Any],
        *,
        max_age_seconds: float,
        now: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, str | None]]:
        """Select stale videos independently using each video's latest snapshot."""
        current = now or datetime.now(timezone.utc)
        videos = [
            item for item in (payload.get("videos") or [])
            if isinstance(item, dict) and str(item.get("video_id") or item.get("youtube_id") or "").strip()
        ]
        latest: dict[str, str | None] = {}
        for snapshot in payload.get("snapshots") or []:
            if not isinstance(snapshot, dict):
                continue
            video_id = str(snapshot.get("video_id") or "").strip()
            if not video_id:
                continue
            captured = snapshot.get("captured_at")
            previous = latest.get(video_id)
            def parsed(value: Any) -> datetime | None:
                if not value:
                    return None
                try:
                    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
                except (TypeError, ValueError):
                    return None
            captured_dt, previous_dt = parsed(captured), parsed(previous)
            if captured_dt is not None and (previous_dt is None or captured_dt > previous_dt):
                latest[video_id] = str(captured)
            elif video_id not in latest:
                latest[video_id] = str(captured) if captured else None

        for video in videos:
            video_id = str(video.get("video_id") or video.get("youtube_id") or "").strip()
            if video_id:
                latest.setdefault(video_id, None)

        stale: list[dict[str, Any]] = []
        for video in videos:
            video_id = str(video.get("video_id") or video.get("youtube_id") or "").strip()
            timestamp = latest.get(video_id)
            try:
                captured = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")) if timestamp else None
                if captured is not None and captured.tzinfo is None:
                    captured = captured.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                captured = None
            age = (current - captured).total_seconds() if captured is not None else None
            if age is None or age < 0 or age > max_age_seconds:
                stale.append(video)
        return stale, latest

    async def _refresh_existing_video_stats(
        self,
        plan: ResearchPlan,
        *,
        project_id: str,
    ) -> dict[str, Any]:
        """Refresh stale known IDs directly through videos.list, without search.list."""
        operation = next(
            (item for item in (plan.operations or []) if item.operation == "refresh_existing_video_stats"),
            None,
        )
        if operation is None or operation.status in {ResearchOperationStatus.SUCCEEDED, ResearchOperationStatus.SKIPPED}:
            return {}
        if self.storage is None or not hasattr(self.storage, "load_youtube_data") or not hasattr(self.storage, "save_youtube_data"):
            return {
                "refresh_existing_video_stats_attempted": True,
                "refresh_existing_video_stats_status": "blocked",
                "refresh_existing_video_stats_errors": ["storage does not expose load_youtube_data/save_youtube_data"],
                "refresh_existing_video_stats_persisted": False,
            }

        try:
            max_age_seconds = float(
                (operation.inputs or {}).get("max_age_seconds")
                or os.getenv("DIRECTOR_VIDEO_STATS_MAX_AGE_SECONDS", "86400")
            )
        except (TypeError, ValueError):
            max_age_seconds = 86400.0
        max_age_seconds = max(0.0, max_age_seconds)

        try:
            payload = await _maybe_await(self.storage.load_youtube_data(project_id=project_id))
            payload = payload if isinstance(payload, dict) else {}
        except Exception as exc:
            return {
                "refresh_existing_video_stats_attempted": True,
                "refresh_existing_video_stats_status": "failed",
                "refresh_existing_video_stats_errors": [f"load_known_videos: {type(exc).__name__}: {exc}"],
                "refresh_existing_video_stats_persisted": False,
            }

        stale_videos, latest_snapshots = self._known_videos_needing_refresh(
            payload,
            max_age_seconds=max_age_seconds,
        )
        stale_ids = list(dict.fromkeys(
            str(video.get("video_id") or video.get("youtube_id") or "").strip()
            for video in stale_videos
        ))
        stale_ids = [value for value in stale_ids if value]
        if not stale_ids:
            return {
                "refresh_existing_video_stats_attempted": True,
                "refresh_existing_video_stats_status": "succeeded",
                "refresh_existing_video_stats_persisted": True,
                "refresh_existing_video_stats_candidates": 0,
                "refresh_existing_video_stats_refreshed": 0,
                "refresh_existing_video_stats_unavailable": [],
                "refresh_existing_video_stats_errors": [],
                "refresh_existing_video_stats_latest_snapshot_by_video": latest_snapshots,
            }

        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception as exc:
            return {
                "refresh_existing_video_stats_attempted": True,
                "refresh_existing_video_stats_status": "blocked",
                "refresh_existing_video_stats_errors": [f"mcp_client_unavailable: {type(exc).__name__}: {exc}"],
                "refresh_existing_video_stats_candidates": len(stale_ids),
                "refresh_existing_video_stats_persisted": False,
            }

        mcp_url = (
            os.getenv("YOUTUBE_MCP_URL")
            or os.getenv("MCP_URL")
            or "http://youtube-mcp:8000/mcp"
        ).rstrip("/")
        refreshed_snapshots: list[dict[str, Any]] = []
        refreshed_videos: list[dict[str, Any]] = []
        unavailable: list[str] = []
        errors: list[str] = []
        api_batches = 0

        try:
            async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tool_names = {tool.name for tool in (await session.list_tools()).tools}
                    if "get_video_stats" not in tool_names:
                        return {
                            "refresh_existing_video_stats_attempted": True,
                            "refresh_existing_video_stats_status": "blocked",
                            "refresh_existing_video_stats_errors": ["MCP tool not available: get_video_stats"],
                            "refresh_existing_video_stats_candidates": len(stale_ids),
                            "refresh_existing_video_stats_persisted": False,
                        }
                    by_id = {
                        str(item.get("video_id") or item.get("youtube_id")): item
                        for item in (payload.get("videos") or []) if isinstance(item, dict)
                    }
                    for offset in range(0, len(stale_ids), 50):
                        batch_ids = stale_ids[offset:offset + 50]
                        quota_token = None
                        try:
                            quota_token = self._quota_preflight(
                                bucket="other", operation="refresh_existing_video_stats",
                                method="videos.list", metadata={"video_ids": batch_ids},
                            )
                            result = await session.call_tool("get_video_stats", {"video_ids": batch_ids})
                            batch_payload = _tool_payload(result)
                            if batch_payload.get("error"):
                                raise ValueError(str(batch_payload["error"]))
                            items = batch_payload.get("items")
                            if not isinstance(items, list):
                                raise ValueError("get_video_stats returned no items list")
                            self._quota_finish(quota_token, status="succeeded")
                            api_batches += 1
                            returned: set[str] = set()
                            for item in items:
                                if not isinstance(item, dict):
                                    continue
                                raw_id = item.get("id")
                                if not raw_id:
                                    continue
                                video_id = str(raw_id)
                                if video_id not in batch_ids:
                                    continue
                                returned.add(video_id)
                                video = dict(by_id.get(video_id) or {"video_id": video_id})
                                metadata = dict(video.get("metadata") or {})
                                snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
                                statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
                                content_details = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
                                metadata.update({"snippet": snippet, "statistics": statistics, "contentDetails": content_details})
                                video["metadata"] = metadata
                                video["video_id"] = video_id
                                refreshed_videos.append(video)
                                snapshot = snapshot_from_mapping(
                                    item,
                                    snapshot_id=f"{plan.research_id}_refresh_{uuid4().hex[:12]}",
                                    video_id=video_id,
                                    research_id=plan.research_id,
                                    query_ids=[],
                                    source="youtube-mcp:refresh_existing_video_stats",
                                )
                                refreshed_snapshots.append(snapshot.to_dict())
                            unavailable.extend(video_id for video_id in batch_ids if video_id not in returned)
                        except Exception as exc:
                            self._quota_finish(quota_token, status="error", reason=f"{type(exc).__name__}: {exc}")
                            errors.append(f"videos.list batch {offset // 50 + 1}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"mcp_transport: {type(exc).__name__}: {exc}")

        persisted = False
        if refreshed_snapshots:
            try:
                await _maybe_await(self.storage.save_youtube_data(
                    project_id=project_id,
                    videos=refreshed_videos,
                    snapshots=refreshed_snapshots,
                ))
                persisted = True
            except Exception as exc:
                errors.append(f"persist_refresh_snapshots: {type(exc).__name__}: {exc}")

        status = "succeeded" if persisted and not errors and not unavailable else (
            "partial" if persisted or refreshed_snapshots else "failed"
        )
        if not refreshed_snapshots and not errors and unavailable:
            status = "partial"
        return {
            "refresh_existing_video_stats_attempted": True,
            "refresh_existing_video_stats_status": status,
            "refresh_existing_video_stats_persisted": persisted,
            "refresh_existing_video_stats_candidates": len(stale_ids),
            "refresh_existing_video_stats_refreshed": len(refreshed_snapshots) if persisted else 0,
            "refresh_existing_video_stats_api_batches": api_batches,
            "refresh_existing_video_stats_unavailable": unavailable,
            "refresh_existing_video_stats_errors": errors,
            "refresh_existing_video_stats_latest_snapshot_by_video": latest_snapshots,
        }

    async def execute(self, plan: Any, *, project_id: str | None = None) -> dict[str, Any]:
        if plan is None:
            return {"status": "blocked", "reason": "research_plan_missing"}
        if isinstance(plan, ResearchPlan):
            self.sync_plan_operations(plan)
            executable_queries = self._queries_for_operations(plan)
        else:
            executable_queries = list(getattr(plan, "queries", []) or [])

        project_id = project_id or getattr(self.data, "project_id", None) or "default"
        refresh_summary: dict[str, Any] = {}
        if isinstance(plan, ResearchPlan) and any(
            op.operation == "refresh_existing_video_stats"
            and op.status not in {ResearchOperationStatus.SUCCEEDED, ResearchOperationStatus.SKIPPED}
            for op in (plan.operations or [])
        ):
            refresh_summary = await self._refresh_existing_video_stats(plan, project_id=project_id)

        if not executable_queries:
            if refresh_summary:
                operation_results = self._finalize_operations(plan, {
                    **refresh_summary,
                    "persisted": bool(refresh_summary.get("refresh_existing_video_stats_persisted")),
                    "errors": list(refresh_summary.get("refresh_existing_video_stats_errors") or []),
                })
                plan.metadata["operations"] = [operation.to_dict() for operation in plan.operations]
                plan.metadata["operation_results"] = operation_results
                return {
                    **refresh_summary,
                    "status": refresh_summary.get("refresh_existing_video_stats_status", "blocked"),
                    "research_id": getattr(plan, "research_id", None),
                    "queries_planned": 0,
                    "queries_collected": 0,
                    "operation_results": operation_results,
                    "operations_planned": len(operation_results),
                }
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
            terminal_statuses = {item["status"] for item in operation_results}
            if not operation_results:
                overall_status = "blocked"
            elif "partial" in terminal_statuses:
                overall_status = "partial"
            elif "failed" in terminal_statuses:
                overall_status = "failed"
            elif "blocked" in terminal_statuses:
                overall_status = "blocked"
            else:
                overall_status = "skipped"
            return {
                "status": overall_status,
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
                *(
                    ["channel_snapshots"]
                    if any(op.operation == "collect_channel_snapshots" for op in (plan.operations or []))
                    else []
                ),
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
                    available_tools = {tool.name for tool in (await session.list_tools()).tools}
    
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
                        search_quota_token = None
                        try:
                            self._mark_operation_started(plan, "search_videos", query=planned_query)
                            # Preflight search.list here. The MCP gateway independently checks every
                            # actual HTTP request, including optional videos.list enrichment.
                            search_quota_token = self._quota_preflight(
                                bucket="search", operation="search_videos", method="search.list",
                                metadata={"query": text},
                            )
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
                            self._quota_finish(search_quota_token, status="succeeded")
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
                            # The MCP API gateway preflights every actual videos.list
                            # request. Mirror its observed count into Director's ledger.
                            if self.quota_manager is not None and videos_list_calls:
                                self.quota_manager.record_usage(
                                    operation="search_videos",
                                    other_units=videos_list_calls,
                                    metadata={"method": "videos.list", "query": text, "source": "mcp_observed"},
                                )
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
                                query.metadata.setdefault("video_ids", []).append(video.video_id)
    
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
                            self._quota_finish(search_quota_token, status="error", reason=f"{type(exc).__name__}: {exc}")
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
    
                    # Refresh video statistics through videos.list in bounded batches.
                    # This is one API call per <=50 videos and does not use search.list quota.
                    video_stats_calls = 0
                    video_stats_errors: list[str] = []
                    video_ids = list(dict.fromkeys(str(value) for value in research.video_ids if value))
                    if video_ids and "get_video_stats" in available_tools:
                        for offset in range(0, len(video_ids), 50):
                            batch_ids = video_ids[offset:offset + 50]
                            quota_token = None
                            try:
                                quota_token = self._quota_preflight(
                                    bucket="other", operation="collect_video_snapshots",
                                    method="videos.list", metadata={"video_ids": batch_ids},
                                )
                                stats_result = await session.call_tool("get_video_stats", {"video_ids": batch_ids})
                                stats_payload = _tool_payload(stats_result)
                                if stats_payload.get("error"):
                                    raise ValueError(str(stats_payload["error"]))
                                items = stats_payload.get("items")
                                if not isinstance(items, list):
                                    raise ValueError("get_video_stats returned no items list")
                                self._quota_finish(quota_token, status="succeeded")
                                video_stats_calls += 1
                                for item in items:
                                    if not isinstance(item, dict):
                                        continue
                                    raw_id = item.get("id") or item.get("video_id") or item.get("youtube_id")
                                    if not raw_id:
                                        continue
                                    video = registry.get_video(str(raw_id))
                                    if video is None:
                                        continue
                                    # Preserve the richer search metadata while refreshing observed metrics.
                                    refreshed = video_from_mapping(item, video_id=str(raw_id), source="youtube-mcp:get_video_stats")
                                    for field_name in ("title", "description", "channel_id", "channel_title", "published_at", "view_count", "like_count", "comment_count", "duration_seconds", "tags", "category_id"):
                                        value = getattr(refreshed, field_name, None)
                                        if value not in (None, "", []):
                                            try:
                                                setattr(video, field_name, value)
                                            except (AttributeError, TypeError):
                                                pass
                                    snapshot = snapshot_from_mapping(
                                        item,
                                        snapshot_id=f"{plan.research_id}_stats_{uuid4().hex[:12]}",
                                        video_id=video.video_id,
                                        research_id=plan.research_id,
                                        query_ids=list(research.query_ids),
                                        source="youtube-mcp:get_video_stats",
                                    )
                                    registry.add_snapshot(snapshot)
                                    research.add_snapshot(snapshot)
                                    if relations is not None:
                                        relations.link_research_snapshot(research, snapshot)
                                        relations.link_video_snapshot(video, snapshot)
                            except Exception as stats_exc:
                                self._quota_finish(quota_token, status="error", reason=f"{type(stats_exc).__name__}: {stats_exc}")
                                video_stats_errors.append(f"get_video_stats batch {offset // 50 + 1}: {type(stats_exc).__name__}: {stats_exc}")
                    elif video_ids:
                        video_stats_errors.append("MCP tool not available: get_video_stats")

                    # Capture a point-in-time channel metrics snapshot for each channel
                    # discovered from the video results. Do not make channel searches
                    # implicitly: search_channels is a separate planned operation.
                    channel_snapshots: list[ChannelSnapshot] = []
                    channel_stats_errors: list[str] = []
                    channel_stats_calls = 0
                    if "collect_channel_snapshots" in {op.operation for op in (plan.operations or [])}:
                        unique_channels = list({
                            str(channel.channel_id): channel
                            for channel in channels
                            if getattr(channel, "channel_id", None)
                        }.values())
                        if unique_channels and "get_channel_stats" in available_tools:
                            for channel in unique_channels:
                                quota_token = None
                                try:
                                    quota_token = self._quota_preflight(
                                        bucket="other", operation="collect_channel_snapshots",
                                        method="channels.list", metadata={"channel_id": channel.channel_id},
                                    )
                                    stats_result = await session.call_tool(
                                        "get_channel_stats",
                                        {"channel_id": channel.channel_id},
                                    )
                                    stats_payload = _tool_payload(stats_result)
                                    self._quota_finish(quota_token, status="succeeded")
                                    if stats_payload.get("error"):
                                        raise ValueError(str(stats_payload["error"]))
                                    items = stats_payload.get("items")
                                    if not isinstance(items, list):
                                        raise ValueError("get_channel_stats returned no items list")
                                    item = next(
                                        (candidate for candidate in items if isinstance(candidate, dict)
                                         and str(candidate.get("id") or "") == channel.channel_id),
                                        None,
                                    )
                                    if item is None:
                                        raise ValueError("get_channel_stats returned no matching channel")
                                    channel_stats_calls += 1
                                    snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
                                    statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
                                    def metric_int(value: Any) -> int | None:
                                        try:
                                            return int(value) if value is not None else None
                                        except (TypeError, ValueError):
                                            return None
                                    channel.title = str(snippet.get("title") or channel.title or "")
                                    channel.description = snippet.get("description") or channel.description
                                    channel.custom_url = snippet.get("customUrl") or channel.custom_url
                                    channel.country = snippet.get("country") or channel.country
                                    channel.published_at = snippet.get("publishedAt") or channel.published_at
                                    channel.subscriber_count = metric_int(statistics.get("subscriberCount"))
                                    channel.video_count = metric_int(statistics.get("videoCount"))
                                    channel.view_count = metric_int(statistics.get("viewCount"))
                                    channel.data.update({
                                        "statistics_source": "youtube-mcp:get_channel_stats",
                                        "statistics_captured_at": _now(),
                                        "hidden_subscriber_count": bool(statistics.get("hiddenSubscriberCount", False)),
                                    })
                                    channel_snap = ChannelSnapshot(
                                        channel_id=channel.channel_id,
                                        captured_at=_now(),
                                        subscriber_count=channel.subscriber_count,
                                        video_count=channel.video_count,
                                        view_count=channel.view_count,
                                        data={"source": "youtube-mcp:get_channel_stats", "research_id": plan.research_id},
                                    )
                                    if opportunity_registry is None:
                                        raise RuntimeError("opportunity registry is not available")
                                    opportunity_registry.add_channel_snapshot(channel_snap)
                                    channel_snapshots.append(channel_snap)
                                except Exception as stats_exc:
                                    self._quota_finish(quota_token, status="error", reason=f"{type(stats_exc).__name__}: {stats_exc}")
                                    channel_stats_errors.append(f"{channel.channel_id}: {type(stats_exc).__name__}: {stats_exc}")
                        elif unique_channels:
                            channel_stats_errors.append("MCP tool not available: get_channel_stats")
                    errors.extend(video_stats_errors)
                    errors.extend(f"channel_stats: {error}" for error in channel_stats_errors)

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
            plan.metadata["operations"] = [operation.to_dict() for operation in plan.operations]
            plan.metadata["operation_results"] = operation_results
            blocked_summary["operation_results"] = operation_results
            blocked_summary["operations_planned"] = len(operation_results)
            blocked_summary["operation_ledger_persisted"] = False
            if self.storage is not None:
                research.metadata["operation_results"] = operation_results
                research.metadata["research_plan"] = plan.to_dict()
                try:
                    await _maybe_await(self.storage.save_research_data(
                        project_id=project_id,
                        queries=[query.to_dict() for query in collected_queries],
                        research_sets=[research.to_dict()],
                        relations=[],
                    ))
                    blocked_summary["operation_ledger_persisted"] = True
                except Exception as persist_exc:
                    errors.append(f"operation_ledger_persistence: {type(persist_exc).__name__}: {persist_exc}")
                    blocked_summary["errors"] = errors
                    logger.exception("Failed to persist interrupted operation ledger: research_id=%s", plan.research_id)
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
        if any(op.operation == "collect_channel_snapshots" for op in (plan.operations or [])):
            if channel_snapshots:
                research.mark_data_gathered("channel_snapshots")
            else:
                research.mark_data_missing("channel_snapshots")

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
                                    "channel_snapshots": [
                                        snapshot.to_dict()
                                        for snapshot in channel_snapshots
                                        if str(snapshot.channel_id) in seen_channel_ids
                                    ],
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
            **refresh_summary,
            "status": research.status,
            "persisted": persistence_confirmed,
            "research_id": plan.research_id,
            "queries_planned": len(executable_queries),
            "queries_in_plan": len(plan.queries),
            "queries_collected": successful_queries,
            "queries_failed": failed_queries,
            "query_results": [
                {
                    "query_id": query.query_id,
                    "query": query.text,
                    "language": query.language,
                    "status": query.status,
                    "result_count": int((query.metadata or {}).get("result_count", 0) or 0),
                    "video_ids": list((query.metadata or {}).get("video_ids") or []),
                    "error": (query.metadata or {}).get("execution_error"),
                }
                for query in collected_queries
            ],
            "videos_collected": len(research.video_ids),
            "video_ids": list(research.video_ids),
            "snapshots_collected": len(research.snapshot_ids),
            "snapshot_ids": list(research.snapshot_ids),
            "relations_created": len(current_relation_objects),
            "relation_ids": [
                getattr(relation, "relation_id", getattr(relation, "id", None))
                for relation in current_relation_objects
            ],
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
            "video_stats_calls": video_stats_calls,
            "video_stats_errors": video_stats_errors,
            "channel_stats_calls": channel_stats_calls,
            "channel_stats_errors": channel_stats_errors,
            "channel_snapshots_collected": len(channel_snapshots),
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
            # Persist the complete plan as well as its final ledger so a later
            # worker can reconstruct the exact operation IDs/statuses and retry
            # only incomplete work without regenerating the plan.
            research.metadata["research_plan"] = plan.to_dict()
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

    def _finalize_operations(self, plan: Any, summary: dict[str, Any]) -> list[dict[str, Any]]:
        quota_status = self.quota_manager.get_status() if self.quota_manager is not None else None
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
        errors = list(summary.get("errors") or [])

        for operation in operations:
            # A restored successful/skipped operation is immutable on resume.
            # Re-finalizing it from only the current attempt's summary could
            # downgrade valid prior work when a later query fails.
            if getattr(operation, "status", None) in {
                ResearchOperationStatus.SUCCEEDED,
                ResearchOperationStatus.SKIPPED,
            }:
                continue
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
                        if video_count == 0:
                            error = "search_completed_without_relevant_video_results"
                        elif query_failed:
                            error = "some_planned_queries_failed"
                    elif errors:
                        status = ResearchOperationStatus.FAILED
                        error = "; ".join(errors[:5])
                    else:
                        status = ResearchOperationStatus.PARTIAL
                        error = "search_completed_without_relevant_video_results"
                    result = {"queries_succeeded": query_count, "queries_failed": query_failed, "videos_collected": video_count}
            elif name == "refresh_existing_video_stats":
                refresh_status = str(summary.get("refresh_existing_video_stats_status") or "blocked")
                if refresh_status == "succeeded":
                    status = ResearchOperationStatus.SUCCEEDED
                elif refresh_status == "partial":
                    status = ResearchOperationStatus.PARTIAL
                elif refresh_status == "failed":
                    status = ResearchOperationStatus.FAILED
                else:
                    status = ResearchOperationStatus.BLOCKED
                error_values = list(summary.get("refresh_existing_video_stats_errors") or [])
                unavailable_values = list(summary.get("refresh_existing_video_stats_unavailable") or [])
                if error_values or unavailable_values:
                    error = "; ".join(
                        error_values[:5] + ([f"unavailable video IDs: {', '.join(unavailable_values[:20])}"] if unavailable_values else [])
                    )
                result = {
                    "candidates": int(summary.get("refresh_existing_video_stats_candidates", 0) or 0),
                    "refreshed": int(summary.get("refresh_existing_video_stats_refreshed", 0) or 0),
                    "api_batches": int(summary.get("refresh_existing_video_stats_api_batches", 0) or 0),
                    "unavailable_video_ids": unavailable_values,
                    "errors": error_values,
                    "persisted": bool(summary.get("refresh_existing_video_stats_persisted")),
                    "latest_snapshot_by_video": dict(summary.get("refresh_existing_video_stats_latest_snapshot_by_video") or {}),
                }
            elif name == "collect_video_snapshots":
                if snapshot_count > 0 and persisted:
                    status = ResearchOperationStatus.SUCCEEDED
                elif snapshot_count > 0:
                    status = ResearchOperationStatus.PARTIAL
                    error = "snapshots_collected_but_persistence_not_confirmed"
                else:
                    status = ResearchOperationStatus.BLOCKED
                    error = "no_video_snapshots_collected"
                result = {
                    "snapshots_collected": snapshot_count,
                    "snapshot_ids": list(summary.get("snapshot_ids") or []),
                    "video_ids": list(summary.get("video_ids") or []),
                    "persisted": persisted,
                }
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
                result = {
                    "queries_succeeded": query_count,
                    "queries_failed": query_failed,
                    "query_ids": [item.get("query_id") for item in query_results if item.get("query_id")],
                    "persisted": persisted,
                }
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
                result = {
                    "relations_created": relation_count,
                    "relation_ids": list(summary.get("relation_ids") or []),
                    "persisted": persisted,
                }
            elif name == "collect_channels":
                # The current collection path derives channel identities from found videos.
                if video_count > 0 and persisted:
                    status = ResearchOperationStatus.PARTIAL
                    error = "channel_identity_enrichment_only; dedicated channel search is not implemented"
                else:
                    status = ResearchOperationStatus.BLOCKED
                    error = "dedicated_channel_collection_not_implemented"
                result = {"videos_collected": video_count, "persisted": persisted}
            elif name == "collect_channel_snapshots":
                collected = int(summary.get("channel_snapshots_collected", 0) or 0)
                if collected > 0 and persisted:
                    status = ResearchOperationStatus.SUCCEEDED
                elif collected > 0:
                    status = ResearchOperationStatus.PARTIAL
                    error = "channel_snapshots_collected_but_persistence_not_confirmed"
                else:
                    status = ResearchOperationStatus.BLOCKED
                    error = "; ".join(summary.get("channel_stats_errors") or []) or "no_channel_snapshots_collected"
                result = {
                    "channel_snapshots_collected": collected,
                    "channel_stats_calls": int(summary.get("channel_stats_calls", 0) or 0),
                    "errors": list(summary.get("channel_stats_errors") or []),
                    "persisted": persisted,
                }
            elif name in {"collect_niche_evidence", "build_niche_snapshots"}:
                status = ResearchOperationStatus.BLOCKED
                error = f"operation_handler_not_implemented: {name}"
            else:
                status = ResearchOperationStatus.BLOCKED
                error = f"unknown_operation_type: {name}"

            operation.status = status
            if quota_status is not None:
                result["quota_status"] = quota_status
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
            if getattr(operation, "status", None) in {
                ResearchOperationStatus.SUCCEEDED,
                ResearchOperationStatus.SKIPPED,
            }:
                continue
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
