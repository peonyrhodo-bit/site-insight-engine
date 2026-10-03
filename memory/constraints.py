"""
Director Constraints

This module defines constraints learned from user feedback.

Important:
- Director does not know about Supabase.
- Director does not know about SQL.
- Director does not know table names.
- Storage is handled by Memory / MemoryBackend.

A constraint is not the same thing as a rejected recommendation.

Recommendation:
    "This particular idea is not suitable."

Constraint:
    "Do not spend resources researching this type of idea."

The Director must be careful about the scope of a constraint.

For example:

    topic
    region
    language
    topic + region
    execution
    global

A rejection of one recommendation must NOT automatically become
a global prohibition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# CONSTRAINT SCOPES
# ---------------------------------------------------------------------------

CONSTRAINT_SCOPES = {
    "recommendation",
    "topic",
    "region",
    "language",
    "topic_region",
    "topic_language",
    "region_language",
    "execution",
    "global",
}


# ---------------------------------------------------------------------------
# CONSTRAINT TYPES
# ---------------------------------------------------------------------------

CONSTRAINT_TYPES = {
    "avoid",
    "prefer",
    "require",
    "resource_limit",
}


# ---------------------------------------------------------------------------
# CONSTRAINT STATUSES
# ---------------------------------------------------------------------------

CONSTRAINT_STATUSES = {
    "proposed",
    "active",
    "paused",
    "expired",
    "rejected",
}


# ---------------------------------------------------------------------------
# CONSTRAINT
# ---------------------------------------------------------------------------

@dataclass
class Constraint:
    """
    A rule that influences future Director research and decisions.

    A constraint should describe a reusable condition, not merely
    repeat the text of a user's comment.
    """

    title: str
    description: str

    constraint_type: str = "avoid"
    scope: str = "recommendation"
    status: str = "proposed"

    topic: str | None = None
    region: str | None = None
    language: str | None = None

    execution_condition: str | None = None

    reason: str | None = None

    confidence: float = 0.5

    priority: int = 0

    source_recommendation_id: int | None = None
    source_feedback_id: int | None = None
    source_run_id: int | None = None

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

        self.constraint_type = (
            self._validate_constraint_type(
                self.constraint_type
            )
        )

        self.scope = self._validate_scope(
            self.scope
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
    def _validate_constraint_type(
        constraint_type: str,
    ) -> str:
        if not isinstance(
            constraint_type,
            str,
        ):
            raise TypeError(
                "constraint_type must be a string"
            )

        constraint_type = (
            constraint_type
            .strip()
            .lower()
        )

        if (
            constraint_type
            not in CONSTRAINT_TYPES
        ):
            raise ValueError(
                f"Unknown constraint type: "
                f"{constraint_type}"
            )

        return constraint_type

    @staticmethod
    def _validate_scope(
        scope: str,
    ) -> str:
        if not isinstance(scope, str):
            raise TypeError(
                "scope must be a string"
            )

        scope = scope.strip().lower()

        if scope not in CONSTRAINT_SCOPES:
            raise ValueError(
                f"Unknown constraint scope: "
                f"{scope}"
            )

        return scope

    @staticmethod
    def _validate_status(
        status: str,
    ) -> str:
        if not isinstance(status, str):
            raise TypeError(
                "status must be a string"
            )

        status = status.strip().lower()

        if status not in CONSTRAINT_STATUSES:
            raise ValueError(
                f"Unknown constraint status: "
                f"{status}"
            )

        return status

    @staticmethod
    def _validate_confidence(
        confidence: float,
    ) -> float:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "confidence must be a number"
            ) from exc

        if confidence < 0.0:
            confidence = 0.0

        if confidence > 1.0:
            confidence = 1.0

        return confidence

    @staticmethod
    def _validate_priority(
        priority: int,
    ) -> int:
        try:
            priority = int(priority)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "priority must be an integer"
            ) from exc

        return priority

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the constraint into a storage-independent dictionary.
        """

        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "constraint_type": self.constraint_type,
            "scope": self.scope,
            "status": self.status,
            "topic": self.topic,
            "region": self.region,
            "language": self.language,
            "execution_condition": (
                self.execution_condition
            ),
            "reason": self.reason,
            "confidence": self.confidence,
            "priority": self.priority,
            "source_recommendation_id": (
                self.source_recommendation_id
            ),
            "source_feedback_id": (
                self.source_feedback_id
            ),
            "source_run_id": self.source_run_id,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# CONSTRAINT MANAGER
# ---------------------------------------------------------------------------

class ConstraintManager:
    """
    Director-facing constraint manager.

    This class creates and validates constraint objects.

    It does not persist anything itself; storage is handled by
    the memory layer (Memory / MemoryBackend).

    Important:
    A rejected recommendation is not automatically a global
    constraint. The scope must be explicit.
    """

    def create(
        self,
        *,
        title: str,
        description: str,
        constraint_type: str = "avoid",
        scope: str = "recommendation",
        status: str = "proposed",
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
        execution_condition: str | None = None,
        reason: str | None = None,
        confidence: float = 0.5,
        priority: int = 0,
        source_recommendation_id: int | None = None,
        source_feedback_id: int | None = None,
        source_run_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Constraint:
        """
        Create a validated constraint.
        """

        return Constraint(
            title=title,
            description=description,
            constraint_type=constraint_type,
            scope=scope,
            status=status,
            topic=topic,
            region=region,
            language=language,
            execution_condition=(
                execution_condition
            ),
            reason=reason,
            confidence=confidence,
            priority=priority,
            source_recommendation_id=(
                source_recommendation_id
            ),
            source_feedback_id=source_feedback_id,
            source_run_id=source_run_id,
            metadata=(
                metadata
                if isinstance(metadata, dict)
                else {}
            ),
        )
