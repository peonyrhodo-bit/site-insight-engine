"""
Director Decisions — Memory 2.0

A decision is an internal strategic choice made by Director.

Decision != recommendation.

A decision answers:
    "What did I decide?"

A recommendation answers:
    "What am I proposing to the user?"

Memory 2.0 also allows a decision to become an experience:

    decision
        ↓
    expected outcome
        ↓
    actual outcome
        ↓
    lesson
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

DECISION_STATUSES = {
    "proposed",
    "active",
    "completed",
    "cancelled",
    "deferred",
}


@dataclass
class Decision:
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

    evidence: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)

    expected_outcome: str | None = None
    actual_outcome: str | None = None
    lesson: str | None = None

    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    id: int | None = None

    def __post_init__(self) -> None:
        self.decision = self._clean_required(
            self.decision,
            "decision",
        )

        self.decision_type = self._validate_choice(
            self.decision_type,
            DECISION_TYPES,
            "decision_type",
        )

        self.status = self._validate_choice(
            self.status,
            DECISION_STATUSES,
            "status",
        )

        self.confidence = self._validate_confidence(
            self.confidence
        )

        self.priority = self._validate_priority(
            self.priority
        )

        if not isinstance(self.evidence, list):
            self.evidence = []

        if not isinstance(self.alternatives, list):
            self.alternatives = []

        if not isinstance(self.data, dict):
            self.data = {}

        if not isinstance(self.metadata, dict):
            self.metadata = {}

    @staticmethod
    def _clean_required(
        value: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

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
        value: float | None,
    ) -> float | None:
        if value is None:
            return None

        try:
            value = float(value)
        except (TypeError, ValueError):
            return None

        return max(0.0, min(1.0, value))

    @staticmethod
    def _validate_priority(
        value: int | None,
    ) -> int | None:
        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def set_status(self, status: str) -> None:
        self.status = self._validate_choice(
            status,
            DECISION_STATUSES,
            "status",
        )

    def activate(self) -> None:
        self.status = "active"

    def complete(
        self,
        *,
        actual_outcome: str | None = None,
        lesson: str | None = None,
    ) -> None:
        self.status = "completed"

        if actual_outcome is not None:
            self.actual_outcome = actual_outcome.strip()

        if lesson is not None:
            self.lesson = lesson.strip()

    def defer(self) -> None:
        self.status = "deferred"

    def cancel(self) -> None:
        self.status = "cancelled"

    def add_evidence(
        self,
        evidence: dict[str, Any],
    ) -> None:
        if isinstance(evidence, dict):
            self.evidence.append(dict(evidence))

    def add_alternative(
        self,
        alternative: dict[str, Any],
    ) -> None:
        if isinstance(alternative, dict):
            self.alternatives.append(dict(alternative))

    def learn(
        self,
        *,
        actual_outcome: str,
        lesson: str,
    ) -> None:
        self.actual_outcome = (
            actual_outcome.strip()
            if actual_outcome
            else None
        )

        self.lesson = (
            lesson.strip()
            if lesson
            else None
        )

        self.status = "completed"

    def to_dict(self) -> dict[str, Any]:
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
            "recommendation_id": self.recommendation_id,
            "parent_decision_id": self.parent_decision_id,
            "evidence": list(self.evidence),
            "alternatives": list(self.alternatives),
            "expected_outcome": self.expected_outcome,
            "actual_outcome": self.actual_outcome,
            "lesson": self.lesson,
            "data": dict(self.data),
            "metadata": dict(self.metadata),
        }


class DecisionManager:
    """Factory and lifecycle helper for Decision objects."""

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
        evidence: list[dict[str, Any]] | None = None,
        alternatives: list[dict[str, Any]] | None = None,
        expected_outcome: str | None = None,
        actual_outcome: str | None = None,
        lesson: str | None = None,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Decision:
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
            recommendation_id=recommendation_id,
            parent_decision_id=parent_decision_id,
            evidence=evidence or [],
            alternatives=alternatives or [],
            expected_outcome=expected_outcome,
            actual_outcome=actual_outcome,
            lesson=lesson,
            data=data or {},
            metadata=metadata or {},
        )


def decision_from_dict(
    data: dict[str, Any],
) -> Decision:
    return Decision(
        decision=data.get("decision", ""),
        decision_type=data.get(
            "decision_type",
            "research",
        ),
        status=data.get(
            "status",
            "proposed",
        ),
        reason=data.get("reason"),
        topic=data.get("topic"),
        region=data.get("region"),
        language=data.get("language"),
        priority=data.get("priority"),
        confidence=data.get("confidence"),
        run_id=data.get("run_id"),
        recommendation_id=data.get(
            "recommendation_id"
        ),
        parent_decision_id=data.get(
            "parent_decision_id"
        ),
        evidence=data.get("evidence", []),
        alternatives=data.get(
            "alternatives",
            [],
        ),
        expected_outcome=data.get(
            "expected_outcome"
        ),
        actual_outcome=data.get(
            "actual_outcome"
        ),
        lesson=data.get("lesson"),
        data=data.get("data", {}),
        metadata=data.get("metadata", {}),
        id=data.get("id"),
    )
