"""
Director Constraints — Memory 2.0

Constraints are reusable knowledge that influences future decisions.

A rejected recommendation is NOT automatically a constraint.

Constraint lifecycle:

    proposed
       ↓
    active
       ↓
    paused / expired

Every constraint has:
- scope
- reason
- confidence
- source
- optional execution condition
- optional review/expiration information
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

CONSTRAINT_TYPES = {
    "avoid",
    "prefer",
    "require",
    "resource_limit",
}

CONSTRAINT_STATUSES = {
    "proposed",
    "active",
    "paused",
    "expired",
    "rejected",
}


@dataclass
class Constraint:
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

    active_from: str | None = None
    review_at: str | None = None
    expires_at: str | None = None

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

        if not isinstance(
            self.metadata,
            dict,
        ):
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
        value: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                "constraint_type must be a string"
            )

        value = value.strip().lower()

        if value not in CONSTRAINT_TYPES:
            raise ValueError(
                f"Unknown constraint type: {value}"
            )

        return value

    @staticmethod
    def _validate_scope(
        value: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                "scope must be a string"
            )

        value = value.strip().lower()

        if value not in CONSTRAINT_SCOPES:
            raise ValueError(
                f"Unknown constraint scope: {value}"
            )

        return value

    @staticmethod
    def _validate_status(
        value: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                "status must be a string"
            )

        value = value.strip().lower()

        if value not in CONSTRAINT_STATUSES:
            raise ValueError(
                f"Unknown constraint status: {value}"
            )

        return value

    @staticmethod
    def _validate_confidence(
        value: float,
    ) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.5

        return max(0.0, min(1.0, value))

    @staticmethod
    def _validate_priority(
        value: int,
    ) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def activate(
        self,
        *,
        timestamp: str | None = None,
    ) -> None:
        self.status = "active"

        if timestamp:
            self.active_from = timestamp

    def pause(self) -> None:
        self.status = "paused"

    def expire(self) -> None:
        self.status = "expired"

    def reject(self) -> None:
        self.status = "rejected"

    def applies_to(
        self,
        *,
        topic: str | None = None,
        region: str | None = None,
        language: str | None = None,
    ) -> bool:
        """
        Conservative scope matching.

        A constraint only applies when its defined dimensions match.

        Missing dimensions do not create a global match.
        """

        if self.status != "active":
            return False

        if self.scope == "global":
            return True

        if self.scope in {
            "topic",
            "topic_region",
            "topic_language",
        }:
            if not self.topic:
                return False

            if not topic:
                return False

            if self.topic.lower() != topic.lower():
                return False

        if self.scope in {
            "region",
            "topic_region",
            "region_language",
        }:
            if not self.region:
                return False

            if not region:
                return False

            if self.region.lower() != region.lower():
                return False

        if self.scope in {
            "language",
            "topic_language",
            "region_language",
        }:
            if not self.language:
                return False

            if not language:
                return False

            if self.language.lower() != language.lower():
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
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
            "execution_condition": self.execution_condition,
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
            "active_from": self.active_from,
            "review_at": self.review_at,
            "expires_at": self.expires_at,
            "metadata": dict(self.metadata),
        }


class ConstraintManager:
    """Factory and lifecycle helper."""

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
        active_from: str | None = None,
        review_at: str | None = None,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Constraint:
        return Constraint(
            title=title,
            description=description,
            constraint_type=constraint_type,
            scope=scope,
            status=status,
            topic=topic,
            region=region,
            language=language,
            execution_condition=execution_condition,
            reason=reason,
            confidence=confidence,
            priority=priority,
            source_recommendation_id=(
                source_recommendation_id
            ),
            source_feedback_id=source_feedback_id,
            source_run_id=source_run_id,
            active_from=active_from,
            review_at=review_at,
            expires_at=expires_at,
            metadata=metadata or {},
        )


def constraint_from_dict(
    data: dict[str, Any],
) -> Constraint:
    return Constraint(
        title=data.get("title", ""),
        description=data.get("description", ""),
        constraint_type=data.get(
            "constraint_type",
            "avoid",
        ),
        scope=data.get(
            "scope",
            "recommendation",
        ),
        status=data.get(
            "status",
            "proposed",
        ),
        topic=data.get("topic"),
        region=data.get("region"),
        language=data.get("language"),
        execution_condition=data.get(
            "execution_condition"
        ),
        reason=data.get("reason"),
        confidence=data.get(
            "confidence",
            0.5,
        ),
        priority=data.get(
            "priority",
            0,
        ),
        source_recommendation_id=data.get(
            "source_recommendation_id"
        ),
        source_feedback_id=data.get(
            "source_feedback_id"
        ),
        source_run_id=data.get(
            "source_run_id"
        ),
        active_from=data.get(
            "active_from"
        ),
        review_at=data.get(
            "review_at"
        ),
        expires_at=data.get(
            "expires_at"
        ),
        metadata=data.get(
            "metadata",
            {},
        ),
        id=data.get("id"),
    )
