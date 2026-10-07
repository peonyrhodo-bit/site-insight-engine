"""
In-memory Memory Backend — Memory 2.0

Development/test backend that implements the same MemoryBackend
contract as SupabaseMemoryBackend without requiring external services.

Architecture:

```
Director
    ↓
Memory
    ↓
InMemoryMemoryBackend
    ↓
process-local storage
```

It is selected only in FREE_MODE / explicit MEMORY_BACKEND=memory,
so production behavior (Supabase required) is preserved.

Row shapes intentionally mirror SupabaseMemoryBackend rows
(including data_json and the same unpacking rules), so the rest of
the system does not need to know which backend is used.
"""

from **future** import annotations

from datetime import datetime, timezone
from typing import Any

def _utc_now() -> str:
return datetime.now(timezone.utc).isoformat()

def _safe_dict(value: Any) -> dict[str, Any]:
return value if isinstance(value, dict) else {}

def _clean(
value: Any,
default: Any = None,
) -> Any:
if value is None:
return default

```
if isinstance(value, str):
    value = value.strip()
    return value or default

return value
```

class InMemoryMemoryBackend:
"""
Process-local implementation of the MemoryBackend protocol.

```
All tables are plain lists of dicts with monotonically growing ids.
"""

def __init__(self) -> None:
    self._next_id: int = 1

    self._runs: list[dict[str, Any]] = []
    self._decisions: list[dict[str, Any]] = []
    self._chat: list[dict[str, Any]] = []
    self._actions: list[dict[str, Any]] = []
    self._results: list[dict[str, Any]] = []
    self._events: list[dict[str, Any]] = []
    self._recommendations: list[dict[str, Any]] = []
    self._recommendation_feedback: list[dict[str, Any]] = []
    self._constraints: list[dict[str, Any]] = []

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _allocate_id(self) -> int:
    value = self._next_id
    self._next_id += 1
    return value

@staticmethod
def _limit(
    value: int,
    default: int = 20,
) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default

    return max(1, min(value, 100))

def _recent(
    self,
    rows: list[dict[str, Any]],
    limit: int,
    order_key: str = "id",
) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: row.get(order_key) or 0,
        reverse=True,
    )

    return ordered[: self._limit(limit)]

def _insert(
    self,
    rows: list[dict[str, Any]],
    payload: dict[str, Any],
) -> int:
    row_id = self._allocate_id()

    row = {
        "id": row_id,
        "created_at": _utc_now(),
    }
    row.update(payload)

    rows.append(row)

    return row_id

def _project_id_from_row(
    self,
    row: dict[str, Any],
) -> str | None:
    direct = row.get("project_id")
    if direct is not None:
        return str(direct)

    data = _safe_dict(row.get("data_json"))
    value = data.get("project_id")
    if value is not None:
        return str(value)

    for key in ("source_data", "metadata"):
        nested = _safe_dict(data.get(key))
        value = nested.get("project_id")
        if value is not None:
            return str(value)

    return None

def _recent_for_project(
    self,
    rows: list[dict[str, Any]],
    limit: int,
    project_id: str | None,
) -> list[dict[str, Any]]:
    if project_id is not None:
        project_id = str(project_id)
        rows = [
            row
            for row in rows
            if self._project_id_from_row(row) == project_id
        ]

    return self._recent(rows, limit)

# ------------------------------------------------------------------
# YOUTUBE DATA
# ------------------------------------------------------------------

