```python
"""
Director Recommendations

This module defines the Director-facing model for recommendations.

Important:
- Director does not know about Supabase.
- Director does not know about SQL.
- Director does not know table names.
- Storage is handled by Memory / MemoryBackend.

A recommendation is a strategic proposal made by the Director.

Examples:
- investigate a niche;
- run a pilot;
- increase research priority;
- revisit a previously discovered direction.

User feedback is stored separately from the recommendation itself.

The purpose of this module is to give recommendations a stable
structure before connecting them to the actual storage backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# RECOMMENDATION STATUSES
# ---------------------------------------------------------------------------

RECOMMENDATION_STATUSES = {
    "new",
    "active",
    "accepted",
    "rejected",
    "deferred",
    "completed",
    "archived",
}


# ---------------------------------------------------------------------------
# FEEDBACK TYPES
# ---------------------------------------------------------------------------

FEEDBACK_TYPES = {
    "accept",
    "reject",
    "defer",
    "investigate",
    "change_priority",
    "comment",
}


# ---------------------------------------------------------------------------
# RECOMMENDATION
# ---------------------------------------------------------------------------

@dataclass
class Recommendation:
    """
    A strategic recommendation produced by the Director.

    The object intentionally contains both human-readable information
    and structured fields.

    Structured fields are important because later the Director must be
    able to reason about recommendations without relying only on text.
    """

    title: str
    description: str

    recommendation_type: str = "research_direction"

    status: str = "new"

    topic: str | None = None
    region: str | None = None
    language: str | None = None

    rationale: str | None = None

    suggested_action: str | None = None

    confidence: float | None = None
    priority: int | None = None

    run_id: int | None = None
    decision_id: int | None = None

    source_data: dict[str, Any] = field(
        default_factory=dict
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    id: int | None = None

    def __post_init__(self) -> None:
        self.title = self._clean_required(
            self.title,
            "title",
        )

        self.description = self._clean_required(
            self.description,
            "description",
        )

        self.recommendation_type = self._clean_required(
            self.recommendation_type,
            "recommendation_type",
        )

        self.status = self._validate_status(
            self.status
        )

        self.confidence = self._validate_confidence(
            self.confidence
        )

        self.priority = self._validate_priority(
            self.priority
        )

        if not isinstance(self.source_data, dict):
            self.source_data = {}

        if not isinstance(self.metadata, dict):
            self.metadata = {}

    @staticmethod
    def _clean_required(
        value: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                f"{field_name} must be a string"
            )

        value = value.strip()

        if not value:
            raise ValueError(
                f"{field_name} cannot be empty"
            )

        return value

    @staticmethod
    def _validate_status(
        status: str,
    ) -> str:
        if not isinstance(status, str):
            raise TypeError(
                "status must be a string"
            )

        status = status.strip().lower()

        if status not in RECOMMENDATION_STATUSES:
            raise ValueError(
                f"Unknown recommendation status: {status}"
            )

        return status

    @staticmethod
    def _validate_confidence(
        confidence: float | None,
    ) -> float | None:
        if confidence is None:
            return None

        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "confidence must be a number"
            ) from exc

        if confidence < 0:
            confidence = 0.0

        if confidence > 1:
            confidence = 1.0

        return confidence

    @staticmethod
    def _validate_priority(
        priority: int | None,
    ) -> int | None:
        if priority is None:
            return None

        try:
            priority = int(priority)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "priority must be an integer"
            ) from exc

        return priority

    def set_status(
        self,
        status: str,
    ) -> None:
        """
        Change recommendation status.
        """

        self.status = self._validate_status(
            status
        )

    def set_priority(
        self,
        priority: int | None,
    ) -> None:
        """
        Change research priority of this recommendation.
        """

        self.priority = self._validate_priority(
            priority
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert recommendation into a storage-independent dictionary.
        """

        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "recommendation_type": self.recommendation_type,
            "status": self.status,
            "topic": self.topic,
            "region": self.region,
            "language": self.language,
            "rationale": self.rationale,
            "suggested_action": self.suggested_action,
            "confidence": self.confidence,
            "priority": self.priority,
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "source_data": self.source_data,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# FEEDBACK
# ---------------------------------------------------------------------------

@dataclass
class RecommendationFeedback:
    """
    User feedback about a recommendation.

    This is deliberately separate from Recommendation.

    A rejection is not automatically interpreted as rejection of the
    entire topic, region, or thematic cluster.

    The scope of the feedback can later be clarified by the Director.

    Examples:

        scope="topic"

        scope="region"

        scope="topic_region"

        scope="execution"

        scope="global"
    """

    recommendation_id: int | None

    feedback_type: str

    comment: str = ""

    scope: str | None = None

    topic: str | None = None
    region: str | None = None
    language: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.feedback_type,
            str,
        ):
            raise TypeError(
                "feedback_type must be a string"
            )

        self.feedback_type = (
            self.feedback_type
            .strip()
            .lower()
        )

        if (
            self.feedback_type
            not in FEEDBACK_TYPES
        ):
            raise ValueError(
                f"Unknown feedback type: "
                f"{self.feedback_type}"
            )

        if not isinstance(
            self.comment,
            str,
        ):
            self.comment = str(
                self.comment
            )

        self.comment = self.comment.strip()

        if self.scope is not None:
            if not isinstance(
                self.scope,
                str,
            ):
                raise TypeError(
                    "scope must be a string or None"
                )

            self.scope = (
                self.scope
                .strip()
                .lower()
            )

        if not isinstance(
            self.metadata,
            dict,
        ):
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """
        Convert feedback into a storage-independent dictionary.
        """

        return {
            "id": self.id,
            "recommendation_id": self.recommendation_id,
            "feedback_type": self.feedback_type,
            "comment": self.comment,
            "scope": self.scope,
            "topic": self.topic,
            "region": self.region,
            "language": self.language,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# RECOMMENDATION MANAGER
# ---------------------------------------------------------------------------

class RecommendationManager:
    """
    Director-facing recommendation manager.

    This class does NOT save anything to Supabase or SQLite.

    It prepares and validates recommendation objects.

    Actual persistence will be connected later through the memory layer.
    """

    def create(
        self,
        *,
        title: str,
        description: str,
        recommendation_type: str = "research_direction",
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        rationale: str | None = None,
        suggested_action: str | None = None,
        confidence: float | None = None,
        priority: int | None = None,
        run_id: int | None = None,
        decision_id: int | None = None,
        source_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Recommendation:
        """
        Create a validated recommendation.
        """

        return Recommendation(
            title=title,
            description=description,
            recommendation_type=recommendation_type,
            topic=topic,
            region=region,
            language=language,
            rationale=rationale,
            suggested_action=suggested_action,
            confidence=confidence,
            priority=priority,
            run_id=run_id,
            decision_id=decision_id,
            source_data=(
                source_data
                if isinstance(source_data, dict)
                else {}
            ),
            metadata=(
                metadata
                if isinstance(metadata, dict)
                else {}
            ),
        )

    def create_feedback(
        self,
        *,
        recommendation_id: int | None,
        feedback_type: str,
        comment: str = "",
        scope: str | None = None,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RecommendationFeedback:
        """
        Create validated feedback for a recommendation.
        """

        return RecommendationFeedback(
            recommendation_id=recommendation_id,
            feedback_type=feedback_type,
            comment=comment,
            scope=scope,
            topic=topic,
            region=region,
            language=language,
            metadata=(
                metadata
                if isinstance(metadata, dict)
                else {}
            ),
        )

    @staticmethod
    def apply_feedback(
        recommendation: Recommendation,
        feedback: RecommendationFeedback,
    ) -> Recommendation:
        """
        Apply the immediate status effect of user feedback.

        Important:
        This method does NOT decide the long-term meaning of rejection.

        For example:

            "I don't want gardening in Central England"

        does not automatically become:

            "gardening is forbidden"

        The scope of such a constraint must be determined separately.
        """

        if (
            feedback.feedback_type == "accept"
        ):
            recommendation.set_status(
                "accepted"
            )

        elif (
            feedback.feedback_type == "reject"
        ):
            recommendation.set_status(
                "rejected"
            )

        elif (
            feedback.feedback_type == "defer"
        ):
            recommendation.set_status(
                "deferred"
            )

        elif (
            feedback.feedback_type
            == "investigate"
        ):
            recommendation.set_status(
                "active"
            )

        elif (
            feedback.feedback_type
            == "change_priority"
        ):
            recommendation.set_status(
                "active"
            )

        elif (
            feedback.feedback_type == "comment"
        ):
            # A comment alone does not change the
            # recommendation's status.
            pass

        return recommendation
```
