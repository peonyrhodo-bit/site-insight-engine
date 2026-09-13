from __future__ import annotations

from typing import Any

from director.recommendations import (
    DirectorRecommendation,
    DirectorRecommendationManager,
)
from director.feedback import (
    DirectorFeedbackManager,
)


class RecommendationsWebService:
    """
    Web-facing service for Director recommendations.

    This layer connects the web/API layer with Director's
    recommendation and feedback logic.

    It does not contain strategic decisions.
    """

    def __init__(
        self,
        recommendation_manager: DirectorRecommendationManager,
        feedback_manager: DirectorFeedbackManager,
    ):
        self.recommendation_manager = (
            recommendation_manager
        )
        self.feedback_manager = feedback_manager

    def create_recommendation(
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
    ) -> dict[str, Any]:

        recommendation = (
            self.recommendation_manager.create(
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
                source_data=source_data,
                metadata=metadata,
            )
        )

        return recommendation.to_dict()

    def create_feedback(
        self,
        recommendation_id: int,
        feedback_type: str,
        comment: str | None = None,
        scope: str | None = None,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        feedback = self.feedback_manager.apply(
            recommendation_id=(
                recommendation_id
            ),
            feedback_type=feedback_type,
            comment=comment,
            scope=scope,
            topic=topic,
            region=region,
            language=language,
            metadata=metadata,
        )

        return feedback.to_dict()

    def recommendations_from_analysis(
        self,
        analysis: dict[str, Any],
        run_id: int | None = None,
        decision_id: int | None = None,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:

        recommendations = (
            self.recommendation_manager
            .create_from_analysis(
                analysis=analysis,
                run_id=run_id,
                decision_id=decision_id,
                topic=topic,
                region=region,
                language=language,
            )
        )

        ranked = (
            self.recommendation_manager.rank(
                recommendations
            )
        )

        return [
            recommendation.to_dict()
            for recommendation in ranked
        ]
