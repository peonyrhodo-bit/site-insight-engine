"""
Director decision layer.

This module converts available evidence, opportunities, constraints,
resources and previous experience into a structured Director decision.

Important architectural rule:
- analytics calculates;
- research gathers;
- memory stores experience;
- decision.py decides;
- recommendations.py turns a decision into a human-facing recommendation.

This is intentionally a small first-stage decision layer.
It is not the final autonomous Director.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DirectorDecision:
    """
    Structured decision made by the Director.

    The object is deliberately independent from Supabase, FastAPI
    and UI code.
    """

    decision_type: str
    opportunity: str | None = None
    applicable: bool = True
    confidence: float | None = None
    next_action: str | None = None
    rationale: str | None = None

    evidence: list[Any] = field(default_factory=list)
    constraints: list[Any] = field(default_factory=list)
    resources: dict[str, Any] = field(default_factory=dict)
    previous_decisions: list[Any] = field(default_factory=list)

    run_id: int | None = None
    id: int | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "decision_type": self.decision_type,
            "opportunity": self.opportunity,
            "applicable": self.applicable,
            "confidence": self.confidence,
            "next_action": self.next_action,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "constraints": self.constraints,
            "resources": self.resources,
            "previous_decisions": self.previous_decisions,
            "run_id": self.run_id,
            "metadata": self.metadata,
        }


class DirectorDecisionManager:
    """
    Creates structured decisions for the Director.

    Persistence remains the responsibility of Memory.

    The manager does not perform research and does not calculate
    analytics. It only structures the decision from already available
    information.
    """

    def __init__(self, memory: Any | None = None) -> None:
        self.memory = memory

    def decide(
        self,
        *,
        decision_type: str,
        opportunity: str | None = None,
        applicable: bool = True,
        confidence: float | None = None,
        next_action: str | None = None,
        rationale: str | None = None,
        evidence: list[Any] | None = None,
        constraints: list[Any] | None = None,
        resources: dict[str, Any] | None = None,
        previous_decisions: list[Any] | None = None,
        run_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> DirectorDecision:
        if not isinstance(decision_type, str):
            raise TypeError("decision_type must be a string")

        decision_type = decision_type.strip()

        if not decision_type:
            raise ValueError("decision_type cannot be empty")

        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = None

        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))

        decision = DirectorDecision(
            decision_type=decision_type,
            opportunity=opportunity,
            applicable=bool(applicable),
            confidence=confidence,
            next_action=next_action,
            rationale=rationale,
            evidence=list(evidence or []),
            constraints=list(constraints or []),
            resources=dict(resources or {}),
            previous_decisions=list(previous_decisions or []),
            run_id=run_id,
            metadata=dict(metadata or {}),
        )

        if persist and self.memory is not None:
            saved = self.memory.save_decision(
                decision=decision_type,
                data=decision.to_dict(),
                run_id=run_id,
            )

            if isinstance(saved, int):
                decision.id = saved

        return decision

    def from_context(
        self,
        context: dict[str, Any] | None,
        *,
        decision_type: str,
        opportunity: str | None = None,
        next_action: str | None = None,
        rationale: str | None = None,
        confidence: float | None = None,
        run_id: int | None = None,
        persist: bool = True,
    ) -> DirectorDecision:
        """
        Build a decision using an already prepared Director context.

        This method intentionally does not invent a strategy.
        The caller supplies the actual decision and rationale.
        """

        context = context if isinstance(context, dict) else {}

        evidence = context.get("evidence", [])
        constraints = context.get("constraints", [])
        resources = context.get("resources", {})
        previous_decisions = context.get(
            "previous_decisions",
            context.get("decisions", []),
        )

        applicable = context.get("applicable", True)

        return self.decide(
            decision_type=decision_type,
            opportunity=opportunity,
            applicable=bool(applicable),
            confidence=confidence,
            next_action=next_action,
            rationale=rationale,
            evidence=(
                evidence
                if isinstance(evidence, list)
                else [evidence]
            ),
            constraints=(
                constraints
                if isinstance(constraints, list)
                else [constraints]
            ),
            resources=(
                resources
                if isinstance(resources, dict)
                else {}
            ),
            previous_decisions=(
                previous_decisions
                if isinstance(previous_decisions, list)
                else [previous_decisions]
            ),
            run_id=run_id,
            metadata={
                "source": "director_context",
            },
            persist=persist,
        )
