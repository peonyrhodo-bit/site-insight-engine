"""
Human feedback for the Director.

Feedback is treated as system state and future knowledge.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class FeedbackType(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    MODIFY = "modify"
    CLARIFY = "clarify"
    PREFER = "prefer"
    AVOID = "avoid"


class FeedbackScope(str, Enum):
    RECOMMENDATION = "recommendation"
    TOPIC = "topic"
    FORMAT = "format"
    AUDIENCE = "audience"
    LANGUAGE = "language"
    CHANNEL = "channel"
    STRATEGY = "strategy"
    RESOURCE = "resource"
    CONSTRAINT = "constraint"
    GENERAL = "general"


@dataclass
class DirectorFeedback:
    feedback_id: str
    feedback_type: FeedbackType
    scope: FeedbackScope
    message: str
    recommendation_id: str | None = None
    decision_id: str | None = None
    target: str | None = None
    reason: str | None = None
    constraint: str | None = None
    preference: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_feedback(
    *,
    feedback_type: FeedbackType | str,
    scope: FeedbackScope | str,
    message: str,
    recommendation_id: str | None = None,
    decision_id: str | None = None,
    target: str | None = None,
    reason: str | None = None,
    constraint: str | None = None,
    preference: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DirectorFeedback:
    if not isinstance(feedback_type, FeedbackType):
        feedback_type = FeedbackType(str(feedback_type))

    if not isinstance(scope, FeedbackScope):
        scope = FeedbackScope(str(scope))

    return DirectorFeedback(
        feedback_id=f"fb_{uuid4().hex[:12]}",
        feedback_type=feedback_type,
        scope=scope,
        message=str(message or "").strip(),
        recommendation_id=recommendation_id,
        decision_id=decision_id,
        target=target,
        reason=reason,
        constraint=constraint,
        preference=preference,
        metadata=dict(metadata or {}),
    )


def accept(
    *,
    message: str = "",
    recommendation_id: str | None = None,
    decision_id: str | None = None,
    scope: FeedbackScope = FeedbackScope.RECOMMENDATION,
    metadata: dict[str, Any] | None = None,
) -> DirectorFeedback:
    return create_feedback(
        feedback_type=FeedbackType.ACCEPT,
        scope=scope,
        message=message or "Рекомендация принята.",
        recommendation_id=recommendation_id,
        decision_id=decision_id,
        metadata=metadata,
    )


def reject(
    *,
    reason: str,
    recommendation_id: str | None = None,
    decision_id: str | None = None,
    scope: FeedbackScope = FeedbackScope.RECOMMENDATION,
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DirectorFeedback:
    return create_feedback(
        feedback_type=FeedbackType.REJECT,
        scope=scope,
        message=reason,
        recommendation_id=recommendation_id,
        decision_id=decision_id,
        target=target,
        reason=reason,
        metadata=metadata,
    )


def modify(
    *,
    message: str,
    recommendation_id: str | None = None,
    decision_id: str | None = None,
    scope: FeedbackScope = FeedbackScope.RECOMMENDATION,
    metadata: dict[str, Any] | None = None,
) -> DirectorFeedback:
    return create_feedback(
        feedback_type=FeedbackType.MODIFY,
        scope=scope,
        message=message,
        recommendation_id=recommendation_id,
        decision_id=decision_id,
        metadata=metadata,
    )


def preference(
    *,
    message: str,
    scope: FeedbackScope = FeedbackScope.GENERAL,
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DirectorFeedback:
    return create_feedback(
        feedback_type=FeedbackType.PREFER,
        scope=scope,
        message=message,
        target=target,
        preference=message,
        metadata=metadata,
    )


def constraint(
    *,
    message: str,
    scope: FeedbackScope = FeedbackScope.CONSTRAINT,
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DirectorFeedback:
    return create_feedback(
        feedback_type=FeedbackType.AVOID,
        scope=scope,
        message=message,
        target=target,
        constraint=message,
        metadata=metadata,
    )


def feedback_to_memory_record(
    feedback: DirectorFeedback,
) -> dict[str, Any]:
    """
    Stable representation for the future Memory layer.
    """
    return {
        "type": "director_feedback",
        "feedback_id": feedback.feedback_id,
        "feedback_type": feedback.feedback_type.value,
        "scope": feedback.scope.value,
        "message": feedback.message,
        "recommendation_id": feedback.recommendation_id,
        "decision_id": feedback.decision_id,
        "target": feedback.target,
        "reason": feedback.reason,
        "constraint": feedback.constraint,
        "preference": feedback.preference,
        "created_at": feedback.created_at,
        "metadata": feedback.metadata,
    }
