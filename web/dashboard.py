"""
Director dashboard state.

Transforms internal Director state into a stable UI-friendly contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from director.autonomy import DirectorCycle, DirectorPhase
from director.director import Director, DirectorContext
from director.recommendations import (
    DirectorRecommendation,
    RecommendationStatus,
)


@dataclass
class DashboardRecommendation:
    recommendation_id: str
    title: str
    summary: str
    status: str
    proposed_action: str
    confidence: float
    target: dict[str, Any] | None = None
    risks: list[str] = field(default_factory=list)
    created_at: str | None = None


@dataclass
class DashboardState:
    project_id: str | None

    director_status: str
    director_phase: str
    mode: str

    objective: str | None

    current_action: str | None
    current_research_id: str | None
    current_decision_id: str | None
    current_recommendation_id: str | None

    evidence_available: bool
    evidence_sufficient: bool

    recommendations: list[DashboardRecommendation]

    report: dict[str, Any]
    history: list[dict[str, Any]]

    waiting_for_user: bool
    sleep_reason: str | None

    updated_at: str = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DashboardBuilder:
    """
    Converts Director internals into a UI contract.
    """

    def __init__(
        self,
        director: Director,
    ) -> None:
        self.director = director

    def build(self) -> DashboardState:
        state = self.director.state
        context = self.director.context

        recommendations = self._recommendations(
            context
        )

        history = self._history(
            context
        )

        report = self._report(
            context
        )

        waiting_for_user = (
            state.status.value == "waiting"
            and state.current_recommendation_id is not None
        )

        return DashboardState(
            project_id=self.director.project_id,
            director_status=state.status.value,
            director_phase=state.phase.value,
            mode=self.director.mode.value,
            objective=context.objective,
            current_action=state.last_action,
            current_research_id=state.current_research_id,
            current_decision_id=state.current_decision_id,
            current_recommendation_id=(
                state.current_recommendation_id
            ),
            evidence_available=state.evidence_available,
            evidence_sufficient=state.evidence_sufficient,
            recommendations=recommendations,
            report=report,
            history=history,
            waiting_for_user=waiting_for_user,
            sleep_reason=state.sleep_reason,
        )

    def _recommendations(
        self,
        context: DirectorContext,
    ) -> list[DashboardRecommendation]:
        result: list[DashboardRecommendation] = []

        for item in context.recommendations:
            if isinstance(
                item,
                DirectorRecommendation,
            ):
                recommendation = item
            elif isinstance(item, dict):
                recommendation = self._recommendation_from_dict(
                    item
                )
            else:
                continue

            target = None

            if recommendation.target is not None:
                target = asdict(
                    recommendation.target
                )

            result.append(
                DashboardRecommendation(
                    recommendation_id=(
                        recommendation.recommendation_id
                    ),
                    title=recommendation.title,
                    summary=recommendation.summary,
                    status=recommendation.status.value,
                    proposed_action=(
                        recommendation.proposed_action
                    ),
                    confidence=recommendation.confidence,
                    target=target,
                    risks=list(
                        recommendation.risks
                    ),
                    created_at=recommendation.created_at,
                )
            )

        return list(
            reversed(result)
        )

    def _recommendation_from_dict(
        self,
        item: dict[str, Any],
    ) -> DirectorRecommendation:
        from director.recommendations import (
            RecommendationTarget,
        )

        target_data = item.get(
            "target"
        )

        target = None

        if isinstance(
            target_data,
            dict,
        ):
            target = RecommendationTarget(
                kind=target_data.get(
                    "kind",
                    "unknown",
                ),
                title=target_data.get(
                    "title",
                    "",
                ),
                description=target_data.get(
                    "description",
                    "",
                ),
                audience=target_data.get(
                    "audience"
                ),
                format=target_data.get(
                    "format"
                ),
                language=target_data.get(
                    "language",
                    "ru",
                ),
                metadata=target_data.get(
                    "metadata",
                    {},
                ),
            )

        status = item.get(
            "status",
            RecommendationStatus.PENDING.value,
        )

        if not isinstance(
            status,
            RecommendationStatus,
        ):
            status = RecommendationStatus(
                status
            )

        return DirectorRecommendation(
            recommendation_id=item.get(
                "recommendation_id",
                "",
            ),
            title=item.get(
                "title",
                "",
            ),
            summary=item.get(
                "summary",
                "",
            ),
            status=status,
            target=target,
            proposed_action=item.get(
                "proposed_action",
                "",
            ),
            reason=item.get(
                "reason",
                "",
            ),
            confidence=float(
                item.get(
                    "confidence",
                    0,
                )
            ),
            evidence=[],
            risks=item.get(
                "risks",
                [],
            ),
            constraints=item.get(
                "constraints",
                [],
            ),
            decision_id=item.get(
                "decision_id"
            ),
            research_id=item.get(
                "research_id"
            ),
            created_at=item.get(
                "created_at"
            )
            or datetime.now(
                timezone.utc
            ).isoformat(),
            metadata=item.get(
                "metadata",
                {},
            ),
        )

    def _history(
        self,
        context: DirectorContext,
    ) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []

        for item in context.decisions:
            if isinstance(item, dict):
                history.append(
                    {
                        "type": "decision",
                        **item,
                    }
                )

        for item in context.research_history:
            if isinstance(item, dict):
                history.append(
                    {
                        "type": "research",
                        **item,
                    }
                )

        for item in context.feedback:
            if isinstance(item, dict):
                history.append(
                    {
                        "type": "feedback",
                        **item,
                    }
                )

        return history[-100:]

    def _report(
        self,
        context: DirectorContext,
    ) -> dict[str, Any]:
        """
        Compact report for the dashboard.

        This is intentionally not a giant analytics dump.
        """
        return {
            "objective": context.objective,
            "topics_count": self._count_topics(
                context.topics
            ),
            "opportunities_count": len(
                context.opportunities
            ),
            "observations_count": len(
                context.observations
            ),
            "missing_data": list(
                context.missing_data
            ),
            "constraints": list(
                context.constraints
            ),
            "available_actions": list(
                context.available_actions
            ),
            "analytics": context.analytics,
        }

    @staticmethod
    def _count_topics(
        topics: Any,
    ) -> int:
        if isinstance(
            topics,
            dict,
        ):
            values = topics.get(
                "topics",
                topics.get(
                    "items",
                    [],
                ),
            )

            if isinstance(
                values,
                dict,
            ):
                return len(values)

            if isinstance(
                values,
                list,
            ):
                return len(values)

        if isinstance(
            topics,
            list,
        ):
            return len(topics)

        return 0


def build_dashboard(
    director: Director,
) -> DashboardState:
    return DashboardBuilder(
        director
    ).build()
