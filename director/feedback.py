from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DirectorFeedback:
    """
    Structured feedback from a human about a recommendation.
    """

    recommendation_id: int
    feedback_type: str
    comment: str | None = None
    scope: str | None = None
    topic: str | None = None
    region: str | None = None
    language: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "recommendation_id": (
                self.recommendation_id
            ),
            "feedback_type": self.feedback_type,
            "comment": self.comment,
            "scope": self.scope,
            "topic": self.topic,
            "region": self.region,
            "language": self.language,
            "metadata": self.metadata,
        }


class DirectorFeedbackManager:
    """
    Converts human feedback into structured
    data and sends it to Memory.

    This layer does not decide whether the feedback
    is strategically correct. It records the human
    decision and lets Memory apply the corresponding
    state change.
    """

    VALID_TYPES = {
        "accept",
        "reject",
        "defer",
        "investigate",
        "change_priority",
        "comment",
    }

    def __init__(
        self,
        memory: Any | None = None,
    ):
        self.memory = memory

    def create(
        self,
        recommendation_id: int,
        feedback_type: str,
        comment: str | None = None,
        scope: str | None = None,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DirectorFeedback:

        if feedback_type not in self.VALID_TYPES:
            raise ValueError(
                "Unsupported feedback type: "
                f"{feedback_type}"
            )

        feedback = DirectorFeedback(
            recommendation_id=int(
                recommendation_id
            ),
            feedback_type=feedback_type,
            comment=comment,
            scope=scope,
            topic=topic,
            region=region,
            language=language,
            metadata=metadata or {},
        )

        if self.memory is not None:
            saved = (
                self.memory.save_recommendation_feedback(
                    feedback.to_dict()
                )
            )

            if isinstance(saved, dict):
                feedback.id = saved.get(
                    "id"
                )

        return feedback

    def apply(
        self,
        recommendation_id: int,
        feedback_type: str,
        comment: str | None = None,
        scope: str | None = None,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DirectorFeedback:

        feedback = self.create(
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

        if self.memory is not None:
            self.memory.apply_recommendation_feedback(
                feedback.to_dict()
            )

        return feedback
