"""
Web recommendation actions.

This module translates user actions from the web/API layer into
Director feedback and recommendation state changes.

It does not make strategic decisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from director.feedback import (
    FeedbackScope,
    DirectorFeedback,
    accept as create_accept_feedback,
    reject as create_reject_feedback,
    modify as create_modify_feedback,
)
from director.recommendations import (
    DirectorRecommendation,
    RecommendationStatus,
    accept_recommendation,
    complete_recommendation,
    discuss_recommendation,
    reject_recommendation,
)


class RecommendationAction(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    DISCUSS = "discuss"
    ANSWER = "answer"
    COMPLETE = "complete"
    CANCEL = "cancel"


@dataclass
class RecommendationActionRequest:
    action: RecommendationAction
    recommendation_id: str
    message: str | None = None
    reason: str | None = None
    scope: FeedbackScope = FeedbackScope.RECOMMENDATION
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecommendationActionResult:
    success: bool
    recommendation_id: str
    action: RecommendationAction
    status: RecommendationStatus | None
    message: str
    feedback: DirectorFeedback | None = None
    recommendation: DirectorRecommendation | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecommendationStore:
    """
    Small in-memory store used as a default implementation.

    Later it can be replaced by Memory/Supabase without changing
    the web contract.
    """

    def __init__(self) -> None:
        self._items: dict[str, DirectorRecommendation] = {}

    def save(
        self,
        recommendation: DirectorRecommendation,
    ) -> DirectorRecommendation:
        self._items[recommendation.recommendation_id] = recommendation
        return recommendation

    def get(
        self,
        recommendation_id: str,
    ) -> DirectorRecommendation | None:
        return self._items.get(recommendation_id)

    def all(self) -> list[DirectorRecommendation]:
        return list(self._items.values())

    def delete(self, recommendation_id: str) -> None:
        self._items.pop(recommendation_id, None)


class RecommendationController:
    """
    Web-facing controller.

    It manages recommendation lifecycle but never decides whether
    a recommendation is strategically correct.
    """

    def __init__(
        self,
        *,
        store: RecommendationStore | None = None,
        feedback_handler: Any = None,
    ) -> None:
        self.store = store or RecommendationStore()
        self.feedback_handler = feedback_handler

    def register(
        self,
        recommendation: DirectorRecommendation,
    ) -> DirectorRecommendation:
        return self.store.save(recommendation)

    def get(
        self,
        recommendation_id: str,
    ) -> DirectorRecommendation | None:
        return self.store.get(recommendation_id)

    def list(
        self,
        *,
        status: RecommendationStatus | None = None,
    ) -> list[DirectorRecommendation]:
        items = self.store.all()

        if status is None:
            return items

        return [
            item
            for item in items
            if item.status == status
        ]

    def apply(
        self,
        request: RecommendationActionRequest,
    ) -> RecommendationActionResult:
        recommendation = self.get(
            request.recommendation_id
        )

        if recommendation is None:
            return RecommendationActionResult(
                success=False,
                recommendation_id=request.recommendation_id,
                action=request.action,
                status=None,
                message="Рекомендация не найдена.",
            )

        try:
            feedback = None

            if request.action == RecommendationAction.ACCEPT:
                recommendation = accept_recommendation(
                    recommendation,
                    feedback=request.message,
                )

                feedback = create_accept_feedback(
                    message=request.message or "Рекомендация принята.",
                    recommendation_id=(
                        recommendation.recommendation_id
                    ),
                    scope=request.scope,
                    metadata=request.metadata,
                )

                message = (
                    "Рекомендация принята. "
                    "Валерий учтёт это как часть текущего состояния."
                )

            elif request.action == RecommendationAction.REJECT:
                reason = (
                    request.reason
                    or request.message
                    or "Причина отказа не указана."
                )

                recommendation = reject_recommendation(
                    recommendation,
                    reason=reason,
                )

                feedback = create_reject_feedback(
                    reason=reason,
                    recommendation_id=(
                        recommendation.recommendation_id
                    ),
                    scope=request.scope,
                    metadata=request.metadata,
                )

                message = (
                    "Рекомендация отклонена. "
                    "Причина передана Валерию."
                )

            elif request.action == RecommendationAction.DISCUSS:
                recommendation = discuss_recommendation(
                    recommendation,
                    message=request.message,
                )

                feedback = create_modify_feedback(
                    message=request.message or "",
                    recommendation_id=(
                        recommendation.recommendation_id
                    ),
                    scope=request.scope,
                    metadata=request.metadata,
                )

                message = (
                    "Хорошо. Рекомендация переведена в обсуждение."
                )

            elif request.action == RecommendationAction.ANSWER:
                if not request.message:
                    return RecommendationActionResult(
                        success=False,
                        recommendation_id=(
                            recommendation.recommendation_id
                        ),
                        action=request.action,
                        status=recommendation.status,
                        message=(
                            "Нужен ответ пользователя."
                        ),
                        recommendation=recommendation,
                    )

                recommendation.metadata.setdefault(
                    "answers",
                    [],
                ).append(
                    {
                        "message": request.message,
                        "created_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    }
                )

                recommendation.status = (
                    RecommendationStatus.DISCUSSED
                )

                feedback = create_modify_feedback(
                    message=request.message,
                    recommendation_id=(
                        recommendation.recommendation_id
                    ),
                    scope=request.scope,
                    metadata=request.metadata,
                )

                message = (
                    "Ответ принят и сохранён для Валерия."
                )

            elif request.action == RecommendationAction.COMPLETE:
                recommendation = complete_recommendation(
                    recommendation,
                    result=request.metadata.get(
                        "result"
                    ),
                )

                message = (
                    "Результат рекомендации отмечен как завершённый."
                )

            elif request.action == RecommendationAction.CANCEL:
                recommendation.status = (
                    RecommendationStatus.CANCELLED
                )

                if request.reason:
                    recommendation.metadata[
                        "cancellation_reason"
                    ] = request.reason

                message = "Рекомендация отменена."

            else:
                return RecommendationActionResult(
                    success=False,
                    recommendation_id=(
                        recommendation.recommendation_id
                    ),
                    action=request.action,
                    status=recommendation.status,
                    message="Неизвестное действие.",
                    recommendation=recommendation,
                )

            self.store.save(recommendation)

            if feedback is not None:
                self._send_feedback(feedback)

            return RecommendationActionResult(
                success=True,
                recommendation_id=(
                    recommendation.recommendation_id
                ),
                action=request.action,
                status=recommendation.status,
                message=message,
                feedback=feedback,
                recommendation=recommendation,
            )

        except Exception as exc:
            return RecommendationActionResult(
                success=False,
                recommendation_id=(
                    recommendation.recommendation_id
                ),
                action=request.action,
                status=recommendation.status,
                message=(
                    f"Не удалось обработать действие: {exc}"
                ),
                recommendation=recommendation,
            )

    def _send_feedback(
        self,
        feedback: DirectorFeedback,
    ) -> None:
        if self.feedback_handler is None:
            return

        self.feedback_handler(feedback)


def create_controller(
    *,
    feedback_handler: Any = None,
) -> RecommendationController:
    return RecommendationController(
        feedback_handler=feedback_handler,
    )
