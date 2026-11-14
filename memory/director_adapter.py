"""Director-facing adapter for the Memory 2.0 subsystem.

All Director/Memory translation and persistence integration lives here.
server.py only constructs this adapter and delegates to it.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from director.trace_context import get_correlation_id

logger = logging.getLogger("memory.director_adapter")

FREE_MODE = (
    os.getenv("FREE_MODE", "true").lower()
    in {"1", "true", "yes", "on"}
)

try:
    from memory.memory import Memory
except Exception:
    Memory = None

try:
    from memory.supabase import SupabaseMemoryBackend
except Exception:
    SupabaseMemoryBackend = None

try:
    from memory.inmemory import InMemoryMemoryBackend
except Exception:
    InMemoryMemoryBackend = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DirectorCycleAlreadyRunning(RuntimeError):
    """Raised when a project already has an active autonomous Director cycle."""


def serialize(value: Any) -> Any:
    """Convert project objects/enums/dataclasses into JSON-safe values."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize(item) for item in value]
    if hasattr(value, "value"):
        try:
            return value.value
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return serialize(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "__dataclass_fields__"):
        try:
            from dataclasses import asdict
            return serialize(asdict(value))
        except Exception:
            pass
    return str(value)


# Director <-> Memory 2.0 contract adapters
#
# These helpers translate Director-facing models (DirectorRecommendation,
# DirectorDecision, DirectorFeedback) into the shapes expected by the
# existing Memory 2.0 API (memory/memory.py + memory/*).
# ---------------------------------------------------------------------------

def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _decision_to_memory_payload(
    decision: Any,
    *,
    project_id: str | None,
) -> dict[str, Any]:
    """
    Convert a DirectorDecision (or dict) into the payload expected by
    Memory.save_decision_model(): a dict with a non-empty "decision" key.
    """
    if hasattr(decision, "to_dict"):
        payload = decision.to_dict()
    elif isinstance(decision, dict):
        payload = dict(decision)
    else:
        payload = serialize(decision)

    if not isinstance(payload, dict):
        return {}

    # Normalize enums/dataclasses into JSON-safe values.
    payload = serialize(payload)

    text = str(
        payload.get("decision")
        or payload.get("title")
        or ""
    ).strip()

    if not text:
        decision_type = _enum_value(
            payload.get("decision_type")
        )
        objective = str(
            payload.get("objective")
            or ""
        ).strip()

        text = (
            f"{decision_type}: {objective}".strip(": ")
            or "Решение Директора"
        )

    record = dict(payload)
    record["decision"] = text
    record["project_id"] = project_id

    return record


def _recommendation_to_memory_payload(
    recommendation: Any,
    *,
    project_id: str | None,
    decision_db_id: int | None = None,
) -> dict[str, Any]:
    """
    Convert a DirectorRecommendation (or dict) into the dict shape
    expected by Memory.save_recommendation() (Memory 2.0).

    The stable Director recommendation_id and the string decision_id
    are preserved inside source_data so the item can be retrieved and
    linked back later.
    """
    if hasattr(recommendation, "to_dict"):
        data = recommendation.to_dict()
    elif isinstance(recommendation, dict):
        data = dict(recommendation)
    else:
        data = serialize(recommendation)

    if not isinstance(data, dict):
        return {}

    # Recommendation status is canonical across Director and Memory.
    # Do not translate it to a second lifecycle.
    status = str(
        _enum_value(data.get("status")) or "pending"
    ).strip().lower()

    target = data.get("target")
    if hasattr(target, "to_dict"):
        target = target.to_dict()
    elif isinstance(target, dict):
        target = dict(target)

    if not isinstance(target, dict):
        target = None

    evidence: list[dict[str, Any]] = []

    for item in data.get("evidence") or []:
        if hasattr(item, "to_dict"):
            item = item.to_dict()

        if isinstance(item, dict):
            evidence.append(
                {
                    "statement": item.get("statement"),
                    "source": item.get("source"),
                    "reference_id": item.get("reference_id"),
                    "strength": item.get("strength", 0.5),
                    "metadata": item.get("metadata", {}),
                }
            )
        else:
            evidence.append(
                {"statement": str(item)}
            )

    decision_id = data.get("decision_id")
    decision_column: int | None = None

    if decision_id is not None:
        try:
            decision_column = int(decision_id)
        except (TypeError, ValueError):
            decision_column = None

    if decision_column is None:
        decision_column = decision_db_id

    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    try:
        priority = int(round(confidence * 10))
    except (TypeError, ValueError):
        priority = None

    title = str(data.get("title") or "").strip()
    description = str(
        data.get("summary")
        or data.get("description")
        or ""
    ).strip()

    return serialize(
        {
            "title": title,
            "description": description,
            "recommendation_type": (
                "youtube_direction"
                if target
                else "research_direction"
            ),
            "status": status,
            "topic": (                str(target.get("title"))
                if target and target.get("title")
                else None
            ),
            "region": target.get("region") if target else None,
            "language": (
                str(target.get("language") or "ru")
                if target
                else "ru"
            ),
            "rationale": (
                data.get("reason")
                or data.get("rationale")
            ),
            "suggested_action": (
                data.get("proposed_action")
                or data.get("suggested_action")
            ),
            "confidence": confidence,
            "priority": priority,
            "decision_id": decision_column,
            "run_id": data.get("run_id"),
            "source_data": {
                "director_recommendation_id": data.get(
                    "recommendation_id"
                ),
                "decision_id": decision_id,
                "research_id": data.get("research_id"),
                "project_id": project_id,
                "target": target,
                "evidence": evidence,
                "risks": list(data.get("risks") or []),
                "constraints": list(
                    data.get("constraints") or []
                ),
                "summary": data.get("summary"),
            },
            "metadata": dict(data.get("metadata") or {}),
        }
    )


