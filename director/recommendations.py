from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DirectorRecommendation:
    """
    Recommendation produced by the Director.

    This layer is responsible for the recommendation itself.
    Storage and persistence are handled by Memory.
    """

    title: str
    description: str
    recommendation_type: str = "research"
    topic: str | None = None
    region: str | None = None
    language: str | None = None
    rationale: str | None = None
    suggested_action: str | None = None
    confidence: float | None = None
    priority: int = 0
    run_id: int | None = None
    decision_id: int | None = None
    source_data: dict[str, Any] = field(
        default_factory=dict
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "recommendation_type": (
                self.recommendation_type
            ),
            "topic": self.topic,
            "region": self.region,
            "language": self.language,
            "rationale": self.rationale,
            "suggested_action": (
                self.suggested_action
            ),
            "confidence": self.confidence,
            "priority": self.priority,
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "source_data": self.source_data,
            "metadata": self.metadata,
        }


class DirectorRecommendationManager:
    """
    Creates and prepares recommendations
    for the Director.

    The manager does not own persistence.
    Memory remains the source of stored recommendations.
    """

    def __init__(
        self,
        memory: Any | None = None,
    ):
        self.memory = memory

    def create(
        self,
        title: str,
        description: str,
        recommendation_type: str = "research",
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        rationale: str | None = None,
        suggested_action: str | None = None,
        confidence: float | None = None,
        priority: int = 0,
        run_id: int | None = None,
        decision_id: int | None = None,
        source_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DirectorRecommendation:

        recommendation = DirectorRecommendation(
            title=title,
            description=description,
            recommendation_type=(
                recommendation_type
            ),
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

        if self.memory is not None:
            saved = self.memory.save_recommendation(
                recommendation.to_dict()
            )

            if isinstance(saved, dict):
                recommendation.id = saved.get(
                    "id"
                )

        return recommendation

    def create_from_analysis(
        self,
        analysis: dict[str, Any],
        run_id: int | None = None,
        decision_id: int | None = None,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
    ) -> list[DirectorRecommendation]:

        recommendations: list[
            DirectorRecommendation
        ] = []

        experiments = analysis.get(
            "experiments",
            [],
        )

        if not isinstance(
            experiments,
            list,
        ):
            experiments = []

        hypothesis = analysis.get(
            "hypothesis"
        )

        reasoning = analysis.get(
            "reasoning"
        )

        confidence = analysis.get(
            "confidence"
        )

        for experiment in experiments:
            if not isinstance(
                experiment,
                str,
            ):
                continue

            title = (
                experiment[:120]
                if experiment
                else "Director experiment"
            )

            recommendation = self.create(
                title=title,
                description=experiment,
                recommendation_type="pilot",
                topic=topic,
                region=region,
                language=language,
                rationale=(
                    reasoning
                    or hypothesis
                ),
                suggested_action=experiment,
                confidence=confidence,
                run_id=run_id,
                decision_id=decision_id,
                source_data=analysis,
            )

            recommendations.append(
                recommendation
            )

        return recommendations

    def rank(
        self,
        recommendations: list[
            DirectorRecommendation
        ],
    ) -> list[DirectorRecommendation]:

        return sorted(
            recommendations,
            key=lambda item: (
                item.priority,
                item.confidence or 0.0,
            ),
            reverse=True,
        )
