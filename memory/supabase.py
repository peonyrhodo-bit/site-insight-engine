"""
Supabase Memory Backend

This module implements the MemoryBackend contract using Supabase.

Important architecture rule:

    Director
        ↓
    Memory
        ↓
    SupabaseMemoryBackend
        ↓
    Supabase

Director must never know:
- Supabase client details;
- table names;
- SQL;
- storage-specific field names.

This module is the storage adapter.

The initial implementation deliberately uses the existing
tables already present in site-insight-engine:

    director_runs
    decisions
    chat_messages
    director_actions
    director_results
    system_events

The existing database schema is therefore preserved.

No database migration is performed by this file.
"""

from __future__ import annotations

import os
from typing import Any

from supabase import Client, create_client


class SupabaseMemoryBackend:
    """
    Supabase implementation of MemoryBackend.

    The class contains all Supabase-specific knowledge required
    by the Director memory layer.
    """

    # -----------------------------------------------------------------------
    # EXISTING TABLES
    # -----------------------------------------------------------------------

    TABLE_RUNS = "director_runs"
    TABLE_DECISIONS = "decisions"
    TABLE_CHAT = "chat_messages"
    TABLE_ACTIONS = "director_actions"
    TABLE_RESULTS = "director_results"
    TABLE_EVENTS = "system_events"

    # -----------------------------------------------------------------------
    # INITIALIZATION
    # -----------------------------------------------------------------------

    def __init__(
        self,
        client: Client | None = None,
    ) -> None:
        """
        Create the backend.

        If a Supabase client is supplied, it is used directly.

        Otherwise the backend tries to create a client from:

            SUPABASE_URL
            SUPABASE_KEY
        """

        if client is not None:
            self.client = client
            return

        supabase_url = os.getenv(
            "SUPABASE_URL"
        )

        supabase_key = os.getenv(
            "SUPABASE_KEY"
        )

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

    # -----------------------------------------------------------------------
    # INTERNAL HELPERS
    # -----------------------------------------------------------------------

    @staticmethod
    def _safe_dict(
        value: Any,
    ) -> dict[str, Any]:
        """
        Ensure metadata/data values are dictionaries.
        """

        if isinstance(value, dict):
            return value

        return {}

    @staticmethod
    def _safe_list(
        response: Any,
    ) -> list[dict[str, Any]]:
        """
        Extract rows from a Supabase response safely.
        """

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

    @staticmethod
    def _first_id(
        response: Any,
    ) -> int | None:
        """
        Extract an inserted row ID from a Supabase response.
        """

        rows = SupabaseMemoryBackend._safe_list(
            response
        )

        if not rows:
            return None

        value = rows[0].get("id")

        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # -----------------------------------------------------------------------
    # GENERAL CONTEXT
    # -----------------------------------------------------------------------

    def get_context(
        self,
        *,
        limit_runs: int = 10,
        limit_decisions: int = 20,
        limit_events: int = 30,
        limit_chat: int = 20,
        limit_actions: int = 20,
        limit_results: int = 20,
    ) -> dict[str, Any]:
        """
        Load recent Director memory.

        This intentionally mirrors the context that the existing
        server.py already collects, but moves all storage knowledge
        into this backend.
        """

        return {
            "runs": self.get_recent_runs(
                limit=limit_runs
            ),
            "decisions": self.get_recent_decisions(
                limit=limit_decisions
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

    # -----------------------------------------------------------------------
    # DIRECTOR RUNS
    # -----------------------------------------------------------------------

    def save_run(
        self,
        *,
        language: str | None = None,
        region_code: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Save a Director run.

        Existing schema:

            created_at
            language
            region_code
            data_json
        """

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

        return self._first_id(
            response
        )

    def get_recent_runs(
        self,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Load recent Director runs.
        """

        response = (
            self.client
            .table(self.TABLE_RUNS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(limit)
            .execute()
        )

        return self._safe_list(
            response
        )

    # -----------------------------------------------------------------------
    # DECISIONS
    # -----------------------------------------------------------------------

    def save_decision(
        self,
        *,
        decision: str,
        data: dict[str, Any] | None = None,
        run_id: int | None = None,
    ) -> int | None:
        """
        Save a Director decision.

        Existing schema:

            created_at
            decision
            run_id
            data_json
        """

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

        return self._first_id(
            response
        )

    def get_recent_decisions(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Load recent Director decisions.
        """

        response = (
            self.client
            .table(self.TABLE_DECISIONS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(limit)
            .execute()
        )

        return self._safe_list(
            response
        )

    # -----------------------------------------------------------------------
    # CHAT
    # -----------------------------------------------------------------------

    def save_chat_message(
        self,
        *,
        role: str,
        message: str,
        run_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Save a Director chat message.

        Existing schema:

            created_at
            role
            message
            run_id
            data_json
        """

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

        return self._first_id(
            response
        )

    def get_recent_chat_messages(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Load recent Director chat messages.
        """

        response = (
            self.client
            .table(self.TABLE_CHAT)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(limit)
            .execute()
        )

        return self._safe_list(
            response
        )

    # -----------------------------------------------------------------------
    # ACTIONS
    # -----------------------------------------------------------------------

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
        """
        Save a Director action.

        The table is already used by the existing system.
        """

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

        return self._first_id(
            response
        )

    def get_recent_actions(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Load recent Director actions.
        """

        response = (
            self.client
            .table(self.TABLE_ACTIONS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(limit)
            .execute()
        )

        return self._safe_list(
            response
        )

    # -----------------------------------------------------------------------
    # RESULTS
    # -----------------------------------------------------------------------

    def save_result(
        self,
        *,
        result_type: str,
        summary: str = "",
        action_id: int | None = None,
        run_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Save a result produced by a Director action.
        """

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

        return self._first_id(
            response
        )

    def get_recent_results(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Load recent Director results.
        """

        response = (
            self.client
            .table(self.TABLE_RESULTS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(limit)
            .execute()
        )

        return self._safe_list(
            response
        )

    # -----------------------------------------------------------------------
    # EVENTS
    # -----------------------------------------------------------------------

    def save_event(
        self,
        *,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Save a system event.

        Existing system_events table is used here.
        """

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

        return self._first_id(
            response
        )

    def get_recent_events(
        self,
        *,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Load recent system events.
        """

        response = (
            self.client
            .table(self.TABLE_EVENTS)
            .select("*")
            .order(
                "created_at",
                desc=True,
            )
            .limit(limit)
            .execute()
        )

        return self._safe_list(
            response
        )
    # -----------------------------------------------------------------------
    # RECOMMENDATIONS
    # -----------------------------------------------------------------------

    TABLE_RECOMMENDATIONS = "recommendations"
    TABLE_RECOMMENDATION_FEEDBACK = "recommendation_feedback"
    TABLE_CONSTRAINTS = "constraints"

    
    def save_recommendation(
        self,
        *,
        recommendation: dict[str, Any],
    ) -> int | None:
        """
        Save a Director recommendation.
        """

        recommendation = self._safe_dict(
            recommendation
        )

        payload = {
            "run_id": recommendation.get("run_id"),
            "decision_id": recommendation.get("decision_id"),
            "title": recommendation.get("title"),
            "description": recommendation.get("description"),
            "recommendation_type": recommendation.get(
                "recommendation_type"
            ),
            "topic": recommendation.get("topic"),
            "region": recommendation.get("region"),
            "language": recommendation.get("language"),
            "rationale": recommendation.get("rationale"),
            "suggested_action": recommendation.get(
                "suggested_action"
            ),
            "confidence": recommendation.get("confidence"),
            "priority": recommendation.get("priority"),
            "status": recommendation.get(
                "status",
                "new",
            ),
            "data_json": self._safe_dict(
                recommendation.get("metadata")
            ),
        }

        response = (
            self.client
            .table(
                self.TABLE_RECOMMENDATIONS
            )
            .insert(payload)
            .execute()
        )

        rows = response.data or []

        if rows:
            return rows[0].get("id")

        return None
    # -----------------------------------------------------------------------
    # RECOMMENDATION FEEDBACK
    # -----------------------------------------------------------------------

    def save_recommendation_feedback(
        self,
        *,
        feedback: dict[str, Any],
    ) -> int | None:
        """
        Save feedback for a Director recommendation.
        """

        feedback = self._safe_dict(
            feedback
        )

        payload = {
            "recommendation_id": feedback.get(
                "recommendation_id"
            ),
            "feedback_type": feedback.get(
                "feedback_type"
            ),
            "comment": feedback.get(
                "comment"
            ),
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
            "data_json": self._safe_dict(
                feedback.get("metadata")
            ),
        }

        response = (
            self.client
            .table(
                self.TABLE_RECOMMENDATION_FEEDBACK
            )
            .insert(payload)
            .execute()
        )

        return self._first_id(
            response
        )

    # -----------------------------------------------------------------------
    # APPLY RECOMMENDATION FEEDBACK
    # -----------------------------------------------------------------------

    def apply_recommendation_feedback(
        self,
        *,
        feedback: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Save feedback and apply its immediate status effect
        to the recommendation.
        """

        feedback = self._safe_dict(
            feedback
        )

        feedback_id = (
            self.save_recommendation_feedback(
                feedback=feedback
            )
        )

        recommendation_id = feedback.get(
            "recommendation_id"
        )

        feedback_type = feedback.get(
            "feedback_type"
        )

        status_map = {
            "accept": "accepted",
            "reject": "rejected",
            "defer": "deferred",
        }

        new_status = status_map.get(
            feedback_type
        )

        updated = False

        if (
            recommendation_id is not None
            and new_status is not None
        ):
            response = (
                self.client
                .table(
                    self.TABLE_RECOMMENDATIONS
                )
                .update(
                    {
                        "status": new_status,
                    }
                )
                .eq(
                    "id",
                    recommendation_id,
                )
                .execute()
            )

            updated = bool(
                self._safe_list(response)
            )

        return {
            "feedback_id": feedback_id,
            "recommendation_id": recommendation_id,
            "feedback_type": feedback_type,
            "status": new_status,
            "updated": updated,
        }
