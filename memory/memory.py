"""
Director Memory Interface — Memory 2.0

Memory is the stable Director-facing interface to long-term experience.

Architecture:

    Director
        ↓
    Memory
        ↓
    MemoryBackend
        ↓
    Supabase / another storage

Director must not know anything about:
- Supabase
- SQL
- table names
- storage-specific fields

Memory 2.0 adds an important semantic layer:
- recent context
- decisions
- recommendations
- feedback
- constraints
- actions
- results
- events
- chat
- runs

The goal is not merely to store records.

The goal is to let Director answer:

    What happened?
    What did I decide?
    Why did I decide it?
    What did I recommend?
    What did the user say?
    What was actually done?
    What happened afterwards?
    What did I learn?
    What constraints should influence my next decision?
"""

from __future__ import annotations

from typing import Any, Protocol

from memory.constraints import ConstraintManager
from memory.recommendations import RecommendationManager


class MemoryBackend(Protocol):
    """Storage contract used by Memory."""

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
        ...

    def save_run(
        self,
        *,
        language: str | None = None,
        region_code: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        ...

    def get_recent_runs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        ...

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

    def save_recommendation(
        self,
        *,
        recommendation: dict[str, Any],
    ) -> int | None:
        ...

    def get_recent_recommendations(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        ...

    def apply_recommendation_feedback(
        self,
        *,
        feedback: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    def save_constraint(
        self,
        *,
        constraint: dict[str, Any],
    ) -> int | None:
        ...

    def get_recent_constraints(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        ...


class Memory:
    """
    Stable long-term memory interface for Director.

    This class is deliberately storage-agnostic.

    It also provides a semantic context builder so Director does not
    need to know how individual memory tables are organized.
    """

    DEFAULT_LIMIT_RUNS = 10
    DEFAULT_LIMIT_DECISIONS = 20
    DEFAULT_LIMIT_EVENTS = 30
    DEFAULT_LIMIT_CHAT = 20
    DEFAULT_LIMIT_ACTIONS = 20
    DEFAULT_LIMIT_RESULTS = 20
    DEFAULT_LIMIT_RECOMMENDATIONS = 20
    DEFAULT_LIMIT_CONSTRAINTS = 20

    MAX_LIMIT = 100

    def __init__(self, backend: MemoryBackend) -> None:
        if backend is None:
            raise ValueError("Memory backend is required")

        self.backend = backend

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    @classmethod
    def _limit(cls, value: int, default: int) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default

        return max(1, min(value, cls.MAX_LIMIT))

    @staticmethod
    def _dict(value: dict[str, Any] | None) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _text(value: Any, default: str = "") -> str:
        if value is None:
            return default

        value = str(value).strip()
        return value or default

    # ------------------------------------------------------------------
    # MEMORY CONTEXT
    # ------------------------------------------------------------------

    def get_context(
        self,
        *,
        project_id: str | None = None,
        limit_runs: int = DEFAULT_LIMIT_RUNS,
        limit_decisions: int = DEFAULT_LIMIT_DECISIONS,
        limit_events: int = DEFAULT_LIMIT_EVENTS,
        limit_chat: int = DEFAULT_LIMIT_CHAT,
        limit_actions: int = DEFAULT_LIMIT_ACTIONS,
        limit_results: int = DEFAULT_LIMIT_RESULTS,
        limit_recommendations: int = DEFAULT_LIMIT_RECOMMENDATIONS,
        limit_constraints: int = DEFAULT_LIMIT_CONSTRAINTS,
    ) -> dict[str, Any]:
        """
        Return the complete recent memory context.

        This is the primary method intended for Director wake-up.

        The context contains both raw history and a compact semantic
        summary of what Director should remember.
        """

        context = self.backend.get_context(
            project_id=project_id,
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
            limit_recommendations=self._limit(
                limit_recommendations,
                self.DEFAULT_LIMIT_RECOMMENDATIONS,
            ),
            limit_constraints=self._limit(
                limit_constraints,
                self.DEFAULT_LIMIT_CONSTRAINTS,
            ),
        )

        return self._build_memory_context(context)

    @staticmethod
    def _build_memory_context(
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Add semantic indexes without changing the stored records.
        """

        decisions = context.get("decisions") or []
        recommendations = context.get("recommendations") or []
        constraints = context.get("constraints") or []
        actions = context.get("actions") or []
        results = context.get("results") or []

        active_constraints = []

        for item in constraints:
            if not isinstance(item, dict):
                continue

            status = str(item.get("status", "")).lower()

            if status in {"active", "proposed"}:
                active_constraints.append(item)

        pending_recommendations = []

        for item in recommendations:
            if not isinstance(item, dict):
                continue

            status = str(item.get("status", "")).lower()

            if status in {
                "draft",
                "pending",
                "discussed",
                "deferred",
                "accepted",
            }:
                pending_recommendations.append(item)

        unfinished_actions = []

        for item in actions:
            if not isinstance(item, dict):
                continue

            status = str(item.get("status", "")).lower()

            if status in {
                "pending",
                "running",
                "planned",
            }:
                unfinished_actions.append(item)

        unresolved_decisions = []

        for item in decisions:
            if not isinstance(item, dict):
                continue

            status = str(item.get("status", "")).lower()

            if status in {
                "proposed",
                "active",
                "deferred",
            }:
                unresolved_decisions.append(item)

        context["memory_state"] = {
            "active_constraints": active_constraints,
            "pending_recommendations": pending_recommendations,
            "unfinished_actions": unfinished_actions,
            "unresolved_decisions": unresolved_decisions,
            "recent_results": results,
            "recent_events": context.get("events") or [],
            "recent_chat": context.get("chat") or [],
            "recent_runs": context.get("runs") or [],
        }

        return context

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
        return self.backend.save_run(
            language=language,
            region_code=region_code,
            data=self._dict(data),
        )

    def get_recent_runs(
        self,
        *,
        limit: int = DEFAULT_LIMIT_RUNS,
    ) -> list[dict[str, Any]]:
        return self.backend.get_recent_runs(
            limit=self._limit(limit, self.DEFAULT_LIMIT_RUNS)
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
        if not isinstance(decision, str):
            raise TypeError("decision must be a string")

        decision = decision.strip()

        if not decision:
            raise ValueError("decision cannot be empty")

        return self.backend.save_decision(
            decision=decision,
            data=self._dict(data),
            run_id=run_id,
        )

    def save_decision_model(self, decision: Any) -> int | None:
        """
        Persist a rich Decision model without making Memory depend on
        the concrete class implementation.
        """

        if hasattr(decision, "to_dict"):
            payload = decision.to_dict()
        elif isinstance(decision, dict):
            payload = dict(decision)
        else:
            raise TypeError("decision must be a Decision-like object or dict")

        text = self._text(
            payload.get("decision"),
            payload.get("title", ""),
        )

        data = dict(payload)
        data.pop("decision", None)

        return self.save_decision(
            decision=text,
            data=data,
            run_id=payload.get("run_id"),
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
        role = self._text(role)

        if not role:
            raise ValueError("role cannot be empty")

        message = self._text(message)

        if not message:
            raise ValueError("message cannot be empty")

        return self.backend.save_chat_message(
            role=role,
            message=message,
            run_id=run_id,
            data=self._dict(data),
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
        action_type = self._text(action_type)

        if not action_type:
            raise ValueError("action_type cannot be empty")

        return self.backend.save_action(
            action_type=action_type,
            description=self._text(description),
            run_id=run_id,
            decision_id=decision_id,
            status=self._text(status, "pending"),
            data=self._dict(data),
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
        result_type = self._text(result_type)

        if not result_type:
            raise ValueError("result_type cannot be empty")

        return self.backend.save_result(
            result_type=result_type,
            summary=self._text(summary),
            action_id=action_id,
            run_id=run_id,
            data=self._dict(data),
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

    # ------------------------------------------------------------------
    # EVENTS
    # ------------------------------------------------------------------

    def save_event(
        self,
        *,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        event_type = self._text(event_type)

        if not event_type:
            raise ValueError("event_type cannot be empty")

        return self.backend.save_event(
            event_type=event_type,
            data=self._dict(data),
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

    # ------------------------------------------------------------------
    # RECOMMENDATIONS
    # ------------------------------------------------------------------

    def save_recommendation(
        self,
        recommendation: dict[str, Any],
    ) -> int | None:
        if not isinstance(recommendation, dict):
            raise TypeError("recommendation must be a dict")

        manager = RecommendationManager()

        model = manager.create(
            title=recommendation.get("title", ""),
            description=recommendation.get("description", ""),
            recommendation_type=recommendation.get(
                "recommendation_type",
                "research_direction",
            ),
            topic=recommendation.get("topic"),
            region=recommendation.get("region"),
            language=recommendation.get("language"),
            rationale=recommendation.get("rationale"),
            suggested_action=recommendation.get("suggested_action"),
            confidence=recommendation.get("confidence"),
            priority=recommendation.get("priority"),
            run_id=recommendation.get("run_id"),
            decision_id=recommendation.get("decision_id"),
            source_data=recommendation.get("source_data"),
            metadata=recommendation.get("metadata"),
        )

        if recommendation.get("status") is not None:
            model.set_status(recommendation["status"])

        return self.backend.save_recommendation(
            recommendation=model.to_dict()
        )

    def get_recent_recommendations(
        self,
        *,
        limit: int = DEFAULT_LIMIT_RECOMMENDATIONS,
    ) -> list[dict[str, Any]]:
        return self.backend.get_recent_recommendations(
            limit=self._limit(
                limit,
                self.DEFAULT_LIMIT_RECOMMENDATIONS,
            )
        )

    def apply_recommendation_feedback(
        self,
        feedback: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(feedback, dict):
            raise TypeError("feedback must be a dict")

        return self.backend.apply_recommendation_feedback(
            feedback=feedback
        )

    # ------------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------------

    def save_constraint(
        self,
        constraint: dict[str, Any],
    ) -> int | None:
        if not isinstance(constraint, dict):
            raise TypeError("constraint must be a dict")

        manager = ConstraintManager()

        model = manager.create(
            title=constraint.get("title", ""),
            description=constraint.get("description", ""),
            constraint_type=constraint.get(
                "constraint_type",
                "avoid",
            ),
            scope=constraint.get(
                "scope",
                "recommendation",
            ),
            status=constraint.get(
                "status",
                "proposed",
            ),
            topic=constraint.get("topic"),
            region=constraint.get("region"),
            language=constraint.get("language"),
            execution_condition=constraint.get(
                "execution_condition"
            ),
            reason=constraint.get("reason"),
            confidence=constraint.get(
                "confidence",
                0.5,
            ),
            priority=constraint.get(
                "priority",
                0,
            ),
            source_recommendation_id=constraint.get(
                "source_recommendation_id"
            ),
            source_feedback_id=constraint.get(
                "source_feedback_id"
            ),
            source_run_id=constraint.get(
                "source_run_id"
            ),
            metadata=constraint.get("metadata"),
        )

        return self.backend.save_constraint(
            constraint=model.to_dict()
        )

    def get_recent_constraints(
        self,
        *,
        limit: int = DEFAULT_LIMIT_CONSTRAINTS,
    ) -> list[dict[str, Any]]:
        return self.backend.get_recent_constraints(
            limit=self._limit(
                limit,
                self.DEFAULT_LIMIT_CONSTRAINTS,
            )
        )

    # ------------------------------------------------------------------
    # RELEVANT MEMORY
    # ------------------------------------------------------------------

    def get_relevant_memory(
        self,
        *,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Lightweight relevance filter over recent memory.

        This is intentionally not semantic search yet.

        It gives Director a stable interface today and leaves vector/
        embedding retrieval as a future optimization.
        """

        limit = self._limit(limit, 20)

        context = self.get_context(
            limit_decisions=limit,
            limit_recommendations=limit,
            limit_constraints=limit,
            limit_actions=limit,
            limit_results=limit,
        )

        def matches(item: dict[str, Any]) -> bool:
            if not isinstance(item, dict):
                return False

            data = item.get("data_json")

            if not isinstance(data, dict):
                data = item

            if topic:
                item_topic = data.get("topic") or item.get("topic")
                if item_topic and str(item_topic).lower() != topic.lower():
                    return False

            if region:
                item_region = (
                    data.get("region")
                    or item.get("region")
                    or item.get("region_code")
                )
                if item_region and str(item_region).lower() != region.lower():
                    return False

            if language:
                item_language = (
                    data.get("language")
                    or item.get("language")
                )
                if item_language and str(item_language).lower() != language.lower():
                    return False

            return True

        result: dict[str, Any] = {}

        for key in (
            "decisions",
            "recommendations",
            "constraints",
            "actions",
            "results",
        ):
            result[key] = [
                item
                for item in context.get(key, [])
                if matches(item)
            ][:limit]

        return result

    # ------------------------------------------------------------------
    # SNAPSHOT
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """
        Compact diagnostic representation of current memory.
        """

        context = self.get_context(
            limit_runs=5,
            limit_decisions=10,
            limit_events=10,
            limit_chat=10,
            limit_actions=10,
            limit_results=10,
            limit_recommendations=10,
            limit_constraints=10,
        )

        state = context.get("memory_state", {})

        return {
            "counts": {
                key: len(context.get(key, []))
                for key in (
                    "runs",
                    "decisions",
                    "recommendations",
                    "constraints",
                    "actions",
                    "results",
                    "events",
                    "chat",
                )
            },
            "state": state,
        }
