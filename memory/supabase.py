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

import os
from typing import Any

from supabase import Client, create_client

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

        return max(1, min(value, 100))

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
        limit: int,
        project_id: str | None,
        order_key: str = "created_at",
        default_limit: int = 20,
    ) -> list[dict[str, Any]]:
        response = (
            self.client
            .table(table_name)
            .select("*")
            .order(order_key, desc=True)
            .execute()
        )
        rows = self._safe_list(response)

        if project_id is not None:
            project_id = str(project_id)
            rows = [
                row
                for row in rows
                if self._project_id_from_row(row) == project_id
            ]

        return rows[: self._limit(limit, default_limit)]

    # ------------------------------------------------------------------
    # YOUTUBE DATA
    # ------------------------------------------------------------------

    def _paginated_rows(
        self,
        table_name: str,
        *,
        order_key: str,
        page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Load all rows from a DATA table using stable, paginated reads.

        Supabase Data API responses are limited to a default maximum of
        1,000 rows, so DATA loading must not rely on one unbounded select.
        """
        rows: list[dict[str, Any]] = []
        offset = 0

        while True:
            response = (
                self.client
                .table(table_name)
                .select("*")
                .order(order_key, desc=False)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            page = self._safe_list(response)
            rows.extend(page)

            if len(page) < page_size:
                break

            offset += page_size

        return rows

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

        expected_project = (
            str(project_id)
            if project_id is not None
            else None
        )

        video_rows = self._paginated_rows(
            "videos",
            order_key="video_id",
        )

        videos: list[dict[str, Any]] = []
        video_ids: set[str] = set()

        for row in video_rows:
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

        snapshot_rows = self._paginated_rows(
            "video_snapshots",
            order_key="id",
        )

        snapshots: list[dict[str, Any]] = []

        for row in snapshot_rows:
            row_project = self._project_id_from_row(row)

            if expected_project is not None:
                if row_project is not None:
                    if row_project != expected_project:
                        continue
                elif str(row.get("video_id")) not in video_ids:
                    continue

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

            snapshot_id = row.get("id")
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

        return {
            "queries": [],
            "videos": videos,
            "snapshots": snapshots,
        }

    # ------------------------------------------------------------------
    # DATA / RESEARCH
    # ------------------------------------------------------------------

    def load_research_data(self, *, project_id: str | None = None) -> dict[str, Any]:
        """Load persisted research/query/relation DATA for one project."""
        expected_project = str(project_id) if project_id is not None else None
        return {
            "queries": self._recent_for_project(self.TABLE_YOUTUBE_QUERIES, limit=100, project_id=expected_project, order_key="id", default_limit=100),
            "research_sets": self._recent_for_project(self.TABLE_RESEARCH_SETS, limit=10000, project_id=expected_project, order_key="id", default_limit=10000),
            "relations": self._recent_for_project(self.TABLE_DATA_RELATIONS, limit=10000, project_id=expected_project, order_key="id", default_limit=10000),
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
        payload = {
            "language": language,
            "region_code": region_code,
            "data_json": self._safe_dict(data),
        }

        response = (
            self.client
            .table(self.TABLE_RUNS)
            .insert(payload)
            .execute()
        )

        return self._first_id(response)

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
