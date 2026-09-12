"""
Director Memory Interface

This module defines the stable interface that Director uses to work
with memory.

Important:
- Director does not know about Supabase.
- Director does not know about SQL.
- Director does not know table names.
- Storage implementation is provided by a backend
  such as memory.supabase.

The purpose of this module is to keep Director logic independent
from the actual storage system.
"""

from __future__ import annotations

from typing import Any, Protocol


class MemoryBackend(Protocol):
    """
    Storage contract.

    A backend can be implemented using Supabase, SQLite,
    or another storage system.

    Director never talks to the backend directly.
    """

    # ---------------------------------------------------------
    # General context
    # ---------------------------------------------------------

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
        ...

    # ---------------------------------------------------------
    # Director runs
    # ---------------------------------------------------------

    def save_run(
        self,
        *,
        language: str | None = None,
        region_code: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        ...

    def get_recent_runs(
        self,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        ...

    # ---------------------------------------------------------
    # Decisions
    # ---------------------------------------------------------

    def save_decision(
        self,
        *,
        decision: str,
        data: dict[str, Any] | None = None,
        run_id: int | None = None,
    ) -> int | None:
        ...

    def get_recent_decisions(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        ...

    # ---------------------------------------------------------
    # Chat
    # ---------------------------------------------------------

    def save_chat_message(
        self,
        *,
        role: str,
        message: str,
        run_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        ...

    def get_recent_chat_messages(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        ...

    # ---------------------------------------------------------
    # Actions
    # ---------------------------------------------------------

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
        ...

    def get_recent_actions(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        ...

    # ---------------------------------------------------------
    # Results
    # ---------------------------------------------------------

    def save_result(
        self,
        *,
        result_type: str,
        summary: str = "",
        action_id: int | None = None,
        run_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        ...

    def get_recent_results(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        ...

    # ---------------------------------------------------------
    # Events
    # ---------------------------------------------------------

    def save_event(
        self,
        *,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        ...

    def get_recent_events(
        self,
        *,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        ...


class Memory:
    """
    Stable Director-facing memory interface.

    The Director uses this class instead of talking directly
    to Supabase or SQLite.

    Example:

        memory = Memory(backend)

        context = memory.get_context()

        memory.save_decision(
            decision="research_direction",
            data={
                "topic": "gardening",
            },
        )

    The actual storage implementation is injected through
    the backend argument.
    """

    DEFAULT_LIMIT_RUNS = 10
    DEFAULT_LIMIT_DECISIONS = 20
    DEFAULT_LIMIT_EVENTS = 30
    DEFAULT_LIMIT_CHAT = 20
    DEFAULT_LIMIT_ACTIONS = 20
    DEFAULT_LIMIT_RESULTS = 20

    MAX_LIMIT = 100

    def __init__(
        self,
        backend: MemoryBackend,
    ) -> None:
        if backend is None:
            raise ValueError(
                "Memory backend is required"
            )

        self.backend = backend

    # =========================================================
    # INTERNAL HELPERS
    # =========================================================

    @classmethod
    def _limit(
        cls,
        value: int,
        default: int,
    ) -> int:
        """
        Normalizes memory query limits.

        This prevents accidental requests for enormous
        amounts of historical data.
        """

        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default

        return max(
            1,
            min(value, cls.MAX_LIMIT),
        )

    @staticmethod
    def _dict_or_empty(
        value: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(value, dict):
            return value

        return {}

    # =========================================================
    # GENERAL CONTEXT
    # =========================================================

    def get_context(
        self,
        *,
        limit_runs: int = DEFAULT_LIMIT_RUNS,
        limit_decisions: int = DEFAULT_LIMIT_DECISIONS,
        limit_events: int = DEFAULT_LIMIT_EVENTS,
        limit_chat: int = DEFAULT_LIMIT_CHAT,
        limit_actions: int = DEFAULT_LIMIT_ACTIONS,
        limit_results: int = DEFAULT_LIMIT_RESULTS,
    ) -> dict[str, Any]:
        """
        Returns the current memory context available to Director.

        This is the main method Director will use when it needs
        to understand what happened previously.
        """

        return self.backend.get_context(
            limit_runs=self._limit(
                limit_runs,
                self.DEFAULT_LIMIT_RUNS,
            ),
            limit_decisions=self._limit(
                limit_decisions,
                self.DEFAULT_LIMIT_DECISIONS,
            ),
            limit_events=self._limit(
                limit_events,
                self.DEFAULT_LIMIT_EVENTS,
            ),
            limit_chat=self._limit(
                limit_chat,
                self.DEFAULT_LIMIT_CHAT,
            ),
            limit_actions=self._limit(
                limit_actions,
                self.DEFAULT_LIMIT_ACTIONS,
            ),
            limit_results=self._limit(
                limit_results,
                self.DEFAULT_LIMIT_RESULTS,
            ),
        )

    # =========================================================
    # DIRECTOR RUNS
    # =========================================================

    def save_run(
        self,
        *,
        language: str | None = None,
        region_code: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        return self.backend.save_run(
            language=language,
            region_code=region_code,
            data=self._dict_or_empty(data),
        )

    def get_recent_runs(
        self,
        *,
        limit: int = DEFAULT_LIMIT_RUNS,
    ) -> list[dict[str, Any]]:
        return self.backend.get_recent_runs(
            limit=self._limit(
                limit,
                self.DEFAULT_LIMIT_RUNS,
            )
        )

    # =========================================================
    # DECISIONS
    # =========================================================

    def save_decision(
        self,
        *,
        decision: str,
        data: dict[str, Any] | None = None,
        run_id: int | None = None,
    ) -> int | None:
        if not isinstance(decision, str):
            raise TypeError(
                "decision must be a string"
            )

        decision = decision.strip()

        if not decision:
            raise ValueError(
                "decision cannot be empty"
            )

        return self.backend.save_decision(
            decision=decision,
            data=self._dict_or_empty(data),
            run_id=run_id,
        )

    def get_recent_decisions(
        self,
        *,
        limit: int = DEFAULT_LIMIT_DECISIONS,
    ) -> list[dict[str, Any]]:
        return self.backend.get_recent_decisions(
            limit=self._limit(
                limit,
                self.DEFAULT_LIMIT_DECISIONS,
            )
        )

    # =========================================================
    # CHAT
    # =========================================================

    def save_chat_message(
        self,
        *,
        role: str,
        message: str,
        run_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        if not isinstance(role, str):
            raise TypeError(
                "role must be a string"
            )

        if not isinstance(message, str):
            raise TypeError(
                "message must be a string"
            )

        role = role.strip()
        message = message.strip()

        if not role:
            raise ValueError(
                "role cannot be empty"
            )

        if not message:
            raise ValueError(
                "message cannot be empty"
            )

        return self.backend.save_chat_message(
            role=role,
            message=message,
            run_id=run_id,
            data=self._dict_or_empty(data),
        )

    def get_recent_chat_messages(
        self,
        *,
        limit: int = DEFAULT_LIMIT_CHAT,
    ) -> list[dict[str, Any]]:
        return self.backend.get_recent_chat_messages(
            limit=self._limit(
                limit,
                self.DEFAULT_LIMIT_CHAT,
            )
        )

    # =========================================================
    # ACTIONS
    # =========================================================

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
        if not isinstance(action_type, str):
            raise TypeError(
                "action_type must be a string"
            )

        action_type = action_type.strip()

        if not action_type:
            raise ValueError(
                "action_type cannot be empty"
            )

        return self.backend.save_action(
            action_type=action_type,
            description=description or "",
            run_id=run_id,
            decision_id=decision_id,
            status=status or "pending",
            data=self._dict_or_empty(data),
        )

    def get_recent_actions(
        self,
        *,
        limit: int = DEFAULT_LIMIT_ACTIONS,
    ) -> list[dict[str, Any]]:
        return self.backend.get_recent_actions(
            limit=self._limit(
                limit,
                self.DEFAULT_LIMIT_ACTIONS,
            )
        )

    # =========================================================
    # RESULTS
    # =========================================================

    def save_result(
        self,
        *,
        result_type: str,
        summary: str = "",
        action_id: int | None = None,
        run_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        if not isinstance(result_type, str):
            raise TypeError(
                "result_type must be a string"
            )

        result_type = result_type.strip()

        if not result_type:
            raise ValueError(
                "result_type cannot be empty"
            )

        return self.backend.save_result(
            result_type=result_type,
            summary=summary or "",
            action_id=action_id,
            run_id=run_id,
            data=self._dict_or_empty(data),
        )

    def get_recent_results(
        self,
        *,
        limit: int = DEFAULT_LIMIT_RESULTS,
    ) -> list[dict[str, Any]]:
        return self.backend.get_recent_results(
            limit=self._limit(
                limit,
                self.DEFAULT_LIMIT_RESULTS,
            )
        )

    # =========================================================
    # EVENTS
    # =========================================================

    def save_event(
        self,
        *,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        if not isinstance(event_type, str):
            raise TypeError(
                "event_type must be a string"
            )

        event_type = event_type.strip()

        if not event_type:
            raise ValueError(
                "event_type cannot be empty"
            )

        return self.backend.save_event(
            event_type=event_type,
            data=self._dict_or_empty(data),
        )

    def get_recent_events(
        self,
        *,
        limit: int = DEFAULT_LIMIT_EVENTS,
    ) -> list[dict[str, Any]]:
        return self.backend.get_recent_events(
            limit=self._limit(
                limit,
                self.DEFAULT_LIMIT_EVENTS,
            )
        )
