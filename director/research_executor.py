"""Execute Director research plans through the YouTube MCP and persist DATA."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from data.youtube import (
    YouTubeQuery,
    YouTubeSnapshot,
    YouTubeVideo,
    snapshot_from_mapping,
    video_from_mapping,
)
from data.research_sets import ResearchSet
from data.opportunity_entities import YouTubeChannel


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


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


class YouTubeResearchExecutor:
    """Research execution layer: Director decides, this layer collects."""

    def __init__(self, *, data_adapter: Any, storage: Any = None) -> None:
        self.data = data_adapter
        self.storage = storage

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
        successful_queries = 0
        failed_queries = 0
        errors: list[str] = []

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
                        },
                    )
                    registry.add_query(query)
                    collected_queries.append(query)
                    research.add_query(query)

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
                        items = payload.get("items") or []

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
                                relations.link_research_query(research, query)
                                relations.link_query_video(query, video)
                                relations.link_research_video(research, video)
                                relations.link_research_snapshot(research, snapshot)
                                relations.link_video_snapshot(video, snapshot)

                            snippet = item.get("snippet") or {}
                            channel_id = snippet.get("channelId") or video.channel_id
                            if channel_id and opportunity_registry is not None:
                                opportunity_registry.add_channel(
                                    YouTubeChannel(
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
                                )

                        query.status = "completed"
                        successful_queries += 1

                    except Exception as exc:
                        query.status = "failed"
                        failed_queries += 1
                        errors.append(f"{text}: {type(exc).__name__}: {exc}")

        research.mark_data_gathered("queries", "research_set")
        if registry.videos():
            research.mark_data_gathered("videos")
        if registry.snapshots():
            research.mark_data_gathered("video_snapshots")
        if relations is not None and relations.relation_count() > 0:
            research.mark_data_gathered("relations")

        if failed_queries:
            research.mark_partial()
        else:
            research.mark_complete()

        if self.storage is not None:
            await _maybe_await(
                self.storage.save_research_data(
                    project_id=project_id,
                    queries=registry.queries(),
                    research_sets=research_manager.all() if research_manager is not None else [research],
                    relations=relations.all_relations() if relations is not None else [],
                )
            )
            if opportunity_registry is not None:
                await _maybe_await(
                    self.storage.save_opportunity_data(
                        project_id=project_id,
                        data=opportunity_registry.to_dict(),
                    )
                )

        return {
            "status": research.status,
            "research_id": plan.research_id,
            "queries_planned": len(plan.queries),
            "queries_collected": successful_queries,
            "queries_failed": failed_queries,
            "videos_collected": len(research.video_ids),
            "snapshots_collected": len(research.snapshot_ids),
            "relations_created": relations.relation_count() if relations is not None else 0,
            "errors": errors,
            "source": "youtube-mcp",
            "mcp_url": mcp_url,
            "completed_at": _now(),
        }
