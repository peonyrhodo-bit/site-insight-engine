from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memory.constraints import (
    CONSTRAINT_SCOPES,
    ConstraintManager,
)


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

            self._record_constraint(
                feedback
            )

        return feedback

    def _record_constraint(
        self,
        feedback: DirectorFeedback,
    ) -> None:
        """
        Persist a constraint only when the user explicitly scoped
        the feedback.

        Important:
        - A rejection without an explicit scope is NOT turned into
          a constraint.
        - A rejected recommendation is never automatically turned
          into a global ban.
        - Saved constraints start as "proposed"; activating them
          remains the Director's decision.
        """

        if self.memory is None:
            return

        scope = feedback.scope

        if not isinstance(scope, str):
            return

        scope = scope.strip().lower()

        if scope not in CONSTRAINT_SCOPES:
            # The scope is unclear/unsupported.
            # Do not invent one.
            return

        if feedback.feedback_type == "reject":
            constraint_type = "avoid"
        elif feedback.feedback_type == "accept":
            constraint_type = "prefer"
        else:
            # Other feedback types do not express a reusable
            # constraint by themselves.
            return

        comment = (
            feedback.comment
            if isinstance(feedback.comment, str)
            else ""
        ).strip()

        title = (
            comment[:120]
            if comment
            else f"Feedback {feedback.feedback_type}"
        )

        description = (
            comment
            or "Constraint recorded from user feedback."
        )

        source_run_id = None

        if isinstance(
            feedback.metadata,
            dict,
        ):
            try:
                source_run_id = int(
                    feedback.metadata.get(
                        "run_id"
                    )
                )
            except (TypeError, ValueError):
                source_run_id = None

        constraint = ConstraintManager().create(
            title=title,
            description=description,
            constraint_type=constraint_type,
            scope=scope,
            status="proposed",
            topic=feedback.topic,
            region=feedback.region,
            language=feedback.language,
            reason=comment or None,
            confidence=0.5,
            priority=0,
            source_recommendation_id=(
                feedback.recommendation_id
            ),
            source_feedback_id=feedback.id,
            source_run_id=source_run_id,
            metadata={
                "feedback_type": (
                    feedback.feedback_type
                ),
                **(
                    feedback.metadata
                    if isinstance(
                        feedback.metadata,
                        dict,
                    )
                    else {}
                ),
            },
        )

        self.memory.save_constraint(
            constraint.to_dict()
        )
