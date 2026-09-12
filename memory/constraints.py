```python
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
```