def load_youtube_data(
    self,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    In-memory backend has no persisted YouTube DATA tables.

    The method mirrors the Supabase storage boundary so DataAdapter can
    use one integration path regardless of the selected backend.
    """
    return {
        "queries": [],
        "videos": [],
        "snapshots": [],
    }

# ------------------------------------------------------------------
# CONTEXT
# ------------------------------------------------------------------

def get_context(
    self,
    *,
    project_id: str | None = None,
    limit_runs: int = 10,
    limit_decisions: int = 20,
    limit_events: int = 30,
    limit_chat: int = 20,
    limit_actions: int = 20,
    limit_results: int = 20,
    limit_recommendations: int = 20,
    limit_constraints: int = 20,
) -> dict[str, Any]:
    return {
        "runs": self.get_recent_runs(
            limit=limit_runs,
            project_id=project_id
        ),
        "decisions": self.get_recent_decisions(
            limit=limit_decisions,
            project_id=project_id
        ),
        "recommendations": (
            self.get_recent_recommendations(
                limit=limit_recommendations,
                project_id=project_id
            )
        ),
        "constraints": (
            self.get_recent_constraints(
                limit=limit_constraints,
                project_id=project_id
            )
        ),
        "events": self.get_recent_events(
            limit=limit_events,
            project_id=project_id
        ),
        "chat": self.get_recent_chat_messages(
            limit=limit_chat,
            project_id=project_id
        ),
        "actions": self.get_recent_actions(
            limit=limit_actions,
            project_id=project_id
        ),
        "results": self.get_recent_results(
            limit=limit_results,
            project_id=project_id
        ),
    }

# ------------------------------------------------------------------
# RUNS
# ------------------------------------------------------------------

def save_run(
    self,
    *,
    language: str | None = None,
    region_code: str | None = None,
    data: dict[str, Any] | None = None,
) -> int | None:
    return self._insert(
        self._runs,
        {
            "language": _clean(language),
            "region_code": _clean(region_code),
            "data_json": _safe_dict(data),
        },
    )

def get_recent_runs(
    self,
    *,
    limit: int = 10,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    return self._recent(
        self._runs,
        limit,
    )

# ------------------------------------------------------------------
# DECISIONS
# ------------------------------------------------------------------

def save_decision(
    self,
    *,
    decision: str,
    data: dict[str, Any] | None = None,
    run_id: int | None = None,
) -> int | None:
    return self._insert(
        self._decisions,
        {
            "decision": _clean(decision, ""),
            "run_id": run_id,
            "data_json": _safe_dict(data),
        },
    )

def get_recent_decisions(
    self,
    *,
    limit: int = 20,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    return self._recent(
        self._decisions,
        limit,
    )

# ------------------------------------------------------------------
# CHAT
# ------------------------------------------------------------------

def save_chat_message(
    self,
    *,
    role: str,
    message: str,
    run_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> int | None:
    return self._insert(
        self._chat,
        {
            "role": _clean(role, ""),
            "message": _clean(message, ""),
            "run_id": run_id,
            "data_json": _safe_dict(data),
        },
    )

def get_recent_chat_messages(
    self,
    *,
    limit: int = 20,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    return self._recent(
        self._chat,
        limit,
    )

# ------------------------------------------------------------------
# ACTIONS
# ------------------------------------------------------------------

def save_action(
    self,
    *,
    action_type: str,
    description: str = "",
    run_id: int | None = None,
    decision_id: int | None = None,
    status: str = "pending",
    data: dict[str, Any] | None = None,
) -> int | None:
    return self._insert(
        self._actions,
        {
            "action_type": _clean(action_type, ""),
            "description": _clean(description, ""),
            "run_id": run_id,
            "decision_id": decision_id,
            "status": _clean(status, "pending"),
            "data_json": _safe_dict(data),
        },
    )

def get_recent_actions(
    self,
    *,
    limit: int = 20,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    return self._recent(
        self._actions,
        limit,
    )

# ------------------------------------------------------------------
# RESULTS
# ------------------------------------------------------------------

def save_result(
    self,
    *,
    result_type: str,
    summary: str = "",
    action_id: int | None = None,
    run_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> int | None:
    return self._insert(
        self._results,
        {
            "result_type": _clean(result_type, ""),
            "summary": _clean(summary, ""),
            "action_id": action_id,
            "run_id": run_id,
            "data_json": _safe_dict(data),
        },
    )

def get_recent_results(
    self,
    *,
    limit: int = 20,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    return self._recent(
        self._results,
        limit,
    )

# ------------------------------------------------------------------
# EVENTS
# ------------------------------------------------------------------

def save_event(
    self,
    *,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> int | None:
    return self._insert(
        self._events,
        {
            "event_type": _clean(event_type, ""),
            "data_json": _safe_dict(data),
        },
    )

def get_recent_events(
    self,
    *,
    limit: int = 30,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    return self._recent(
        self._events,
        limit,
    )

# ------------------------------------------------------------------
# RECOMMENDATIONS
# ------------------------------------------------------------------

def save_recommendation(
    self,
    *,
    recommendation: dict[str, Any],
) -> int | None:
    recommendation = _safe_dict(recommendation)

    return self._insert(
        self._recommendations,
        {
            "run_id": recommendation.get("run_id"),
            "decision_id": recommendation.get(
                "decision_id"
            ),
            "title": recommendation.get("title"),
            "description": recommendation.get(
                "description"
            ),
            "recommendation_type": recommendation.get(
                "recommendation_type"
            ),
            "topic": recommendation.get("topic"),
            "region": recommendation.get("region"),
            "language": recommendation.get("language"),
            "rationale": recommendation.get(
                "rationale"
            ),
            "suggested_action": recommendation.get(
                "suggested_action"
            ),
            "confidence": recommendation.get(
                "confidence"
            ),
            "priority": recommendation.get("priority"),
            "status": recommendation.get(
                "status",
                "pending",
            ),
            "data_json": {
                "source_data": _safe_dict(
                    recommendation.get(
                        "source_data"
                    )
                ),
                "metadata": _safe_dict(
                    recommendation.get("metadata")
                ),
                "user_response": recommendation.get(
                    "user_response"
                ),
                "result_summary": recommendation.get(
                    "result_summary"
                ),
                "lesson": recommendation.get("lesson"),
                "shown_at": recommendation.get(
                    "shown_at"
                ),
                "accepted_at": recommendation.get(
                    "accepted_at"
                ),
                "rejected_at": recommendation.get(
                    "rejected_at"
                ),
                "completed_at": recommendation.get(
                    "completed_at"
                ),
            },
        },
    )

def get_recent_recommendations(
    self,
    *,
    limit: int = 20,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = self._recent(
        self._recommendations,
        limit,
    )

    for row in rows:
        data = row.get("data_json")

        if isinstance(data, dict):
            source_data = data.get("source_data")
            metadata = data.get("metadata")

            if isinstance(source_data, dict):
                row["source_data"] = source_data

            if isinstance(metadata, dict):
                row["metadata"] = metadata

            for key in (
                "user_response",
                "result_summary",
                "lesson",
                "shown_at",
                "accepted_at",
                "rejected_at",
                "completed_at",
            ):
                if key in data:
                    row[key] = data[key]

    return rows

# ------------------------------------------------------------------
# RECOMMENDATION FEEDBACK
# ------------------------------------------------------------------

def save_recommendation_feedback(
    self,
    *,
    feedback: dict[str, Any],
) -> int | None:
    feedback = _safe_dict(feedback)

    data_json = _safe_dict(
        feedback.get("metadata")
    )

    for key in (
        "reason",
        "priority",
        "creates_constraint",
        "run_id",
        "decision_id",
        "feedback_id",
        "target",
        "constraint",
        "preference",
        "created_at",
        "type",
    ):
        if key in feedback:
            data_json[key] = feedback[key]

    comment = feedback.get("message")
    if comment is None:
        comment = feedback.get("comment")

    return self._insert(
        self._recommendation_feedback,
        {
            "recommendation_id": feedback.get(
                "recommendation_id"
            ),
            "feedback_type": feedback.get(
                "feedback_type"
            ),
            "comment": comment,
            "scope": feedback.get("scope"),
            "topic": feedback.get("topic"),
            "region": feedback.get("region"),
            "language": feedback.get("language"),
            "data_json": data_json,
        },
    )

def apply_recommendation_feedback(
    self,
    *,
    feedback: dict[str, Any],
) -> dict[str, Any]:
    """
    Persist feedback and update recommendation status,
    mirroring the Supabase backend contract.
    """
    feedback = _safe_dict(feedback)

    feedback_id = self.save_recommendation_feedback(
        feedback=feedback
    )

    feedback_type = str(
        feedback.get("feedback_type", "")
    ).lower()

    status_map = {
        "accept": "accepted",
        "reject": "rejected",
        "defer": "deferred",
    }

    recommendation_id = feedback.get(
        "recommendation_id"
    )

    updated_status = status_map.get(
        feedback_type
    )

    updated = False

    if recommendation_id is not None and updated_status:
        try:
            target_id = int(recommendation_id)
        except (TypeError, ValueError):
            target_id = None

        for row in self._recommendations:
            if row.get("id") == target_id:
                row["status"] = updated_status
                updated = True
                break

    return {
        "feedback_id": feedback_id,
        "recommendation_id": recommendation_id,
        "feedback_type": feedback_type,
        "status": updated_status,
        "updated": updated,
        "creates_constraint": bool(
            feedback.get(
                "creates_constraint",
                False,
            )
        ),
    }

# ------------------------------------------------------------------
# CONSTRAINTS
# ------------------------------------------------------------------

def save_constraint(
    self,
    *,
    constraint: dict[str, Any],
) -> int | None:
    constraint = _safe_dict(constraint)

    return self._insert(
        self._constraints,
        {
            "title": constraint.get("title"),
            "description": constraint.get(
                "description"
            ),
            "constraint_type": constraint.get(
                "constraint_type",
                "avoid",
            ),
            "scope": constraint.get(
                "scope",
                "recommendation",
            ),
            "status": constraint.get(
                "status",
                "proposed",
            ),
            "topic": constraint.get("topic"),
            "region": constraint.get("region"),
            "language": constraint.get("language"),
            "execution_condition": constraint.get(
                "execution_condition"
            ),
            "reason": constraint.get("reason"),
            "confidence": constraint.get(
                "confidence",
                0.5,
            ),
            "priority": constraint.get(
                "priority",
                0,
            ),
            "source_recommendation_id": constraint.get(
                "source_recommendation_id"
            ),
            "source_feedback_id": constraint.get(
                "source_feedback_id"
            ),
            "source_run_id": constraint.get(
                "source_run_id"
            ),
            "data_json": {
                "active_from": constraint.get(
                    "active_from"
                ),
                "review_at": constraint.get(
                    "review_at"
                ),
                "expires_at": constraint.get(
                    "expires_at"
                ),
                "metadata": _safe_dict(
                    constraint.get("metadata")
                ),
            },
        },
    )

def get_recent_constraints(
    self,
    *,
    limit: int = 20,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = self._recent(
        self._constraints,
        limit,
    )

    for row in rows:
        data = row.get("data_json")

        if not isinstance(data, dict):
            continue

        for key in (
            "active_from",
            "review_at",
            "expires_at",
        ):
            if key in data:
                row[key] = data[key]

        metadata = data.get("metadata")

        if isinstance(metadata, dict):
            row["metadata"] = metadata

    return rows
```

def create_inmemory_backend() -> InMemoryMemoryBackend:
"""Factory for the development memory backend."""
return InMemoryMemoryBackend()
