"""
Director decision layer.

Decision is a structured interpretation of analytical evidence.
It does not gather data and does not itself perform actions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
from uuid import uuid4


class DecisionType(str, Enum):
    RESEARCH = "research"
    ANALYZE = "analyze"
    TEST = "test"
    CREATE = "create"
    PUBLISH = "publish"
    EVALUATE = "evaluate"
    WAIT = "wait"
    ASK_USER = "ask_user"
    SLEEP = "sleep"
    NONE = "none"


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    EXECUTED = "executed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass
class DecisionEvidence:
    source: str
    statement: str
    strength: float = 0.5
    reference_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.strength = max(0.0, min(1.0, float(self.strength)))


@dataclass
class DirectorDecision:
    decision_id: str
    decision_type: DecisionType
    status: DecisionStatus
    objective: str
    rationale: str
    confidence: float
    opportunity_score: float | None = None
    applicability_score: float | None = None
    evidence: list[DecisionEvidence] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    next_action: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

        if self.opportunity_score is not None:
            self.opportunity_score = max(
                0.0, min(1.0, float(self.opportunity_score))
            )

        if self.applicability_score is not None:
            self.applicability_score = max(
                0.0, min(1.0, float(self.applicability_score))
            )

    @property
    def is_actionable(self) -> bool:
        return self.decision_type not in {
            DecisionType.NONE,
            DecisionType.WAIT,
            DecisionType.SLEEP,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _value(source: Any, name: str, default: Any = None) -> Any:
    if source is None:
        return default

    if isinstance(source, dict):
        return source.get(name, default)

    return getattr(source, name, default)


def _dimension_score(assessment: Any, name: str) -> float | None:
    value = _value(assessment, name)

    if value is None:
        return None

    if isinstance(value, dict):
        value = value.get("score")

    if hasattr(value, "score"):
        value = value.score

    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def build_decision(
    *,
    decision_type: DecisionType | str,
    objective: str,
    rationale: str,
    confidence: float,
    opportunity: Any = None,
    evidence: Iterable[DecisionEvidence] | None = None,
    risks: Iterable[str] | None = None,
    missing_data: Iterable[str] | None = None,
    next_action: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DirectorDecision:
    if not isinstance(decision_type, DecisionType):
        decision_type = DecisionType(str(decision_type))

    return DirectorDecision(
        decision_id=f"dec_{uuid4().hex[:12]}",
        decision_type=decision_type,
        status=DecisionStatus.PROPOSED,
        objective=str(objective or "").strip(),
        rationale=str(rationale or "").strip(),
        confidence=confidence,
        opportunity_score=_dimension_score(opportunity, "overall_score"),
        applicability_score=_dimension_score(opportunity, "applicability"),
        evidence=list(evidence or []),
        risks=[str(x) for x in (risks or []) if str(x).strip()],
        missing_data=[
            str(x) for x in (missing_data or []) if str(x).strip()
        ],
        next_action=str(next_action).strip() if next_action else None,
        metadata=dict(metadata or {}),
    )


def decide_from_opportunity(
    opportunity: Any,
    *,
    objective: str = "",
    research_if_confidence_below: float = 0.55,
) -> DirectorDecision:
    """
    Translate an OpportunityAssessment into a Director-level next action.

    Important:
    This function does NOT choose a content niche by itself.
    It decides what kind of next step is justified by the evidence.
    """
    score = _dimension_score(opportunity, "overall_score") or 0.0
    confidence = _dimension_score(opportunity, "confidence") or 0.0
    applicability = _dimension_score(opportunity, "applicability") or 0.0

    risks = list(_value(opportunity, "risks", []) or [])
    missing = list(_value(opportunity, "missing_data", []) or [])

    if missing or confidence < research_if_confidence_below:
        return build_decision(
            decision_type=DecisionType.RESEARCH,
            objective=objective or "Уточнить перспективность направления.",
            rationale=(
                "Текущих данных недостаточно для уверенного решения. "
                "Сначала нужно закрыть ключевые исследовательские пробелы."
            ),
            confidence=confidence,
            opportunity=opportunity,
            risks=risks,
            missing_data=missing,
            next_action="Провести дополнительное исследование.",
        )

    if score >= 0.72 and applicability >= 0.60:
        return build_decision(
            decision_type=DecisionType.TEST,
            objective=objective or "Проверить перспективное направление.",
            rationale=(
                "Сочетание спроса, динамики, применимости и качества "
                "доказательств позволяет перейти от исследования к тесту."
            ),
            confidence=confidence,
            opportunity=opportunity,
            risks=risks,
            missing_data=missing,
            next_action="Сформировать небольшой проверочный эксперимент.",
        )

    if score >= 0.50:
        return build_decision(
            decision_type=DecisionType.ANALYZE,
            objective=objective or "Уточнить потенциально интересное направление.",
            rationale=(
                "Есть положительные сигналы, но их пока недостаточно "
                "для перехода к практическому тесту."
            ),
            confidence=confidence,
            opportunity=opportunity,
            risks=risks,
            missing_data=missing,
            next_action="Сравнить направление с альтернативами.",
        )

    return build_decision(
        decision_type=DecisionType.WAIT,
        objective=objective or "Не переходить к действию преждевременно.",
        rationale=(
            "Текущая совокупность сигналов не даёт достаточного основания "
            "для перехода к следующему этапу."
        ),
        confidence=confidence,
        opportunity=opportunity,
        risks=risks,
        missing_data=missing,
        next_action="Наблюдать за изменением данных.",
    )


def confirm_decision(decision: DirectorDecision) -> DirectorDecision:
    decision.status = DecisionStatus.CONFIRMED
    return decision


def mark_executed(decision: DirectorDecision) -> DirectorDecision:
    decision.status = DecisionStatus.EXECUTED
    return decision


def reject_decision(
    decision: DirectorDecision,
    reason: str | None = None,
) -> DirectorDecision:
    decision.status = DecisionStatus.REJECTED

    if reason:
        decision.metadata["rejection_reason"] = reason

    return decision


def decision_to_dict(decision: DirectorDecision) -> dict[str, Any]:
    return decision.to_dict()
