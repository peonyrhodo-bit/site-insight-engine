"""
Director recommendations.

A recommendation is a user-facing proposal created from a Director decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
from uuid import uuid4

from .decision import DirectorDecision


class RecommendationStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DISCUSSED = "discussed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class RecommendationEvidence:
    statement: str
    source: str | None = None
    reference_id: str | None = None
    strength: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.strength = max(0.0, min(1.0, float(self.strength)))


@dataclass
class RecommendationTarget:
    kind: str
    title: str
    description: str = ""
    audience: str | None = None
    format: str | None = None
    language: str = "ru"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DirectorRecommendation:
    recommendation_id: str
    title: str
    summary: str
    status: RecommendationStatus
    target: RecommendationTarget | None
    proposed_action: str
    reason: str
    confidence: float
    evidence: list[RecommendationEvidence]
    risks: list[str]
    constraints: list[str]
    decision_id: str | None = None
    research_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_recommendation(
    *,
    title: str,
    summary: str,
    proposed_action: str,
    reason: str,
    confidence: float,
    target: RecommendationTarget | None = None,
    evidence: Iterable[RecommendationEvidence] | None = None,
    risks: Iterable[str] | None = None,
    constraints: Iterable[str] | None = None,
    decision: DirectorDecision | None = None,
    research_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DirectorRecommendation:
    """
    Create a user-facing recommendation from a Director decision.
    """
    return DirectorRecommendation(
        recommendation_id=f"rec_{uuid4().hex[:12]}",
        title=str(title or "").strip(),
        summary=str(summary or "").strip(),
        status=RecommendationStatus.PENDING,
        target=target,
        proposed_action=str(proposed_action or "").strip(),
        reason=str(reason or "").strip(),
        confidence=confidence,
        evidence=list(evidence or []),
        risks=[str(x) for x in (risks or []) if str(x).strip()],
        constraints=[
            str(x) for x in (constraints or []) if str(x).strip()
        ],
        decision_id=decision.decision_id if decision else None,
        research_id=research_id,
        metadata=dict(metadata or {}),
    )


def recommendation_from_decision(
    decision: DirectorDecision,
    *,
    title: str,
    summary: str,
    target: RecommendationTarget | None = None,
    evidence: Iterable[RecommendationEvidence] | None = None,
    metadata: dict[str, Any] | None = None,
) -> DirectorRecommendation:
    action = decision.next_action or "Обсудить следующий шаг."

    return create_recommendation(
        title=title,
        summary=summary,
        proposed_action=action,
        reason=decision.rationale,
        confidence=decision.confidence,
        target=target,
        evidence=evidence,
        risks=decision.risks,
        constraints=decision.missing_data,
        decision=decision,
        metadata=metadata,
    )


def accept_recommendation(
    recommendation: DirectorRecommendation,
    *,
    feedback: str | None = None,
) -> DirectorRecommendation:
    recommendation.status = RecommendationStatus.ACCEPTED

    if feedback:
        recommendation.metadata["acceptance_feedback"] = feedback

    return recommendation


def reject_recommendation(
    recommendation: DirectorRecommendation,
    *,
    reason: str | None = None,
) -> DirectorRecommendation:
    recommendation.status = RecommendationStatus.REJECTED

    if reason:
        recommendation.metadata["rejection_reason"] = reason

    return recommendation


def discuss_recommendation(
    recommendation: DirectorRecommendation,
    *,
    message: str | None = None,
) -> DirectorRecommendation:
    recommendation.status = RecommendationStatus.DISCUSSED

    if message:
        recommendation.metadata.setdefault("discussion", []).append(message)

    return recommendation


def complete_recommendation(
    recommendation: DirectorRecommendation,
    *,
    result: Any = None,
) -> DirectorRecommendation:
    recommendation.status = RecommendationStatus.COMPLETED

    if result is not None:
        recommendation.metadata["result"] = result

    return recommendation


def recommendation_to_dict(
    recommendation: DirectorRecommendation,
) -> dict[str, Any]:
    return recommendation.to_dict()
