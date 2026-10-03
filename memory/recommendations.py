"""
Director Recommendations — Memory 2.0

A recommendation is a strategic proposal made by Director.

It is not the same as:
- a decision;
- user feedback;
- an action;
- a result.

The lifecycle can be:

    NEW
      ↓
    ACTIVE
      ↓
    ACCEPTED / REJECTED / DEFERRED
      ↓
    COMPLETED
      ↓
    RESULT
      ↓
    LESSON
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


RECOMMENDATION_STATUSES = {
    "new",
    "active",
    "accepted",
    "rejected",
    "deferred",
    "completed",
    "archived",
}

FEEDBACK_TYPES = {
    "accept",
    "reject",
    "defer",
    "investigate",
    "change_priority",
    "comment",
}


@dataclass
class RecommendationFeedback:
    recommendation_id: int

    feedback_type: str
    message: str | None = None

    reason: str | None = None
    priority: int | None = None

    scope: str | None = None

    creates_constraint: bool = False

    run_id: int | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    id: int | None = None

    def __post_init__(self) -> None:
        try:
            self.recommendation_id = int(
                self.recommendation_id
            )
        except (TypeError, ValueError):
            raise ValueError(
                "recommendation_id must be an integer"
            )

        self.feedback_type = self._validate_type(
            self.feedback_type
        )

        if not isinstance(self.metadata, dict):
            self.metadata = {}

    @staticmethod
    def _validate_type(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError(
                "feedback_type must be a string"
            )

        value = value.strip().lower()

        if value not in FEEDBACK_TYPES:
            raise ValueError(
                f"Unknown feedback type: {value}"
            )

        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "recommendation_id": self.recommendation_id,
            "feedback_type": self.feedback_type,
            "message": self.message,
            "reason": self.reason,
            "priority": self.priority,
            "scope": self.scope,
            "creates_constraint": self.creates_constraint,
            "run_id": self.run_id,
            "metadata": dict(self.metadata),
        }


@dataclass
class Recommendation:
    title: str
    description: str

    recommendation_type: str = "research_direction"
    status: str = "new"

    topic: str | None = None
    region: str | None = None
    language: str | None = None

    rationale: str | None = None
    suggested_action: str | None = None

    confidence: float | None = None
    priority: int | None = None

    run_id: int | None = None
    decision_id: int | None = None

    source_data: dict[str, Any] = field(
        default_factory=dict
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    user_response: str | None = None
    result_summary: str | None = None
    lesson: str | None = None

    shown_at: str | None = None
    accepted_at: str | None = None
    rejected_at: str | None = None
    completed_at: str | None = None

    id: int | None = None

    def __post_init__(self) -> None:
        self.title = self._clean_required(
            self.title,
            "title",
        )

        self.description = self._clean_required(
            self.description,
            "description",
        )

        self.recommendation_type = self._clean_required(
            self.recommendation_type,
            "recommendation_type",
        )

        self.status = self._validate_status(
            self.status
        )

        self.confidence = self._validate_confidence(
            self.confidence
        )

        self.priority = self._validate_priority(
            self.priority
        )

        if not isinstance(
            self.source_data,
            dict,
        ):
            self.source_data = {}

        if not isinstance(
            self.metadata,
            dict,
        ):
            self.metadata = {}

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
    def _validate_status(
        status: str,
    ) -> str:
        if not isinstance(status, str):
            raise TypeError(
                "status must be a string"
            )

        status = status.strip().lower()

        if status not in RECOMMENDATION_STATUSES:
            raise ValueError(
                f"Unknown recommendation status: {status}"
            )

        return status

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
        self.status = self._validate_status(status)

    def activate(self) -> None:
        self.status = "active"

    def mark_shown(
        self,
        *,
        timestamp: str | None = None,
    ) -> None:
        self.status = "active"

        if timestamp:
            self.shown_at = timestamp

    def accept(
        self,
        *,
        message: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.status = "accepted"
        self.user_response = message

        if timestamp:
            self.accepted_at = timestamp

    def reject(
        self,
        *,
        reason: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.status = "rejected"
        self.user_response = reason

        if timestamp:
            self.rejected_at = timestamp

    def defer(
        self,
        *,
        reason: str | None = None,
    ) -> None:
        self.status = "deferred"
        self.user_response = reason

    def complete(
        self,
        *,
        result_summary: str | None = None,
        lesson: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.status = "completed"

        self.result_summary = result_summary
        self.lesson = lesson

        if timestamp:
            self.completed_at = timestamp

    def learn(
        self,
        *,
        result_summary: str,
        lesson: str,
    ) -> None:
        self.result_summary = result_summary
        self.lesson = lesson
        self.status = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "recommendation_type": self.recommendation_type,
            "status": self.status,
            "topic": self.topic,
            "region": self.region,
            "language": self.language,
            "rationale": self.rationale,
            "suggested_action": self.suggested_action,
            "confidence": self.confidence,
            "priority": self.priority,
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "source_data": dict(self.source_data),
            "metadata": dict(self.metadata),
            "user_response": self.user_response,
            "result_summary": self.result_summary,
            "lesson": self.lesson,
            "shown_at": self.shown_at,
            "accepted_at": self.accepted_at,
            "rejected_at": self.rejected_at,
            "completed_at": self.completed_at,
        }


class RecommendationManager:
    """Factory and lifecycle manager."""

    def create(
        self,
        *,
        title: str,
        description: str,
        recommendation_type: str = "research_direction",
        status: str = "new",
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        rationale: str | None = None,
        suggested_action: str | None = None,
        confidence: float | None = None,
        priority: int | None = None,
        run_id: int | None = None,
        decision_id: int | None = None,
        source_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Recommendation:
        return Recommendation(
            title=title,
            description=description,
            recommendation_type=recommendation_type,
            status=status,
            topic=topic,
            region=region,
            language=language,
            rationale=rationale,
            suggested_action=suggested_action,
            confidence=confidence,
            priority=priority,
            run_id=run_id,
            decision_id=decision_id,
            source_data=source_data or {},
            metadata=metadata or {},
        )

    def create_feedback(
        self,
        *,
        recommendation_id: int,
        feedback_type: str,
        message: str | None = None,
        reason: str | None = None,
        priority: int | None = None,
        scope: str | None = None,
        creates_constraint: bool = False,
        run_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RecommendationFeedback:
        return RecommendationFeedback(
            recommendation_id=recommendation_id,
            feedback_type=feedback_type,
            message=message,
            reason=reason,
            priority=priority,
            scope=scope,
            creates_constraint=creates_constraint,
            run_id=run_id,
            metadata=metadata or {},
        )


def recommendation_from_dict(
    data: dict[str, Any],
) -> Recommendation:
    return Recommendation(
        title=data.get("title", ""),
        description=data.get("description", ""),
        recommendation_type=data.get(
            "recommendation_type",
            "research_direction",
        ),
        status=data.get("status", "new"),
        topic=data.get("topic"),
        region=data.get("region"),
        language=data.get("language"),
        rationale=data.get("rationale"),
        suggested_action=data.get(
            "suggested_action"
        ),
        confidence=data.get("confidence"),
        priority=data.get("priority"),
        run_id=data.get("run_id"),
        decision_id=data.get("decision_id"),
        source_data=data.get(
            "source_data",
            {},
        ),
        metadata=data.get(
            "metadata",
            {},
        ),
        user_response=data.get(
            "user_response"
        ),
        result_summary=data.get(
            "result_summary"
        ),
        lesson=data.get("lesson"),
        shown_at=data.get("shown_at"),
        accepted_at=data.get("accepted_at"),
        rejected_at=data.get("rejected_at"),
        completed_at=data.get("completed_at"),
        id=data.get("id"),
    )
