"""
Director hypotheses.

A hypothesis is a falsifiable strategic explanation derived from
interpreted Analytics signals. It is not yet a recommendation or a decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class DirectorHypothesis:
    hypothesis_id: str
    statement: str
    opportunity_id: str | None
    title: str
    rationale: str
    supporting_signals: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    test: str = ""
    expected_outcome: str = ""
    falsification_criteria: list[str] = field(default_factory=list)
    confidence: float = 0.0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_hypothesis(
    *,
    title: str,
    statement: str,
    rationale: str,
    opportunity_id: str | None = None,
    supporting_signals: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    risks: list[str] | None = None,
    missing_data: list[str] | None = None,
    test: str = "",
    expected_outcome: str = "",
    falsification_criteria: list[str] | None = None,
    confidence: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> DirectorHypothesis:
    return DirectorHypothesis(
        hypothesis_id=f"hyp_{uuid4().hex[:12]}",
        statement=str(statement or "").strip(),
        opportunity_id=opportunity_id,
        title=str(title or "").strip(),
        rationale=str(rationale or "").strip(),
        supporting_signals=[
            str(x) for x in (supporting_signals or []) if str(x).strip()
        ],
        evidence=list(evidence or []),
        risks=[str(x) for x in (risks or []) if str(x).strip()],
        missing_data=[
            str(x) for x in (missing_data or []) if str(x).strip()
        ],
        test=str(test or "").strip(),
        expected_outcome=str(expected_outcome or "").strip(),
        falsification_criteria=[
            str(x)
            for x in (falsification_criteria or [])
            if str(x).strip()
        ],
        confidence=confidence,
        metadata=dict(metadata or {}),
    )
