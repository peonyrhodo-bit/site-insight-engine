"""
Supabase Memory Backend — Memory 2.0

Storage adapter for Director Memory.

Architecture:

Director
↓
Memory
↓
SupabaseMemoryBackend
↓
Supabase

This file contains all storage-specific knowledge.

IMPORTANT:
No database migration is performed here.

Existing tables are preserved.
Rich Memory 2.0 fields are stored inside data_json where possible.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on some platforms
    resource = None

from supabase import Client, create_client

logger = logging.getLogger(__name__)


def _peak_rss_raw() -> int | None:
    """Return the platform's raw process peak-RSS counter when available."""
    if resource is None:
        return None
    try:
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return None

class SupabaseMemoryBackend:
    """Supabase implementation of MemoryBackend."""

    TABLE_RUNS = "director_runs"
    TABLE_DECISIONS = "decisions"
    TABLE_CHAT = "chat_messages"
    TABLE_ACTIONS = "director_actions"
    TABLE_RESULTS = "director_results"
    TABLE_EVENTS = "system_events"

    TABLE_RECOMMENDATIONS = "recommendations"
    TABLE_RECOMMENDATION_FEEDBACK = (
        "recommendation_feedback"
    )
    TABLE_CONSTRAINTS = "constraints"

    # DATA / Research persistence
    TABLE_YOUTUBE_QUERIES = "youtube_queries"
    TABLE_RESEARCH_SETS = "research_sets"
    TABLE_DATA_RELATIONS = "data_relations"

    def __init__(
        self,
        client: Client | None = None,
    ) -> None:
        if client is not None:
            self.client = client
            return

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")

        if not supabase_url:
            raise ValueError(
                "SUPABASE_URL is not configured"
            )

        if not supabase_key:
            raise ValueError(
                "SUPABASE_KEY is not configured"
            )

        self.client = create_client(
            supabase_url,
            supabase_key,
        )

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_dict(
        value: Any,
    ) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _safe_list(
        response: Any,
    ) -> list[dict[str, Any]]:
        if response is None:
            return []

        data = getattr(
            response,
            "data",
            None,
        )

        if not isinstance(data, list):
            return []

        return [
            row
            for row in data
            if isinstance(row, dict)
        ]

    @classmethod
    def _first_id(
        cls,
        response: Any,
    ) -> int | None:
        rows = cls._safe_list(response)

        if not rows:
            return None

        value = rows[0].get("id")

        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _limit(
        value: int,
        default: int = 20,
    ) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default

        # Callers choose the intended history window. Do not silently clamp
        # research/channel/relation reads to 100 rows.
        return max(1, value)

    @classmethod
    def _project_id_from_value(
        cls,
        value: Any,
    ) -> str | None:
        """Find an existing project_id anywhere in persisted DATA metadata."""
        if isinstance(value, dict):
            direct = value.get("project_id")
            if direct is not None:
                return str(direct)

            for nested in value.values():
                found = cls._project_id_from_value(nested)
                if found is not None:
                    return found

        elif isinstance(value, list):
            for nested in value:
                found = cls._project_id_from_value(nested)
                if found is not None:
                    return found

        return None

    @classmethod
    def _project_id_from_row(
        cls,
        row: dict[str, Any],
    ) -> str | None:
        direct = row.get("project_id")
        if direct is not None:
            return str(direct)

        return cls._project_id_from_value(
            row.get("data_json")
        )

    def _recent_for_project(
        self,
        table_name: str,
        *,
        limit: int | None,
        project_id: str | None,
        order_key: str = "created_at",
        default_limit: int = 20,
        page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        """Load the requested newest rows without relying on the API's default cap.

        Project IDs can live either in a dedicated column or in legacy nested
        data_json, so filtering is done after each page is read. Stable ordering
        (with id as a tie-breaker) keeps offset pagination deterministic.
        """
        page_size = max(1, int(page_size))
        requested_limit = (
            None if limit is None else self._limit(limit, default_limit)
        )
        rows: list[dict[str, Any]] = []
        offset = 0
        expected_project = str(project_id) if project_id is not None else None

        while True:
            query = (
                self.client
                .table(table_name)
                .select("*")
                .order(order_key, desc=True)
            )
            if order_key != "id":
                query = query.order("id", desc=True)

            response = (
                query
                .range(offset, offset + page_size - 1)
                .execute()
            )
            page = self._safe_list(response)
            for row in page:
                if expected_project is not None and self._project_id_from_row(row) != expected_project:
                    continue
                rows.append(row)
                # Results are ordered newest-first, so stop as soon as the
                # requested project-specific working set has been collected.
                if requested_limit is not None and len(rows) >= requested_limit:
                    return rows

            if len(page) < page_size:
                break

            offset += page_size

        return rows

    # ------------------------------------------------------------------
    # YOUTUBE DATA
    # ------------------------------------------------------------------

    def _iter_paginated_rows(
        self,
        table_name: str,
        *,
        order_key: str,
        descending: bool = False,
        page_size: int = 500,
        columns: str = "*",
    ):
        """Yield one page at a time instead of retaining an entire table in RAM.

        The database remains the source of truth; callers choose a bounded
        working set while every page is fetched in stable order.
        """
        page_size = max(1, min(int(page_size), 1000))
        offset = 0

        while True:
            response = (
                self.client
                .table(table_name)
                .select(columns)
                .order(order_key, desc=descending)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            page = self._safe_list(response)
            yield from page

            if len(page) < page_size:
                break

            offset += page_size

    def load_youtube_data(
        self,
        *,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Load persisted YouTube DATA into a registry-compatible payload.

        Existing videos/snapshots are stored in the dedicated DATA tables;
        this method is the persistence -> DATA boundary and does not change
        their schema.
        """
        from data.youtube import (
            YouTubeSnapshot,
            YouTubeVideo,
        )

        started_at = time.monotonic()
        video_rows_scanned = 0
        snapshot_rows_scanned = 0
        expected_project = (
            str(project_id)
            if project_id is not None
            else None
        )

        video_rows = self._iter_paginated_rows(
            "videos",
            order_key="video_id",
        )

        videos: list[dict[str, Any]] = []
        video_ids: set[str] = set()

        for row in video_rows:
            video_rows_scanned += 1
            row_project = self._project_id_from_row(row)

            if (
                expected_project is not None
                and row_project != expected_project
            ):
                continue

            data = self._safe_dict(row.get("data_json"))
            snippet = self._safe_dict(data.get("snippet"))
            video_id = row.get("video_id") or data.get("id")

            if video_id is None:
                continue

            video = YouTubeVideo(
                video_id=video_id,
                youtube_id=str(video_id),
                title=str(snippet.get("title") or ""),
                channel_id=snippet.get("channelId"),
                channel_title=snippet.get("channelTitle"),
                description=snippet.get("description"),
                published_at=snippet.get("publishedAt"),
                first_seen_at=row.get("first_seen"),
                last_seen_at=row.get("last_seen"),
                source="supabase",
                metadata=data,
            )

            videos.append(video.to_dict())
            video_ids.add(str(video.video_id))

        # Keep the newest few observations per video in the in-memory working set.
        # Older observations remain untouched in Supabase and can be queried
        # for offline/history-specific analysis when needed.
        try:
            snapshots_per_video = max(
                1, min(int(os.getenv("DIRECTOR_SNAPSHOTS_PER_VIDEO", "2")), 20)
            )
        except (TypeError, ValueError):
            snapshots_per_video = 2

        snapshots: list[dict[str, Any]] = []
        snapshot_counts: dict[str, int] = {}

        # Descending IDs mean the newest observations are encountered first.
        # Stream rows and discard old observations before constructing objects.
        for row in self._iter_paginated_rows(
            "video_snapshots",
            order_key="id",
            descending=True,
        ):
            snapshot_rows_scanned += 1
            row_project = self._project_id_from_row(row)

            if expected_project is not None:
                if row_project is not None:
                    if row_project != expected_project:
                        continue
                elif str(row.get("video_id")) not in video_ids:
                    continue

            video_key = str(row.get("video_id") or "")
            if not video_key:
                continue
            seen_for_video = snapshot_counts.get(video_key, 0)
            if seen_for_video >= snapshots_per_video:
                continue
            snapshot_counts[video_key] = seen_for_video + 1

            data = self._safe_dict(row.get("data_json"))
            statistics = self._safe_dict(data.get("statistics"))
            radar = self._safe_dict(data.get("_radar"))

            metrics = dict(statistics)
            for key in (
                "views",
                "age_hours",
                "engagement",
                "views_per_hour",
            ):
                if key in radar:
                    metrics[key] = radar[key]

            snapshot_id = data.get("snapshot_id") or row.get("id")
            video_id = row.get("video_id")

            if snapshot_id is None or video_id is None:
                continue

            snapshot = YouTubeSnapshot(
                snapshot_id=snapshot_id,
                video_id=video_id,
                captured_at=row.get("created_at"),
                metrics=metrics,
                metadata=data,
                source="supabase",
            )

            snapshots.append(snapshot.to_dict())

        logger.info(
            "SUPABASE YOUTUBE DATA LOADED: project_id=%s video_rows_scanned=%d "
            "videos_loaded=%d snapshot_rows_scanned=%d snapshots_loaded=%d "
            "snapshots_per_video=%d elapsed_seconds=%.3f peak_rss_raw=%s",
            expected_project or "all",
            video_rows_scanned,
            len(videos),
            snapshot_rows_scanned,
            len(snapshots),
            snapshots_per_video,
            time.monotonic() - started_at,
            _peak_rss_raw(),
        )
        return {
            "queries": [],
            "videos": videos,
            "snapshots": snapshots,
        }

    @staticmethod
    def _analysis_metadata(data: dict[str, Any]) -> dict[str, Any]:
        """Keep bounded fields needed for topic, channel and recency analysis."""
        result: dict[str, Any] = {}
        snippet = data.get("snippet")
        if isinstance(snippet, dict):
            compact_snippet: dict[str, Any] = {}
            for key in ("title", "channelId", "channelTitle", "publishedAt", "categoryId"):
                value = snippet.get(key)
                if value is not None:
                    compact_snippet[key] = str(value)[:500] if isinstance(value, str) else value
            tags = snippet.get("tags")
            if isinstance(tags, (list, tuple)):
                compact_tags = [str(tag)[:120] for tag in tags[:30] if tag]
                if compact_tags:
                    compact_snippet["tags"] = compact_tags
                    result["tags"] = compact_tags
            if compact_snippet:
                result["snippet"] = compact_snippet

        list_fields = {
            "topics", "categories", "niches", "thematic_directions",
            "keywords", "tags", "search_terms", "search_keywords",
            "subtopics", "sub_topics",
        }
        scalar_fields = {
            "topic", "category", "niche", "thematic_direction",
            "duration_seconds", "duration",
        }
        for key in list_fields | scalar_fields:
            value = data.get(key)
            if value is None:
                continue
            if key in list_fields:
                values = value if isinstance(value, (list, tuple, set)) else [value]
                result[key] = [str(item)[:120] for item in list(values)[:30] if item is not None]
            elif isinstance(value, str):
                result[key] = value[:500]
            else:
                result[key] = value
        return result

    def load_youtube_analysis_data(
        self,
        *,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Load a compact Director working set without retaining full video payloads.

        Rows are streamed from Supabase page by page. Only topic metadata and
        the newest configured number of numeric snapshots per video are kept
        in memory. Full source records and older history remain in Supabase.
        """
        from data.youtube import YouTubeSnapshot, YouTubeVideo

        started_at = time.monotonic()
        expected_project = str(project_id) if project_id is not None else None
        page_size = max(50, min(int(os.getenv("DIRECTOR_ANALYSIS_PAGE_SIZE", "500")), 1000))
        videos: list[dict[str, Any]] = []
        video_ids: set[str] = set()
        video_rows_scanned = 0

        for row in self._iter_paginated_rows(
            "videos",
            order_key="video_id",
            page_size=page_size,
            columns="video_id,data_json,first_seen,last_seen",
        ):
            video_rows_scanned += 1
            if expected_project is not None and self._project_id_from_row(row) != expected_project:
                continue

            data = self._safe_dict(row.get("data_json"))
            snippet = self._safe_dict(data.get("snippet"))
            video_id = row.get("video_id") or data.get("id")
            if video_id is None:
                continue

            compact_metadata = self._analysis_metadata(data)
            video = YouTubeVideo(
                video_id=video_id,
                youtube_id=str(video_id),
                title=str(snippet.get("title") or data.get("title") or ""),
                channel_id=snippet.get("channelId") or data.get("channel_id"),
                channel_title=snippet.get("channelTitle") or data.get("channel_title"),
                description=None,
                published_at=snippet.get("publishedAt") or data.get("published_at"),
                first_seen_at=row.get("first_seen"),
                last_seen_at=row.get("last_seen"),
                source="supabase_analysis",
                metadata=compact_metadata,
            )
            videos.append(video.to_dict())
            video_ids.add(str(video_id))

        try:
            snapshots_per_video = max(
                1, min(int(os.getenv("DIRECTOR_SNAPSHOTS_PER_VIDEO", "2")), 20)
            )
        except (TypeError, ValueError):
            snapshots_per_video = 2

        snapshots: list[dict[str, Any]] = []
        snapshot_counts: dict[str, int] = {}
        snapshot_rows_scanned = 0

        for row in self._iter_paginated_rows(
            "video_snapshots",
            order_key="id",
            descending=True,
            page_size=page_size,
            columns="id,video_id,created_at,data_json",
        ):
            snapshot_rows_scanned += 1
            row_project = self._project_id_from_row(row)
            if expected_project is not None:
                if row_project is not None and row_project != expected_project:
                    continue
                if row_project is None and str(row.get("video_id")) not in video_ids:
                    continue

            video_key = str(row.get("video_id") or "")
            if not video_key:
                continue
            seen = snapshot_counts.get(video_key, 0)
            if seen >= snapshots_per_video:
                continue

            data = self._safe_dict(row.get("data_json"))
            statistics = self._safe_dict(data.get("statistics"))
            radar = self._safe_dict(data.get("_radar"))
            metrics = dict(statistics)
            for key in ("views", "age_hours", "engagement", "views_per_hour"):
                if key in radar:
                    metrics[key] = radar[key]

            snapshot_id = data.get("snapshot_id") or row.get("id")
            if snapshot_id is None:
                continue

            snapshot = YouTubeSnapshot(
                snapshot_id=snapshot_id,
                video_id=row.get("video_id"),
                captured_at=row.get("created_at"),
                metrics=metrics,
                metadata={},
                source="supabase_analysis",
            )
            snapshots.append(snapshot.to_dict())
            snapshot_counts[video_key] = seen + 1

        logger.info(
            "SUPABASE COMPACT ANALYSIS DATA LOADED: project_id=%s "
            "video_rows_scanned=%d videos=%d snapshot_rows_scanned=%d "
            "snapshots=%d snapshots_per_video=%d page_size=%d "
            "elapsed_seconds=%.3f peak_rss_raw=%s",
            expected_project or "all", video_rows_scanned, len(videos),
            snapshot_rows_scanned, len(snapshots), snapshots_per_video,
            page_size, time.monotonic() - started_at, _peak_rss_raw(),
        )
        return {"queries": [], "videos": videos, "snapshots": snapshots}

    def save_youtube_data(
        self,
        *,
        project_id: str,
        videos: list[dict[str, Any]] | None = None,
        snapshots: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Persist normalized YouTube DATA returned by Research/MCP."""
        project_id = str(project_id)
        saved_videos = 0
        saved_snapshots = 0
        snapshot_ids: list[int] = []
        saved_video_ids: list[str] = []
        saved_snapshot_video_ids: list[str] = []
        saved_snapshot_query_ids: list[list[str]] = []

        for video in videos or []:
            if not isinstance(video, dict):
                continue
            video_id = str(video.get("video_id") or "").strip()
            if not video_id:
                continue
            data_json = self._safe_dict(video.get("metadata"))
            data_json["project_id"] = project_id
            payload = {
                "video_id": video_id,
                "data_json": data_json,
                "first_seen": video.get("first_seen_at"),
                "last_seen": video.get("last_seen_at"),
            }
            response = (
                self.client.table("videos")
                .upsert(payload, on_conflict="video_id")
                .select("video_id")
                .execute()
            )
            if self._safe_list(response):
                saved_videos += 1
                saved_video_ids.append(video_id)

        for snapshot in snapshots or []:
            if not isinstance(snapshot, dict):
                continue
            video_id = str(snapshot.get("video_id") or "").strip()
            if not video_id:
                continue
            data_json = self._safe_dict(snapshot.get("metadata"))
            data_json["project_id"] = project_id
            data_json["snapshot_id"] = snapshot.get("snapshot_id")
            data_json["research_id"] = snapshot.get("research_id")
            data_json["query_ids"] = list(snapshot.get("query_ids") or [])
            data_json["statistics"] = self._safe_dict(
                snapshot.get("metrics")
            )
            payload = {
                "video_id": video_id,
                "data_json": data_json,
            }
            response = (
                self.client.table("video_snapshots")
                .insert(payload)
                .select("id")
                .execute()
            )
            row_id = self._first_id(response)
            if row_id is not None:
                saved_snapshots += 1
                snapshot_ids.append(row_id)
                saved_snapshot_video_ids.append(video_id)
                saved_snapshot_query_ids.append([str(value) for value in (snapshot.get("query_ids") or [])])

        return {
            "videos": saved_videos,
            "snapshots": saved_snapshots,
            "snapshot_ids": snapshot_ids,
            "video_ids": saved_video_ids,
            "snapshot_video_ids": saved_snapshot_video_ids,
            "snapshot_query_ids": saved_snapshot_query_ids,
        }


    # ------------------------------------------------------------------
    # OPPORTUNITY DATA
    # ------------------------------------------------------------------

    def save_opportunity_data(self, *, project_id: str, data: dict[str, Any]) -> dict[str, int]:
        counts = {"channels": 0, "channel_snapshots": 0, "niches": 0, "niche_snapshots": 0}
        pid = str(project_id)

        for item in data.get("channels") or []:
            if not isinstance(item, dict) or not item.get("channel_id"):
                continue
            payload = {
                "project_id": pid,
                "channel_id": str(item["channel_id"]),
                "title": item.get("title", ""),
                "description": item.get("description"),
                "custom_url": item.get("custom_url"),
                "country": item.get("country"),
                "published_at": item.get("published_at"),
                "video_count": item.get("video_count"),
                "subscriber_count": item.get("subscriber_count"),
                "view_count": item.get("view_count"),
                "data_json": self._safe_dict(item.get("data") or item.get("data_json")),
            }
            self.client.table("channels").upsert(payload, on_conflict="project_id,channel_id").execute()
            counts["channels"] += 1

        for item in data.get("channel_snapshots") or []:
            if not isinstance(item, dict) or not item.get("channel_id"):
                continue
            payload = {
                "project_id": pid,
                "channel_id": str(item["channel_id"]),
                "captured_at": item.get("captured_at"),
                "subscriber_count": item.get("subscriber_count"),
                "video_count": item.get("video_count"),
                "view_count": item.get("view_count"),
                "new_video_count": item.get("new_video_count"),
                "subscriber_growth": item.get("subscriber_growth"),
                "view_growth": item.get("view_growth"),
                "data_json": self._safe_dict(item.get("data") or item.get("data_json")),
            }
            self.client.table("channel_snapshots").upsert(payload, on_conflict="project_id,channel_id,captured_at").execute()
            counts["channel_snapshots"] += 1

        for item in data.get("niches") or []:
            if not isinstance(item, dict) or not item.get("niche_id"):
                continue
            payload = {
                "project_id": pid,
                "niche_id": str(item["niche_id"]),
                "name": item.get("name", ""),
                "description": item.get("description"),
                "aliases": item.get("aliases") or [],
                "language": item.get("language"),
                "region": item.get("region"),
                "status": item.get("status", "active"),
                "data_json": self._safe_dict(item.get("data") or item.get("data_json")),
            }
            self.client.table("niches").upsert(payload, on_conflict="project_id,niche_id").execute()
            counts["niches"] += 1

        for item in data.get("niche_snapshots") or []:
            if not isinstance(item, dict) or not item.get("niche_id"):
                continue
            payload = {
                "project_id": pid,
                "niche_id": str(item["niche_id"]),
                "captured_at": item.get("captured_at"),
                "video_count": item.get("video_count"),
                "channel_count": item.get("channel_count"),
                "median_views": item.get("median_views"),
                "average_views": item.get("average_views"),
                "growth_rate": item.get("growth_rate"),
                "new_video_count": item.get("new_video_count"),
                "new_channel_count": item.get("new_channel_count"),
                "top_channel_share": item.get("top_channel_share"),
                "competition_score": item.get("competition_score"),
                "opportunity_score": item.get("opportunity_score"),
                "data_json": self._safe_dict(item.get("data") or item.get("data_json")),
            }
            self.client.table("niche_snapshots").upsert(payload, on_conflict="project_id,niche_id,captured_at").execute()
            counts["niche_snapshots"] += 1

        return counts

    # DATA / RESEARCH
    # ------------------------------------------------------------------

    def load_research_data(self, *, project_id: str | None = None) -> dict[str, Any]:
        """Load persisted research/query/relation DATA for one project."""
        expected_project = str(project_id) if project_id is not None else None
        # Keep the process-local graph bounded. The complete history remains
        # in Supabase; Director startup only needs a recent working index.
        return {
            "queries": self._recent_for_project(self.TABLE_YOUTUBE_QUERIES, limit=2000, project_id=expected_project, order_key="id", default_limit=2000),
            "research_sets": self._recent_for_project(self.TABLE_RESEARCH_SETS, limit=1000, project_id=expected_project, order_key="id", default_limit=1000),
            "relations": self._recent_for_project(self.TABLE_DATA_RELATIONS, limit=5000, project_id=expected_project, order_key="id", default_limit=5000),
        }

    def save_youtube_query(self, *, project_id: str, query: dict[str, Any]) -> int | None:
        query = self._safe_dict(query)
        query_id = str(query.get("query_id") or "").strip()
        if not query_id:
            raise ValueError("query_id is required")
        payload = {
            "project_id": str(project_id), "query_id": query_id,
            "text": query.get("text", ""), "language": query.get("language"),
            "region": query.get("region"), "metadata": self._safe_dict(query.get("metadata")),
            "source": query.get("source"), "status": query.get("status", "planned"),
        }
        response = self.client.table(self.TABLE_YOUTUBE_QUERIES).upsert(payload, on_conflict="project_id,query_id").select("id").execute()
        return self._first_id(response)

    def save_research_set(self, *, project_id: str, research: dict[str, Any]) -> int | None:
        research = self._safe_dict(research)
        research_id = str(research.get("research_id") or "").strip()
        if not research_id:
            raise ValueError("research_id is required")
        payload = {
            "project_id": str(project_id), "research_id": research_id,
            "name": research.get("name", ""), "objective": research.get("objective", ""),
            "language": research.get("language"), "region": research.get("region"),
            "languages": research.get("languages") or [], "regions": research.get("regions") or [],
            "query_ids": research.get("query_ids") or [], "video_ids": research.get("video_ids") or [],
            "snapshot_ids": research.get("snapshot_ids") or [], "gathered_data": research.get("gathered_data") or [],
            "missing_data": research.get("missing_data") or [], "reusable_video_ids": research.get("reusable_video_ids") or [],
            "reused_video_ids": research.get("reused_video_ids") or [], "source": research.get("source"),
            "status": research.get("status", "planned"), "created_at": research.get("created_at"),
            "updated_at": research.get("updated_at"), "completed_at": research.get("completed_at"),
            "metadata": self._safe_dict(research.get("metadata")), "expected_data": research.get("expected_data") or [],
        }
        response = self.client.table(self.TABLE_RESEARCH_SETS).upsert(payload, on_conflict="project_id,research_id").select("id").execute()
        return self._first_id(response)

    def save_data_relation(self, *, project_id: str, relation: dict[str, Any]) -> int | None:
        relation = self._safe_dict(relation)
        payload = {
            "project_id": str(project_id), "source_type": relation.get("source_type"),
            "source_id": str(relation.get("source_id")), "relation": relation.get("relation"),
            "target_type": relation.get("target_type"), "target_id": str(relation.get("target_id")),
            "metadata": self._safe_dict(relation.get("metadata")),
        }
        response = self.client.table(self.TABLE_DATA_RELATIONS).upsert(payload, on_conflict="project_id,source_type,source_id,relation,target_type,target_id").select("id").execute()
        return self._first_id(response)

    def save_research_data(self, *, project_id: str, queries: list[dict[str, Any]] | None = None, research_sets: list[dict[str, Any]] | None = None, relations: list[dict[str, Any]] | None = None) -> dict[str, int]:
        """Persist the current DATA graph using idempotent upserts."""
        saved = {"queries": 0, "research_sets": 0, "relations": 0}
        for query in queries or []:
            if self.save_youtube_query(project_id=project_id, query=query) is not None: saved["queries"] += 1
        for research in research_sets or []:
            if self.save_research_set(project_id=project_id, research=research) is not None: saved["research_sets"] += 1
        for relation in relations or []:
            if self.save_data_relation(project_id=project_id, relation=relation) is not None: saved["relations"] += 1
        return saved

    # ------------------------------------------------------------------
    # OPPORTUNITY DATA (channels / niches / historical snapshots)
    # ------------------------------------------------------------------

    TABLE_CHANNELS = "channels"
    TABLE_CHANNEL_SNAPSHOTS = "channel_snapshots"
    TABLE_NICHES = "niches"
    TABLE_NICHE_SNAPSHOTS = "niche_snapshots"

    def load_opportunity_data(self, *, project_id: str | None = None) -> dict[str, Any]:
        """Load a bounded working set; Supabase remains the complete history."""
        expected_project = str(project_id) if project_id is not None else None

        def configured_limit(name: str, default: int, maximum: int) -> int:
            try:
                value = int(os.getenv(name, str(default)))
            except (TypeError, ValueError):
                value = default
            return max(1, min(value, maximum))

        limits = {
            "channels": configured_limit("DIRECTOR_CHANNELS_IN_MEMORY", 500, 2000),
            "channel_snapshots": configured_limit("DIRECTOR_CHANNEL_SNAPSHOTS_IN_MEMORY", 500, 5000),
            "niches": configured_limit("DIRECTOR_NICHES_IN_MEMORY", 250, 1000),
            "niche_snapshots": configured_limit("DIRECTOR_NICHE_SNAPSHOTS_IN_MEMORY", 500, 5000),
        }
        started_at = time.monotonic()
        result = {
            "channels": self._recent_for_project(
                self.TABLE_CHANNELS, limit=limits["channels"],
                project_id=expected_project, order_key="id",
                default_limit=limits["channels"],
            ),
            "channel_snapshots": self._recent_for_project(
                self.TABLE_CHANNEL_SNAPSHOTS, limit=limits["channel_snapshots"],
                project_id=expected_project, order_key="captured_at",
                default_limit=limits["channel_snapshots"],
            ),
            "niches": self._recent_for_project(
                self.TABLE_NICHES, limit=limits["niches"],
                project_id=expected_project, order_key="id",
                default_limit=limits["niches"],
            ),
            "niche_snapshots": self._recent_for_project(
                self.TABLE_NICHE_SNAPSHOTS, limit=limits["niche_snapshots"],
                project_id=expected_project, order_key="captured_at",
                default_limit=limits["niche_snapshots"],
            ),
        }
        logger.info(
            "SUPABASE OPPORTUNITY DATA LOADED: project_id=%s counts=%s limits=%s elapsed_seconds=%.3f peak_rss_raw=%s",
            expected_project or "all",
            {key: len(rows) for key, rows in result.items()},
            limits,
            time.monotonic() - started_at,
            _peak_rss_raw(),
        )
        return result

    def save_opportunity_data(self, *, project_id: str, data: dict[str, Any]) -> dict[str, int]:
        """Persist channel/niche identities and snapshots idempotently."""
        project_id = str(project_id)
        saved = {"channels": 0, "channel_snapshots": 0, "niches": 0, "niche_snapshots": 0}

        for item in data.get("channels") or []:
            if not isinstance(item, dict) or not item.get("channel_id"):
                continue
            payload = dict(item)
            payload["project_id"] = project_id
            payload["data_json"] = payload.pop("data_json", payload.pop("data", {})) or {}
            response = self.client.table(self.TABLE_CHANNELS).upsert(payload, on_conflict="project_id,channel_id").select("id").execute()
            if self._first_id(response) is not None:
                saved["channels"] += 1

        for item in data.get("channel_snapshots") or []:
            if not isinstance(item, dict) or not item.get("channel_id") or not item.get("captured_at"):
                continue
            payload = dict(item)
            payload["project_id"] = project_id
            payload["data_json"] = payload.pop("data_json", payload.pop("data", {})) or {}
            response = self.client.table(self.TABLE_CHANNEL_SNAPSHOTS).upsert(payload, on_conflict="project_id,channel_id,captured_at").select("id").execute()
            if self._first_id(response) is not None:
                saved["channel_snapshots"] += 1

        for item in data.get("niches") or []:
            if not isinstance(item, dict) or not item.get("niche_id") or not item.get("name"):
                continue
            payload = dict(item)
            payload["project_id"] = project_id
            payload["data_json"] = payload.pop("data_json", payload.pop("data", {})) or {}
            response = self.client.table(self.TABLE_NICHES).upsert(payload, on_conflict="project_id,niche_id").select("id").execute()
            if self._first_id(response) is not None:
                saved["niches"] += 1

        for item in data.get("niche_snapshots") or []:
            if not isinstance(item, dict) or not item.get("niche_id") or not item.get("captured_at"):
                continue
            payload = dict(item)
            payload["project_id"] = project_id
            payload["data_json"] = payload.pop("data_json", payload.pop("data", {})) or {}
            response = self.client.table(self.TABLE_NICHE_SNAPSHOTS).upsert(payload, on_conflict="project_id,niche_id,captured_at").select("id").execute()
            if self._first_id(response) is not None:
                saved["niche_snapshots"] += 1

        return saved

    # ------------------------------------------------------------------
    # CONTEXT
    # ------------------------------------------------------------------

    def get_context(
        self,
        *,
        project_id: str | None = None,
        limit_runs: int = 10,
        limit_decisions: int = 20,
        limit_events: int = 30,
        limit_chat: int = 20,
        limit_actions: int = 20,
        limit_results: int = 20,
        limit_recommendations: int = 20,
        limit_constraints: int = 20,
    ) -> dict[str, Any]:
        return {
            "runs": self.get_recent_runs(
                limit=limit_runs,
                project_id=project_id
            ),
            "decisions": self.get_recent_decisions(
                limit=limit_decisions,
                project_id=project_id
            ),
            "recommendations": (
                self.get_recent_recommendations(
                    limit=limit_recommendations,
                    project_id=project_id
                )
            ),
            "constraints": (
                self.get_recent_constraints(
                    limit=limit_constraints,
                    project_id=project_id
                )
            ),
            "events": self.get_recent_events(
                limit=limit_events,
                project_id=project_id
            ),
            "chat": self.get_recent_chat_messages(
                limit=limit_chat,
                project_id=project_id
            ),
            "actions": self.get_recent_actions(
                limit=limit_actions,
                project_id=project_id
            ),
            "results": self.get_recent_results(
                limit=limit_results,
                project_id=project_id
            ),
        }

    # ------------------------------------------------------------------
    # RUNS
    # ------------------------------------------------------------------

    def save_run(
        self,
        *,
        language: str | None = None,
        region_code: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        run_data = self._safe_dict(data)
        payload = {
            "language": language,
            "region_code": region_code,
            "data_json": run_data,
        }
        for field in ("project_id", "status", "started_at", "finished_at", "current_step", "error_message", "updated_at"):
            if field in run_data:
                payload[field] = run_data[field]

        response = (
            self.client
            .table(self.TABLE_RUNS)
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

    def update_run(self, *, run_id: int, data: dict[str, Any]) -> bool:
        current = self.client.table(self.TABLE_RUNS).select("data_json").eq("id", run_id).limit(1).execute()
        rows = self._safe_list(current)
        if not rows:
            return False
        merged = {**self._safe_dict(rows[0].get("data_json")), **self._safe_dict(data)}
        payload: dict[str, Any] = {"data_json": merged}
        for field in ("project_id", "status", "started_at", "finished_at", "current_step", "error_message", "updated_at"):
            if field in data:
                payload[field] = data[field]
        response = self.client.table(self.TABLE_RUNS).update(payload).eq("id", run_id).select("id").execute()
        return bool(self._safe_list(response))

    def get_recent_runs(
        self,
        *,
        limit: int = 10,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._recent_for_project(
            self.TABLE_RUNS,
            limit=limit,
            project_id=project_id,
            order_key="created_at",
            default_limit=10,
        )

    # ------------------------------------------------------------------
    # DECISIONS
    # ------------------------------------------------------------------

    def save_decision(
        self,
        *,
        decision: str,
        data: dict[str, Any] | None = None,
        run_id: int | None = None,
    ) -> int | None:
        payload = {
            "decision": decision,
            "run_id": run_id,
            "data_json": self._safe_dict(data),
        }

        response = (
            self.client
            .table(self.TABLE_DECISIONS)
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

    def get_recent_decisions(
        self,
        *,
        limit: int = 20,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._recent_for_project(
            self.TABLE_DECISIONS,
            limit=limit,
            project_id=project_id,
            order_key="created_at",
            default_limit=20,
        )

    # ------------------------------------------------------------------
    # CHAT
    # ------------------------------------------------------------------

    def save_chat_message(
        self,
        *,
        role: str,
        message: str,
        run_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        payload = {
            "role": role,
            "message": message,
            "run_id": run_id,
            "data_json": self._safe_dict(data),
        }

        response = (
            self.client
            .table(self.TABLE_CHAT)
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

    def get_recent_chat_messages(
        self,
        *,
        limit: int = 20,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._recent_for_project(
            self.TABLE_CHAT,
            limit=limit,
            project_id=project_id,
            order_key="created_at",
            default_limit=20,
        )

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def save_action(
        self,
        *,
        action_type: str,
        description: str = "",
        run_id: int | None = None,
        decision_id: int | None = None,
        status: str = "pending",
        data: dict[str, Any] | None = None,
    ) -> int | None:
        payload = {
            "action_type": action_type,
            "description": description,
            "run_id": run_id,
            "decision_id": decision_id,
            "status": status,
            "data_json": self._safe_dict(data),
        }

        response = (
            self.client
            .table(self.TABLE_ACTIONS)
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

    def get_recent_actions(
        self,
        *,
        limit: int = 20,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._recent_for_project(
            self.TABLE_ACTIONS,
            limit=limit,
            project_id=project_id,
            order_key="created_at",
            default_limit=20,
        )

    # ------------------------------------------------------------------
    # RESULTS
    # ------------------------------------------------------------------

    def save_result(
        self,
        *,
        result_type: str,
        summary: str = "",
        action_id: int | None = None,
        run_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        payload = {
            "result_type": result_type,
            "summary": summary,
            "action_id": action_id,
            "run_id": run_id,
            "data_json": self._safe_dict(data),
        }

        response = (
            self.client
            .table(self.TABLE_RESULTS)
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

    def get_recent_results(
        self,
        *,
        limit: int = 20,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._recent_for_project(
            self.TABLE_RESULTS,
            limit=limit,
            project_id=project_id,
            order_key="created_at",
            default_limit=20,
        )

    # ------------------------------------------------------------------
    # EVENTS
    # ------------------------------------------------------------------

    def save_event(
        self,
        *,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        payload = {
            "event_type": event_type,
            "data_json": self._safe_dict(data),
        }

        response = (
            self.client
            .table(self.TABLE_EVENTS)
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

    def get_recent_events(
        self,
        *,
        limit: int = 30,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._recent_for_project(
            self.TABLE_EVENTS,
            limit=limit,
            project_id=project_id,
            order_key="created_at",
            default_limit=30,
        )

    # ------------------------------------------------------------------
    # RECOMMENDATIONS
    # ------------------------------------------------------------------

    def save_recommendation(
        self,
        *,
        recommendation: dict[str, Any],
    ) -> int | None:
        recommendation = self._safe_dict(
            recommendation
        )

        payload = {
            "run_id": recommendation.get(
                "run_id"
            ),
            "decision_id": recommendation.get(
                "decision_id"
            ),
            "title": recommendation.get(
                "title"
            ),
            "description": recommendation.get(
                "description"
            ),
            "recommendation_type": recommendation.get(
                "recommendation_type"
            ),
            "topic": recommendation.get(
                "topic"
            ),
            "region": recommendation.get(
                "region"
            ),
            "language": recommendation.get(
                "language"
            ),
            "rationale": recommendation.get(
                "rationale"
            ),
            "suggested_action": recommendation.get(
                "suggested_action"
            ),
            "confidence": recommendation.get(
                "confidence"
            ),
            "priority": recommendation.get(
                "priority"
            ),
            "status": recommendation.get(
                "status",
                "pending",
            ),
            "data_json": {
                "source_data": self._safe_dict(
                    recommendation.get(
                        "source_data"
                    )
                ),
                "metadata": self._safe_dict(
                    recommendation.get(
                        "metadata"
                    )
                ),
                "user_response": recommendation.get(
                    "user_response"
                ),
                "result_summary": recommendation.get(
                    "result_summary"
                ),
                "lesson": recommendation.get(
                    "lesson"
                ),
                "shown_at": recommendation.get(
                    "shown_at"
                ),
                "accepted_at": recommendation.get(
                    "accepted_at"
                ),
                "rejected_at": recommendation.get(
                    "rejected_at"
                ),
                "completed_at": recommendation.get(
                    "completed_at"
                ),
            },
        }

        response = (
            self.client
            .table(self.TABLE_RECOMMENDATIONS)
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

    def get_recent_recommendations(
        self,
        *,
        limit: int = 20,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            rows = self._recent_for_project(
                self.TABLE_RECOMMENDATIONS,
                limit=limit,
                project_id=project_id,
                order_key="id",
            )

            for row in rows:
                data = row.get("data_json")

                if isinstance(data, dict):
                    source_data = data.get(
                        "source_data"
                    )

                    metadata = data.get(
                        "metadata"
                    )

                    if isinstance(
                        source_data,
                        dict,
                    ):
                        row["source_data"] = (
                            source_data
                        )

                    if isinstance(
                        metadata,
                        dict,
                    ):
                        row["metadata"] = metadata

                    for key in (
                        "user_response",
                        "result_summary",
                        "lesson",
                        "shown_at",
                        "accepted_at",
                        "rejected_at",
                        "completed_at",
                    ):
                        if key in data:
                            row[key] = data[key]

            return rows

        except Exception:
            return []

    # ------------------------------------------------------------------
    # RECOMMENDATION FEEDBACK
    # ------------------------------------------------------------------

    def save_recommendation_feedback(
        self,
        *,
        feedback: dict[str, Any],
    ) -> int | None:
        feedback = self._safe_dict(feedback)

        data_json = self._safe_dict(
            feedback.get("metadata")
        )

        for key in (
            "reason",
            "priority",
            "creates_constraint",
            "run_id",
            "decision_id",
            "feedback_id",
            "target",
            "constraint",
            "preference",
            "created_at",
            "type",
        ):
            if key in feedback:
                data_json[key] = feedback[key]

        comment = feedback.get("message")
        if comment is None:
            comment = feedback.get("comment")

        payload = {
            "recommendation_id": feedback.get(
                "recommendation_id"
            ),
            "feedback_type": feedback.get(
                "feedback_type"
            ),
            "comment": comment,
            "scope": feedback.get(
                "scope"
            ),
            "topic": feedback.get(
                "topic"
            ),
            "region": feedback.get(
                "region"
            ),
            "language": feedback.get(
                "language"
            ),
            "data_json": data_json,
        }

        response = (
            self.client
            .table(
                self.TABLE_RECOMMENDATION_FEEDBACK
            )
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

    def apply_recommendation_feedback(
        self,
        *,
        feedback: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Persist feedback and return a normalized result.

        Recommendation status updates are deliberately handled
        conservatively. This method does not invent global constraints.
        """

        feedback = self._safe_dict(feedback)

        feedback_id = (
            self.save_recommendation_feedback(
                feedback=feedback
            )
        )

        feedback_type = str(
            feedback.get(
                "feedback_type",
                ""
            )
        ).lower()

        status_map = {
            "accept": "accepted",
            "reject": "rejected",
            "defer": "deferred",
        }

        recommendation_id = feedback.get(
            "recommendation_id"
        )

        updated_status = status_map.get(
            feedback_type
        )

        update_result = None

        if recommendation_id and updated_status:
            try:
                update_result = (
                    self.client
                    .table(
                        self.TABLE_RECOMMENDATIONS
                    )
                    .update(
                        {
                            "status": updated_status
                        }
                    )
                    .eq(
                        "id",
                        recommendation_id,
                    )
                    .execute()
                )
            except Exception:
                update_result = None

        return {
            "feedback_id": feedback_id,
            "recommendation_id": recommendation_id,
            "feedback_type": feedback_type,
            "status": updated_status,
            "updated": update_result is not None,
            "creates_constraint": bool(
                feedback.get(
                    "creates_constraint",
                    False,
                )
            ),
        }

    # ------------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------------

    def save_constraint(
        self,
        *,
        constraint: dict[str, Any],
    ) -> int | None:
        constraint = self._safe_dict(
            constraint
        )

        payload = {
            "title": constraint.get(
                "title"
            ),
            "description": constraint.get(
                "description"
            ),
            "constraint_type": constraint.get(
                "constraint_type",
                "avoid",
            ),
            "scope": constraint.get(
                "scope",
                "recommendation",
            ),
            "status": constraint.get(
                "status",
                "proposed",
            ),
            "topic": constraint.get(
                "topic"
            ),
            "region": constraint.get(
                "region"
            ),
            "language": constraint.get(
                "language"
            ),
            "execution_condition": constraint.get(
                "execution_condition"
            ),
            "reason": constraint.get(
                "reason"
            ),
            "confidence": constraint.get(
                "confidence",
                0.5,
            ),
            "priority": constraint.get(
                "priority",
                0,
            ),
            "source_recommendation_id": constraint.get(
                "source_recommendation_id"
            ),
            "source_feedback_id": constraint.get(
                "source_feedback_id"
            ),
            "source_run_id": constraint.get(
                "source_run_id"
            ),
            "data_json": {
                "active_from": constraint.get(
                    "active_from"
                ),
                "review_at": constraint.get(
                    "review_at"
                ),
                "expires_at": constraint.get(
                    "expires_at"
                ),
                "metadata": self._safe_dict(
                    constraint.get(
                        "metadata"
                    )
                ),
            },
        }

        response = (
            self.client
            .table(self.TABLE_CONSTRAINTS)
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

    def get_recent_constraints(
        self,
        *,
        limit: int = 20,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            rows = self._recent_for_project(
                self.TABLE_CONSTRAINTS,
                limit=limit,
                project_id=project_id,
                order_key="id",
            )

            for row in rows:
                data = row.get("data_json")

                if not isinstance(data, dict):
                    continue

                for key in (
                    "active_from",
                    "review_at",
                    "expires_at",
                ):
                    if key in data:
                        row[key] = data[key]

                metadata = data.get(
                    "metadata"
                )

                if isinstance(metadata, dict):
                    row["metadata"] = metadata

            return rows

        except Exception:
            return []
