```python
"""
Director Decisions

This module defines the memory model for decisions made by the Director.

Important:
- Director does not know about Supabase.
- Director does not know about SQL.
- Director does not know table names.
- Storage is handled by Memory / MemoryBackend.

A decision is different from a recommendation.

Decision:
    What the Director decided to do or not to do.

Recommendation:
    What the Director proposes to the user.

Example:

    Decision:
        "Research historical video opportunities in China."

    Recommendation:
        "Run a pilot with 3 Shorts and 2 long-form videos."

The decision may exist even when there is no user-facing
recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# DECISION TYPES
# ---------------------------------------------------------------------------

DECISION_TYPES = {
    "research",
    "research_direction",
    "pilot",
    "prioritize",
    "deprioritize",
    "continue",
    "stop",
    "defer",
    "revisit",
    "investigate",
    "constraint",
    "system",
}


# ---------------------------------------------------------------------------
# DECISION STATUSES
# ---------------------------------------------------------------------------

DECISION_STATUSES = {
    "proposed",
    "active",
    "completed",
    "cancelled",
    "deferred",
}


# ---------------------------------------------------------------------------
# DECISION
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    """
    A decision made by the Director.

    The object stores the decision itself together with enough context
    to understand why it was made and what it was connected to.
    """

    decision: str

    decision_type: str = "research"

    status: str = "proposed"

    reason: str | None = None

    topic: str | None = None
    region: str | None = None
    language: str | None = None

    priority: int | None = None
    confidence: float | None = None

    run_id: int | None = None

    recommendation_id: int | None = None

    parent_decision_id: int | None = None

    data: dict[str, Any] = field(
        default_factory=dict
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    id: int | None = None

    def __post_init__(self) -> None:
        self.decision = self._clean_required(
            self.decision,
            "decision",
        )

        self.decision_type = (
            self._validate_choice(
                self.decision_type,
                DECISION_TYPES,
                "decision_type",
            )
        )

        self.status = self._validate_choice(
            self.status,
            DECISION_STATUSES,
            "status",
        )

        self.confidence = (
            self._validate_confidence(
                self.confidence
            )
        )

        self.priority = (
            self._validate_priority(
                self.priority
            )
        )

        if not isinstance(
            self.data,
            dict,
        ):
            self.data = {}

        if not isinstance(
            self.metadata,
            dict,
        ):
            self.metadata = {}

    # -----------------------------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------------------------

    @staticmethod
    def _clean_required(
        value: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                f"{field_name} must be a string"
            )

        value = value.strip()

        if not value:
            raise ValueError(
                f"{field_name} cannot be empty"
            )

        return value

    @staticmethod
    def _validate_choice(
        value: str,
        allowed: set[str],
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                f"{field_name} must be a string"
            )

        value = value.strip().lower()

        if value not in allowed:
            raise ValueError(
                f"Unknown {field_name}: {value}"
            )

        return value

    @staticmethod
    def _validate_confidence(
        confidence: float | None,
    ) -> float | None:
        if confidence is None:
            return None

        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "confidence must be a number"
            ) from exc

        if confidence < 0:
            confidence = 0.0

        if confidence > 1:
            confidence = 1.0

        return confidence

    @staticmethod
    def _validate_priority(
        priority: int | None,
    ) -> int | None:
        if priority is None:
            return None

        try:
            return int(priority)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "priority must be an integer"
            ) from exc

    # -----------------------------------------------------------------------
    # STATE
    # -----------------------------------------------------------------------

    def activate(self) -> None:
        """
        Mark the decision as active.
        """

        self.status = "active"

    def complete(self) -> None:
        """
        Mark the decision as completed.
        """

        self.status = "completed"

    def cancel(self) -> None:
        """
        Cancel the decision.
        """

        self.status = "cancelled"

    def defer(self) -> None:
        """
        Defer the decision.
        """

        self.status = "deferred"

    # -----------------------------------------------------------------------
    # SERIALIZATION
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the decision into a storage-independent dictionary.
        """

        return {
            "id": self.id,
            "decision": self.decision,
            "decision_type": self.decision_type,
            "status": self.status,
            "reason": self.reason,
            "topic": self.topic,
            "region": self.region,
            "language": self.language,
            "priority": self.priority,
            "confidence": self.confidence,
            "run_id": self.run_id,
            "recommendation_id": (
                self.recommendation_id
            ),
            "parent_decision_id": (
                self.parent_decision_id
            ),
            "data": self.data,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# DECISION MANAGER
# ---------------------------------------------------------------------------

class DecisionManager:
    """
    Director-facing manager for decisions.

    This class creates and evaluates decision objects.

    It does not persist anything.

    Persistence will later be provided by the memory layer.
    """

    def create(
        self,
        *,
        decision: str,
        decision_type: str = "research",
        status: str = "proposed",
        reason: str | None = None,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        priority: int | None = None,
        confidence: float | None = None,
        run_id: int | None = None,
        recommendation_id: int | None = None,
        parent_decision_id: int | None = None,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Decision:
        """
        Create a validated decision.
        """

        return Decision(
            decision=decision,
            decision_type=decision_type,
            status=status,
            reason=reason,
            topic=topic,
            region=region,
            language=language,
            priority=priority,
            confidence=confidence,
            run_id=run_id,
            recommendation_id=(
                recommendation_id
            ),
            parent_decision_id=(
                parent_decision_id
            ),
            data=(
                data
                if isinstance(data, dict)
                else {}
            ),
            metadata=(
                metadata
                if isinstance(metadata, dict)
                else {}
            ),
        )

    @staticmethod
    def active(
        decisions: list[Decision],
    ) -> list[Decision]:
        """
        Return only currently active decisions.
        """

        return [
            item
            for item in decisions
            if item.status == "active"
        ]

    @staticmethod
    def relevant(
        decisions: list[Decision],
        *,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
    ) -> list[Decision]:
        """
        Return decisions relevant to the supplied research context.

        Matching is deliberately conservative.

        A decision with a specific topic is not considered relevant
        to an unrelated topic.

        A decision with no topic, region, or language is treated as
        general and remains relevant.
        """

        result: list[Decision] = []

        normalized_topic = (
            topic.strip().casefold()
            if isinstance(topic, str)
            else None
        )

        normalized_region = (
            region.strip().casefold()
            if isinstance(region, str)
            else None
        )

        normalized_language = (
            language.strip().casefold()
            if isinstance(language, str)
            else None
        )

        for item in decisions:
            if item.status not in {
                "proposed",
                "active",
            }:
                continue

            if (
                item.topic is not None
                and normalized_topic is not None
                and item.topic.strip().casefold()
                != normalized_topic
            ):
                continue

            if (
                item.region is not None
                and normalized_region is not None
                and item.region.strip().casefold()
                != normalized_region
            ):
                continue

            if (
                item.language is not None
                and normalized_language is not None
                and item.language.strip().casefold()
                != normalized_language
            ):
                continue

            result.append(item)

        return result

    @staticmethod
    def rank(
        decisions: list[Decision],
    ) -> list[Decision]:
        """
        Rank decisions by status, priority, and confidence.
        """

        return sorted(
            decisions,
            key=lambda item: (
                item.status != "active",
                -(
                    item.priority
                    if item.priority is not None
                    else 0
                ),
                -(
                    item.confidence
                    if item.confidence is not None
                    else 0
                ),
            ),
        )
```
