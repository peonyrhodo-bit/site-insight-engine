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
                limit=limit_runs
            ),
            "decisions": self.get_recent_decisions(
                limit=limit_decisions
            ),
            "recommendations": (
                self.get_recent_recommendations(
                    limit=limit_recommendations
                )
            ),
            "constraints": (
                self.get_recent_constraints(
                    limit=limit_constraints
                )
            ),
            "events": self.get_recent_events(
                limit=limit_events
            ),
            "chat": self.get_recent_chat_messages(
                limit=limit_chat
            ),
            "actions": self.get_recent_actions(
                limit=limit_actions
            ),
            "results": self.get_recent_results(
                limit=limit_results
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
    ) -> list[dict[str, Any]]:
        response = (
            self.client
            .table(self.TABLE_RUNS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(self._limit(limit, 10))
            .execute()
        )

        return self._safe_list(response)

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
    ) -> list[dict[str, Any]]:
        response = (
            self.client
            .table(self.TABLE_DECISIONS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(self._limit(limit))
            .execute()
        )

        return self._safe_list(response)

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
    ) -> list[dict[str, Any]]:
        response = (
            self.client
            .table(self.TABLE_CHAT)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(self._limit(limit))
            .execute()
        )

        return self._safe_list(response)

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
    ) -> list[dict[str, Any]]:
        response = (
            self.client
            .table(self.TABLE_ACTIONS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(self._limit(limit))
            .execute()
        )

        return self._safe_list(response)

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
    ) -> list[dict[str, Any]]:
        response = (
            self.client
            .table(self.TABLE_RESULTS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(self._limit(limit))
            .execute()
        )

        return self._safe_list(response)

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
    ) -> list[dict[str, Any]]:
        response = (
            self.client
            .table(self.TABLE_EVENTS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(self._limit(limit, 30))
            .execute()
        )

        return self._safe_list(response)

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
    ) -> list[dict[str, Any]]:
        try:
            response = (
                self.client
                .table(
                    self.TABLE_RECOMMENDATIONS
                )
                .select("*")
                .order(
                    "id",
                    desc=True,
                )
                .limit(self._limit(limit))
                .execute()
            )

            rows = self._safe_list(response)

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
    ) -> list[dict[str, Any]]:
        try:
            response = (
                self.client
                .table(self.TABLE_CONSTRAINTS)
                .select("*")
                .order(
                    "id",
                    desc=True,
                )
                .limit(self._limit(limit))
                .execute()
            )

            rows = self._safe_list(response)

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
