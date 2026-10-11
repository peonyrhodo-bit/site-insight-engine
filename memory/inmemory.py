"""In-memory implementation of the Memory 2.0 backend contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clean(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        return value or default
    return value


class InMemoryMemoryBackend:
    """Process-local storage backend used in development and tests."""

    def __init__(self) -> None:
        self._next_id = 1
        self._runs: list[dict[str, Any]] = []
        self._decisions: list[dict[str, Any]] = []
        self._chat: list[dict[str, Any]] = []
        self._actions: list[dict[str, Any]] = []
        self._results: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._recommendations: list[dict[str, Any]] = []
        self._recommendation_feedback: list[dict[str, Any]] = []
        self._constraints: list[dict[str, Any]] = []

    def _allocate_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    @staticmethod
    def _limit(value: int, default: int = 20) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return max(1, min(value, 100))

    def _insert(self, rows: list[dict[str, Any]], payload: dict[str, Any]) -> int:
        row_id = self._allocate_id()
        row = {"id": row_id, "created_at": _utc_now()}
        row.update(payload)
        rows.append(row)
        return row_id

    @staticmethod
    def _project_id_from_row(row: dict[str, Any]) -> str | None:
        direct = row.get("project_id")
        if direct is not None:
            return str(direct)
        data = _safe_dict(row.get("data_json"))
        for container in (data, _safe_dict(data.get("source_data")), _safe_dict(data.get("metadata"))):
            value = container.get("project_id")
            if value is not None:
                return str(value)
        return None

    def _recent(self, rows: list[dict[str, Any]], limit: int, order_key: str = "id") -> list[dict[str, Any]]:
        return [dict(row) for row in sorted(rows, key=lambda row: row.get(order_key) or 0, reverse=True)[:self._limit(limit)]]

    def _recent_for_project(self, rows: list[dict[str, Any]], limit: int, project_id: str | None) -> list[dict[str, Any]]:
        if project_id is not None:
            expected = str(project_id)
            rows = [row for row in rows if self._project_id_from_row(row) == expected]
        return self._recent(rows, limit)

    def get_context(
        self, *, project_id: str | None = None, limit_runs: int = 10,
        limit_decisions: int = 20, limit_events: int = 30, limit_chat: int = 20,
        limit_actions: int = 20, limit_results: int = 20,
        limit_recommendations: int = 20, limit_constraints: int = 20,
    ) -> dict[str, Any]:
        return {
            "runs": self.get_recent_runs(limit=limit_runs, project_id=project_id),
            "decisions": self.get_recent_decisions(limit=limit_decisions, project_id=project_id),
            "events": self.get_recent_events(limit=limit_events, project_id=project_id),
            "chat": self.get_recent_chat_messages(limit=limit_chat, project_id=project_id),
            "actions": self.get_recent_actions(limit=limit_actions, project_id=project_id),
            "results": self.get_recent_results(limit=limit_results, project_id=project_id),
            "recommendations": self.get_recent_recommendations(limit=limit_recommendations, project_id=project_id),
            "constraints": self.get_recent_constraints(limit=limit_constraints, project_id=project_id),
        }

    # Runs
    def save_run(self, *, language: str | None = None, region_code: str | None = None, data: dict[str, Any] | None = None) -> int:
        run_data = _safe_dict(data)
        payload = {"language": _clean(language), "region_code": _clean(region_code), "data_json": run_data}
        for field in ("project_id", "status", "started_at", "finished_at", "current_step", "error_message", "updated_at"):
            if field in run_data:
                payload[field] = run_data[field]
        return self._insert(self._runs, payload)

    def update_run(self, *, run_id: int, data: dict[str, Any]) -> bool:
        for row in self._runs:
            if row.get("id") == run_id:
                row["data_json"] = {**_safe_dict(row.get("data_json")), **_safe_dict(data)}
                for field in ("project_id", "status", "started_at", "finished_at", "current_step", "error_message", "updated_at"):
                    if field in data:
                        row[field] = data[field]
                return True
        return False

    def get_recent_runs(self, *, limit: int = 10, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._recent_for_project(self._runs, limit, project_id)

    # Decisions
    def save_decision(self, *, decision: str, data: dict[str, Any] | None = None, run_id: int | None = None) -> int:
        return self._insert(self._decisions, {"decision": _clean(decision, ""), "run_id": run_id, "data_json": _safe_dict(data)})

    def get_recent_decisions(self, *, limit: int = 20, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._recent_for_project(self._decisions, limit, project_id)

    # Chat
    def save_chat_message(self, *, role: str, message: str, run_id: int | None = None, data: dict[str, Any] | None = None) -> int:
        return self._insert(self._chat, {"role": _clean(role, ""), "message": _clean(message, ""), "run_id": run_id, "data_json": _safe_dict(data)})

    def get_recent_chat_messages(self, *, limit: int = 20, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._recent_for_project(self._chat, limit, project_id)

    # Actions
    def save_action(self, *, action_type: str, description: str = "", run_id: int | None = None, decision_id: int | None = None, status: str = "pending", data: dict[str, Any] | None = None) -> int:
        return self._insert(self._actions, {"action_type": _clean(action_type, ""), "description": _clean(description, ""), "run_id": run_id, "decision_id": decision_id, "status": _clean(status, "pending"), "data_json": _safe_dict(data)})

    def get_recent_actions(self, *, limit: int = 20, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._recent_for_project(self._actions, limit, project_id)

    # Results
    def save_result(self, *, result_type: str, summary: str = "", action_id: int | None = None, run_id: int | None = None, data: dict[str, Any] | None = None) -> int:
        return self._insert(self._results, {"result_type": _clean(result_type, ""), "summary": _clean(summary, ""), "action_id": action_id, "run_id": run_id, "data_json": _safe_dict(data)})

    def get_recent_results(self, *, limit: int = 20, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._recent_for_project(self._results, limit, project_id)

    # Events
    def save_event(self, *, event_type: str, data: dict[str, Any] | None = None) -> int:
        return self._insert(self._events, {"event_type": _clean(event_type, ""), "data_json": _safe_dict(data)})

    def get_recent_events(self, *, limit: int = 30, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._recent_for_project(self._events, limit, project_id)

    # Recommendations
    def save_recommendation(self, *, recommendation: dict[str, Any]) -> int:
        record = _safe_dict(recommendation)
        row = {
            "run_id": record.get("run_id"), "decision_id": record.get("decision_id"),
            "title": record.get("title"), "description": record.get("description"),
            "recommendation_type": record.get("recommendation_type"), "topic": record.get("topic"),
            "region": record.get("region"), "language": record.get("language"),
            "rationale": record.get("rationale"), "suggested_action": record.get("suggested_action"),
            "confidence": record.get("confidence"), "priority": record.get("priority"),
            "status": record.get("status", "pending"),
            "data_json": {"source_data": _safe_dict(record.get("source_data")), "metadata": _safe_dict(record.get("metadata"))},
        }
        return self._insert(self._recommendations, row)

    def get_recent_recommendations(self, *, limit: int = 20, project_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._recent_for_project(self._recommendations, limit, project_id)
        for row in rows:
            data = _safe_dict(row.get("data_json"))
            row["source_data"] = _safe_dict(data.get("source_data"))
            row["metadata"] = _safe_dict(data.get("metadata"))
        return rows

    def save_recommendation_feedback(self, *, feedback: dict[str, Any]) -> int:
        record = _safe_dict(feedback)
        data = _safe_dict(record.get("metadata"))
        for key in ("reason", "priority", "creates_constraint", "run_id", "decision_id", "feedback_id", "target", "constraint", "preference", "created_at", "type"):
            if key in record:
                data[key] = record[key]
        return self._insert(self._recommendation_feedback, {
            "recommendation_id": record.get("recommendation_id"), "feedback_type": record.get("feedback_type"),
            "comment": record.get("message", record.get("comment")), "scope": record.get("scope"),
            "topic": record.get("topic"), "region": record.get("region"), "language": record.get("language"),
            "data_json": data,
        })

    def apply_recommendation_feedback(self, *, feedback: dict[str, Any]) -> dict[str, Any]:
        record = _safe_dict(feedback)
        feedback_id = self.save_recommendation_feedback(feedback=record)
        status_map = {"accept": "accepted", "reject": "rejected", "defer": "deferred"}
        feedback_type = str(record.get("feedback_type") or "").lower()
        status = status_map.get(feedback_type)
        recommendation_id = record.get("recommendation_id")
        updated = False
        if recommendation_id is not None and status:
            for row in self._recommendations:
                if row.get("id") == recommendation_id:
                    row["status"] = status
                    updated = True
                    break
        return {"feedback_id": feedback_id, "recommendation_id": recommendation_id, "feedback_type": feedback_type, "status": status, "updated": updated, "creates_constraint": bool(record.get("creates_constraint", False))}

    # Constraints
    def save_constraint(self, *, constraint: dict[str, Any]) -> int:
        record = _safe_dict(constraint)
        return self._insert(self._constraints, {
            "title": record.get("title"), "description": record.get("description"),
            "constraint_type": record.get("constraint_type", "avoid"), "scope": record.get("scope", "recommendation"),
            "status": record.get("status", "proposed"), "topic": record.get("topic"),
            "region": record.get("region"), "language": record.get("language"),
            "execution_condition": record.get("execution_condition"), "reason": record.get("reason"),
            "confidence": record.get("confidence", 0.5), "priority": record.get("priority", 0),
            "source_recommendation_id": record.get("source_recommendation_id"),
            "source_feedback_id": record.get("source_feedback_id"), "source_run_id": record.get("source_run_id"),
            "data_json": {"active_from": record.get("active_from"), "review_at": record.get("review_at"), "expires_at": record.get("expires_at"), "metadata": _safe_dict(record.get("metadata"))},
        })

    def get_recent_constraints(self, *, limit: int = 20, project_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._recent_for_project(self._constraints, limit, project_id)
        for row in rows:
            data = _safe_dict(row.get("data_json"))
            for key in ("active_from", "review_at", "expires_at"):
                if key in data:
                    row[key] = data[key]
            row["metadata"] = _safe_dict(data.get("metadata"))
        return rows

    # Optional DATA-layer compatibility methods.
    def load_youtube_data(self, *, project_id: str | None = None) -> dict[str, Any]:
        return {"queries": [], "videos": [], "snapshots": []}

    def save_youtube_data(self, *, project_id: str, videos: list[dict[str, Any]] | None = None, snapshots: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {"videos": 0, "snapshots": 0, "snapshot_ids": []}