def _feedback_to_memory_payload(
    feedback: Any,
    *,
    project_id: str | None,
) -> dict[str, Any]:
    """
    Convert DirectorFeedback (or dict) into the payload expected by
    the canonical Memory recommendation-feedback operation.
    """
    if hasattr(feedback, "to_dict"):
        record = feedback.to_dict()
    elif isinstance(feedback, dict):
        record = dict(feedback)
    else:
        record = serialize(feedback)

    if not isinstance(record, dict):
        return {}

    feedback_type = _enum_value(
        record.get("feedback_type")
    )

    memory_type = str(
        feedback_type or ""
    ).strip().lower()

    if not memory_type:
        raise ValueError(
            "feedback_type is required"
        )

    recommendation_id = record.get(
        "recommendation_id"
    )

    recommendation_column: int | None = None

    if recommendation_id is not None:
        try:
            recommendation_column = int(
                recommendation_id
            )
        except (TypeError, ValueError):
            recommendation_column = None

    metadata = dict(record.get("metadata") or {})
    metadata["project_id"] = project_id

    if record.get("decision_id") is not None:
        metadata.setdefault(
            "decision_id",
            record.get("decision_id"),
        )

    if recommendation_column is None and recommendation_id:
        metadata["director_recommendation_id"] = (
            str(recommendation_id)
        )

    run_id = record.get("run_id")

    if run_id is None:
        run_id = metadata.get("run_id")

    return {
        "recommendation_id": recommendation_column,
        "feedback_type": memory_type,
        "message": record.get("message"),
        "reason": record.get("reason"),
        "scope": _enum_value(record.get("scope")),
        "creates_constraint": bool(
            record.get("constraint")
            or record.get("creates_constraint")
        ),
        "run_id": run_id,
        "metadata": metadata,
    }


def _memory_row_to_director_recommendation(
    row: dict[str, Any],
) -> Any:
    """
    Reconstruct a DirectorRecommendation from a Memory 2.0
    recommendation row (the reverse direction of the adapter above).
    """
    from director.recommendations import (
        DirectorRecommendation,
        RecommendationEvidence,
        RecommendationStatus,
        RecommendationTarget,
    )

    source_data = row.get("source_data")

    if not isinstance(source_data, dict):
        source_data = {}

    target = None

    target_data = source_data.get("target")

    if isinstance(target_data, dict):
        target = RecommendationTarget(
            kind=str(
                target_data.get("kind")
                or "youtube_direction"
            ),
            title=str(
                target_data.get("title") or ""
            ),
            description=str(
                target_data.get("description") or ""
            ),
            audience=target_data.get("audience"),
            format=target_data.get("format"),
            language=str(
                target_data.get("language") or "ru"
            ),
            metadata=dict(
                target_data.get("metadata") or {}
            ),
        )

    status_value = str(
        row.get("status") or "pending"
    ).strip().lower()

    # Memory stores the same canonical lifecycle values as Director.
    status = RecommendationStatus(status_value)

    evidence: list[RecommendationEvidence] = []

    for item in source_data.get("evidence") or []:
        if not isinstance(item, dict):
            continue

        evidence.append(
            RecommendationEvidence(
                statement=str(
                    item.get("statement") or ""
                ),
                source=item.get("source"),
                reference_id=item.get("reference_id"),
                strength=float(
                    item.get("strength") or 0.5
                ),
                metadata=dict(
                    item.get("metadata") or {}
                ),
            )
        )

    recommendation_id = (
        source_data.get("director_recommendation_id")
        or f"rec_{row.get('id')}"
    )

    return DirectorRecommendation(
        recommendation_id=str(recommendation_id),
        title=str(row.get("title") or ""),
        summary=str(
            row.get("description")
            or source_data.get("summary")
            or ""
        ),
        status=status,
        target=target,
        proposed_action=str(
            row.get("suggested_action") or ""
        ),
        reason=str(row.get("rationale") or ""),
        confidence=float(row.get("confidence") or 0.0),
        evidence=evidence,
        risks=list(
            source_data.get("risks") or []
        ),
        constraints=list(
            source_data.get("constraints") or []
        ),
        decision_id=source_data.get("decision_id"),
        research_id=source_data.get("research_id"),
        created_at=str(row.get("created_at") or ""),
        metadata=dict(row.get("metadata") or {}),
    )


class ServerMemory:
    """
    Thin integration layer between server.py and Memory 2.0.

    server.py should not know Supabase/table details, and it should not
    use the removed Memory 1.0 method names.
    """

    def __init__(self) -> None:
        self.backend = None
        self.memory = None

        if Memory is None:
            logger.warning("Memory module unavailable")
            return

        try:
            self.backend = self._create_backend()

            if self.backend is None:
                logger.warning(
                    "No memory backend configured; "
                    "memory is disabled"
                )
                return

            self.memory = Memory(
                backend=self.backend,
            )

            logger.info(
                "Director memory initialized"
            )

        except Exception:
            logger.exception(
                "Failed to initialize memory"
            )
            self.backend = None
            self.memory = None

    @staticmethod
    def _create_backend() -> Any:
        """
        Pick the storage backend.

        - Supabase is used when credentials are configured.
        - In FREE_MODE (or explicit MEMORY_BACKEND=memory) the
          process-local InMemoryMemoryBackend keeps the engine fully
          runnable without external services.
        - Otherwise memory is disabled.
        """
        backend_choice = (
            os.getenv("MEMORY_BACKEND", "")
            .strip()
            .lower()
        )

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")

        if supabase_url and supabase_key:
            if SupabaseMemoryBackend is not None:
                logger.info(
                    "Using Supabase memory backend"
                )
                return SupabaseMemoryBackend()

            logger.error(
                "Supabase memory backend is unavailable"
            )
            return None

        use_inmemory = (
            backend_choice == "memory"
            or (FREE_MODE and backend_choice != "supabase")
        )

        if use_inmemory:
            if InMemoryMemoryBackend is not None:
                logger.info(
                    "Using in-memory memory backend "
                    "(FREE_MODE)"
                )
                return InMemoryMemoryBackend()

            logger.error(
                "In-memory memory backend is unavailable"
            )
            return None

        return None

    @property
    def enabled(self) -> bool:
        return self.memory is not None

    def _normalize_recommendation_ids(
        self,
        context: dict[str, Any],
    ) -> None:
        """
        Expose a stable recommendation_id on rows returned by Memory,
        preferring the persistent Director recommendation id stored in
        source_data.
        """
        for row in context.get("recommendations") or []:
            if not isinstance(row, dict):
                continue

            source_data = row.get("source_data")

            if not isinstance(source_data, dict):
                source_data = {}

            director_id = source_data.get(
                "director_recommendation_id"
            )

            row["recommendation_id"] = (
                director_id
                or row.get("recommendation_id")
                or row.get("id")
            )

    async def get_context(
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
        if not self.memory:
            return {}

        try:
            result = self.memory.get_context(
                project_id=project_id,
                limit_runs=limit_runs,
                limit_decisions=limit_decisions,
                limit_events=limit_events,
                limit_chat=limit_chat,
                limit_actions=limit_actions,
                limit_results=limit_results,
                limit_recommendations=limit_recommendations,
                limit_constraints=limit_constraints,
            )

            if hasattr(result, "__await__"):
                result = await result

            if not isinstance(result, dict):
                return {}

            self._normalize_recommendation_ids(result)

            return result

        except Exception:
            logger.exception("Memory get_context failed")
            return {}

    async def save_run(
        self,
        project_id: str,
        run: dict[str, Any],
    ) -> Any:
        if not self.memory:
            return None

        try:
            payload = (
                dict(run)
                if isinstance(run, dict)
                else serialize(run)
            )

            if not isinstance(payload, dict):
                payload = {}

            data = dict(payload)
            data["project_id"] = project_id

            result = self.memory.save_run(
                language=payload.get("language"),
                region_code=payload.get(
                    "region_code"
                ),
                data=data,
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        except Exception:
            logger.exception("Memory save_run failed")
            return None

    async def create_run(self, project_id: str, run: dict[str, Any]) -> int:
        if not self.memory or not self.backend:
            raise RuntimeError("Director run storage is unavailable")

        # Read all runs for this project, not just the newest 100 globally:
        # an older active row may still own the partial unique index.
        now = datetime.now(timezone.utc)
        stale_timeout = max(
            60, int(os.getenv("DIRECTOR_RUN_STALE_TIMEOUT_SECONDS", "1800"))
        )
        try:
            if hasattr(self.backend, "_recent_for_project"):
                old_runs = self.backend._recent_for_project(
                    self.backend.TABLE_RUNS,
                    limit=None,
                    project_id=project_id,
                    order_key="created_at",
                )
            else:
                old_runs = self.backend.get_recent_runs(
                    limit=100000, project_id=project_id
                )
        except TypeError:
            old_runs = self.backend.get_recent_runs(limit=100000)
        except Exception:
            logger.exception("Could not inspect active Director runs for project=%s", project_id)
            raise

        active_runs: list[dict[str, Any]] = []
        for old_run in old_runs:
            if not isinstance(old_run, dict):
                continue
            old_data = old_run.get("data_json") if isinstance(old_run.get("data_json"), dict) else {}
            old_project = old_run.get("project_id") or old_data.get("project_id")
            old_status = str(old_run.get("status") or old_data.get("status") or "").lower()
            if str(old_project) != str(project_id) or old_status not in {"requested", "running"}:
                continue

            stamp = (
                old_run.get("updated_at")
                or old_data.get("updated_at")
                or old_run.get("started_at")
                or old_data.get("started_at")
                or old_run.get("created_at")
                or old_data.get("created_at")
            )
            if not stamp:
                # Missing heartbeat is not proof of a stale process. Keep the
                # active guard and require operator review rather than overlap.
                active_runs.append(old_run)
                continue
            try:
                parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                active_runs.append(old_run)
                continue

            age_seconds = (now - parsed).total_seconds()
            old_run_id = old_run.get("id")
            if age_seconds > stale_timeout and old_run_id is not None:
                reason = (
                    f"Stale run timed out after {stale_timeout}s without heartbeat; "
                    f"last update was {parsed.isoformat()} (age={int(age_seconds)}s)."
                )
                await self.update_run(
                    int(old_run_id),
                    project_id=project_id,
                    fields={
                        "status": "failed",
                        "finished_at": utc_now(),
                        "current_step": "stale_timeout",
                        "error_message": reason,
                    },
                )
            else:
                active_runs.append(old_run)

        if active_runs:
            active = active_runs[0]
            active_id = active.get("id", "unknown")
            active_step = active.get("current_step") or "unknown"
            raise DirectorCycleAlreadyRunning(
                f"Project {project_id!r} already has active Director run "
                f"{active_id} (status={active.get('status', 'running')}, step={active_step})."
            )

        payload = dict(run)
        payload["project_id"] = project_id
        try:
            result = self.backend.save_run(
                language=payload.get("language"),
                region_code=payload.get("region_code"),
                data=payload,
            )
            if hasattr(result, "__await__"):
                result = await result
        except Exception as exc:
            # The database partial unique index is the cross-process guard.
            # Translate its race winner into a conflict, never blind-retry it.
            message = str(exc).lower()
            if "unique" in message or "duplicate key" in message or "23505" in message:
                raise DirectorCycleAlreadyRunning(
                    f"Project {project_id!r} already has an active Director run; "
                    "the database uniqueness guard rejected this start."
                ) from exc
            raise
        if result is None:
            raise RuntimeError("Director run insert returned no id")
        return int(result)

    async def update_run(self, run_id: int, *, project_id: str, fields: dict[str, Any]) -> bool:
        if not self.memory:
            raise RuntimeError("Director run storage is unavailable")
        payload = dict(fields)
        payload["project_id"] = project_id
        payload["updated_at"] = utc_now()
        result = self.memory.update_run(run_id=run_id, data=payload)
        if hasattr(result, "__await__"):
            result = await result
        if result is not True:
            raise RuntimeError(f"Director run {run_id} update affected no row")
        return True

    async def save_decision(
        self,
        project_id: str,
        decision: Any,
        *,
        run_id: int | None = None,
    ) -> Any:
        if not self.memory:
            return None

        try:
            record = _decision_to_memory_payload(
                decision,
                project_id=project_id,
            )

            if run_id is not None:
                record["run_id"] = run_id

            if not record:
                return None

            result = self.memory.save_decision(
                decision=str(
                    record.get("decision", "")
                ),
                data={
                    key: value
                    for key, value in record.items()
                    if key != "decision"
                },
                run_id=run_id,
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        except Exception:
            logger.exception(
                "Memory save_decision failed"
            )
            return None

    async def save_recommendation(
        self,
        project_id: str,
        recommendation: Any,
        *,
        decision_db_id: int | None = None,
        run_id: int | None = None,
    ) -> Any:
        if not self.memory:
            return None

        try:
            record = _recommendation_to_memory_payload(
                recommendation,
                project_id=project_id,
                decision_db_id=decision_db_id,
            )

            if run_id is not None:                record["run_id"] = run_id
            if (
                not record.get("title")
                or not record.get("description")
            ):
                logger.warning(
                    "Skipping empty recommendation"
                )
                return None

            result = self.memory.save_recommendation(
                record
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        except Exception:
            logger.exception(
                "Memory save_recommendation failed"
            )
            return None

    async def apply_recommendation_feedback(
        self,
        project_id: str,
        feedback: Any,
    ) -> Any:
        if not self.memory:
            return None

        try:
            record = _feedback_to_memory_payload(
                feedback,
                project_id=project_id,
            )

            result = (
                self.memory.apply_recommendation_feedback(
                    record
                )
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        except Exception:
            logger.exception(
                "Memory apply_recommendation_feedback "
                "failed"
            )
            return None

    async def save_result(
        self,
        project_id: str,
        result: Any,
        *,
        run_id: int | None = None,
        decision_db_id: int | None = None,
        recommendation_db_id: int | None = None,
    ) -> Any:
        if not self.memory:
            return None

        try:
            payload = serialize(result)

            if not isinstance(payload, dict):
                payload = {"value": payload}

            result_type = str(
                payload.get("type")
                or payload.get("result_type")
                or "director_result"
            ).strip()

            summary = str(
                payload.get("summary")
                or payload.get("message")
                or ""
            ).strip()

            data = dict(payload)
            data["project_id"] = project_id

            if decision_db_id is not None:
                data["decision_db_id"] = decision_db_id

            if recommendation_db_id is not None:
                data["recommendation_db_id"] = recommendation_db_id

            effective_run_id = (
                run_id
                if run_id is not None
                else payload.get("run_id")
            )

            saved = self.memory.save_result(
                result_type=result_type,
                summary=summary,
                action_id=payload.get("action_id"),
                run_id=effective_run_id,
                data=data,
            )

            if hasattr(saved, "__await__"):
                saved = await saved

            return saved

        except Exception:
            logger.exception(
                "Memory save_result failed"
            )
            return None

    async def save_chat_message(
        self,
        project_id: str,
        role: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> Any:
        if not self.memory:
            return None

        try:
            payload = dict(data or {})
            payload["project_id"] = project_id

            result = self.memory.save_chat_message(
                role=role,
                message=message,
                data=payload,
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        except Exception:
            logger.exception(
                "Memory save_chat_message failed"
            )
            return None

    async def save_event(
        self,
        project_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> Any:
        if not self.memory:
            return None

        try:
            payload = dict(data or {})
            payload["project_id"] = project_id
            payload.setdefault("correlation_id", get_correlation_id())

            result = self.memory.save_event(
                event_type=event_type,
                data=payload,
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        except Exception:
            logger.exception(
                "Memory save_event failed"
            )
            return None

    async def save_constraint(
        self,
        project_id: str,
        constraint: Any,
    ) -> Any:
        if not self.memory:
            return None

        try:
            record = (
                dict(constraint)
                if isinstance(constraint, dict)
                else serialize(constraint)
            )

            if not isinstance(record, dict):
                return None

            metadata = record.get("metadata")

            if not isinstance(metadata, dict):
                metadata = {}

            metadata["project_id"] = project_id
            record["metadata"] = metadata

            result = self.memory.save_constraint(
                record
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        except Exception:
            logger.exception(
                "Memory save_constraint failed"
            )
            return None


# ---------------------------------------------------------------------------
