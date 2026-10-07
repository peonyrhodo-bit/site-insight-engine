
"""
AI Director HTTP server.

The server is an integration layer between:
    USER / external API
        ↓
    Director
        ↓
    Research / Analytics / AI / Memory / Data
        ↓
    youtube-mcp

The server itself does not make strategic decisions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
)

logger = logging.getLogger("site-insight-engine")


# ---------------------------------------------------------------------------
# Optional environment / compatibility helpers
# ---------------------------------------------------------------------------

SERVICE_NAME = os.getenv(
    "SERVICE_NAME",
    "site-insight-engine",
)

ENVIRONMENT = os.getenv(
    "ENVIRONMENT",
    "production",
)

FREE_MODE = (
    os.getenv("FREE_MODE", "true").lower()
    in {"1", "true", "yes", "on"}
)

AUTONOMOUS_ENABLED = (
    os.getenv("AUTONOMOUS_ENABLED", "false").lower()
    in {"1", "true", "yes", "on"}
)

AUTONOMOUS_POLL_INTERVAL_SECONDS = max(
    1,
    int(os.getenv("AUTONOMOUS_POLL_INTERVAL_SECONDS", "5")),
)

AUTONOMOUS_WAKE_INTERVAL_SECONDS = max(
    1,
    int(os.getenv("AUTONOMOUS_WAKE_INTERVAL_SECONDS", "3600")),
)

DEFAULT_PROJECT_ID = os.getenv(
    "DEFAULT_PROJECT_ID",
    "default",
)

DEFAULT_REGION_CODE = os.getenv(
    "DEFAULT_REGION_CODE",
    "US",
)


# ---------------------------------------------------------------------------
# Imports from project modules
# ---------------------------------------------------------------------------

try:
    from director.director import (
        Director,
        DirectorContext,
        DirectorMode,
        create_director,
    )
except Exception as exc:
    logger.exception("Failed to import Director")
    raise RuntimeError("Director module is unavailable") from exc


try:
    from director.autonomy import (
        AutonomyConfig,
        DirectorAutonomy,
    )
except Exception:
    AutonomyConfig = None
    DirectorAutonomy = None


try:
    from director.chat import (
        ChatResult,
        execute_chat_command,
        parse_chat_command,
    )
except Exception:
    ChatResult = None
    execute_chat_command = None
    parse_chat_command = None


try:
    from director.feedback import (
        FeedbackScope,
        FeedbackType,
        create_feedback,
    )
except Exception:
    FeedbackScope = None
    FeedbackType = None
    create_feedback = None


try:
    from director.recommendations import (
        RecommendationStatus,
        accept_recommendation,
        discuss_recommendation,
        reject_recommendation,
    )
except Exception:
    RecommendationStatus = None
    accept_recommendation = None
    discuss_recommendation = None
    reject_recommendation = None


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


try:
    from ai.provider import create_ai_provider
except Exception:
    create_ai_provider = None


# Analytics imports are intentionally modular.
try:
    from analytics.analytics import (
        analyze_research,
        prepare_for_director as analytics_prepare_for_director,
    )
except Exception:
    analyze_research = None
    analytics_prepare_for_director = None


try:
    from analytics.opportunity import (
        assess_opportunity,
        prepare_for_director as opportunity_prepare_for_director,
    )
except Exception:
    assess_opportunity = None
    opportunity_prepare_for_director = None


try:
    from analytics.topics import (
        analyze_topics,
        prepare_for_director as topics_prepare_for_director,
    )
except Exception:
    analyze_topics = None
    topics_prepare_for_director = None


try:
    from analytics.trends import (
        analyze_trend,
        prepare_for_director as trends_prepare_for_director,
    )
except Exception:
    analyze_trend = None
    trends_prepare_for_director = None


# DATA layer
try:
    from data.youtube import YouTubeDataRegistry
except Exception:
    YouTubeDataRegistry = None


try:
    from data.research_sets import ResearchSetManager
except Exception:
    ResearchSetManager = None


try:
    from data.relations import DataRelations
except Exception:
    DataRelations = None


try:
    from data.opportunity_registry import OpportunityDataRegistry
except Exception:
    OpportunityDataRegistry = None


# Scheduler
try:
    from scheduler.scheduler import create_scheduler
except Exception:
    create_scheduler = None


try:
    from scheduler.wakeup import create_wakeup_manager
except Exception:
    create_wakeup_manager = None


try:
    from scheduler.jobs import JobRunner
except Exception:
    JobRunner = None


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Generic serialization
# ---------------------------------------------------------------------------


def serialize(value: Any) -> Any:
    """
    Convert project objects/enums/dataclasses into JSON-safe values.
    """

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {
            str(key): serialize(item)
            for key, item in value.items()
        }

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


# ---------------------------------------------------------------------------
# Safe async/sync invocation
# ---------------------------------------------------------------------------


async def call_maybe_async(function: Any, *args: Any, **kwargs: Any) -> Any:
    """
    Call a synchronous or asynchronous function.
    """

    result = function(*args, **kwargs)

    if hasattr(result, "__await__"):
        return await result

    return result


# ---------------------------------------------------------------------------
# Memory adapter
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
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
            "topic": (
                str(target.get("title"))
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

            if run_id is not None:
                record["run_id"] = run_id

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
# Analytics adapter
# ---------------------------------------------------------------------------


class AnalyticsAdapter:
    """
    Adapter over modular Analytics.

    Analytics calculates.
    Director interprets and decides.
    """

    async def analyze(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        observations = context.get(
            "observations",
            [],
        )

        previous = context.get(
            "previous_observations",
            [],
        )

        analytics_data: dict[str, Any] = {}

        # ---------------------------------------------------------------
        # Basic analytics
        # ---------------------------------------------------------------

        if analytics_prepare_for_director is not None:
            try:
                research_analysis = analyze_research(
                    observations,
                    previous_videos=(
                        previous or None
                    ),
                )

                prepared = analytics_prepare_for_director(
                    research_analysis,
                )

                if prepared is not None:
                    analytics_data["analytics"] = serialize(
                        prepared
                    )

                # Keep the raw analytical payload too: opportunity
                # assessment expects the "metrics" structure produced
                # by analyze_research().
                from dataclasses import asdict

                analytics_data["analytics_raw"] = serialize(
                    asdict(research_analysis)
                )

            except TypeError:
                # Some versions expect a different argument shape.
                logger.debug(
                    "analytics_prepare_for_director "
                    "signature mismatch",
                    exc_info=True,
                )

            except Exception:
                logger.exception(
                    "Analytics preparation failed"
                )

        # ---------------------------------------------------------------
        # Topics
        # ---------------------------------------------------------------

        if analyze_topics is not None:
            try:
                topic_analysis = analyze_topics(
                    observations,
                )

                analytics_data["topics"] = serialize(
                    (
                        topics_prepare_for_director(topic_analysis)
                        if topics_prepare_for_director
                        else topic_analysis
                    )
                )

            except Exception:
                logger.exception(
                    "Topic analysis failed"
                )

        # ---------------------------------------------------------------
        # Trends
        # ---------------------------------------------------------------

        if analyze_trend is not None and (
            observations or previous
        ):
            try:
                trend_analysis = analyze_trend(
                    current=observations,
                    previous=previous,
                )

                analytics_data["trends"] = serialize(
                    (
                        trends_prepare_for_director(
                            trend_analysis
                        )
                        if trends_prepare_for_director
                        else trend_analysis
                    )
                )

            except TypeError:
                logger.debug(
                    "Trend analyzer signature mismatch",
                    exc_info=True,
                )

            except Exception:
                logger.exception(
                    "Trend analysis failed"
                )

        # ---------------------------------------------------------------
        # Opportunity
        # ---------------------------------------------------------------

        if assess_opportunity is not None:
            try:
                opportunities = []

                topic_items = analytics_data.get(
                    "topics",
                    [],
                )

                if isinstance(topic_items, dict):
                    topic_items = topic_items.get(
                        "topics",
                        topic_items.get(
                            "items",
                            [],
                        ),
                    )

                if not topic_items:
                    topic_items = observations

                trend_payload = (
                    analytics_data.get(
                        "trends",
                        {},
                    )
                    if isinstance(
                        analytics_data.get(
                            "trends",
                            {},
                        ),
                        dict,
                    )
                    else {}
                )

                analytics_payload = (
                    analytics_data.get(
                        "analytics_raw",
                        analytics_data.get(
                            "analytics",
                            {},
                        ),
                    )
                    if isinstance(
                        analytics_data.get(
                            "analytics_raw",
                            analytics_data.get(
                                "analytics",
                                {},
                            ),
                        ),
                        dict,
                    )
                    else {}
                )

                raw_constraints = context.get(
                    "constraints",
                    [],
                )

                constraint_texts: list[str] = []

                for item in raw_constraints or []:
                    if isinstance(item, str):
                        constraint_texts.append(
                            item
                        )
                    elif isinstance(item, dict):
                        value = (
                            item.get("value")
                            or item.get("description")
                            or item.get("title")
                        )

                        if value:
                            constraint_texts.append(
                                str(value)
                            )

                for item in topic_items or []:
                    if not isinstance(item, dict):
                        continue

                    title = (
                        item.get("name")
                        or item.get("title")
                        or item.get("topic")
                        or "Перспективное направление"
                    )

                    try:
                        opportunity = assess_opportunity(
                            opportunity_id=item.get(
                                "topic_id",
                                item.get("id"),
                            ),
                            title=str(title),
                            description=str(
                                item.get("description", "")
                            ),
                            analytics=analytics_payload,
                            trend=(
                                item.get("trend")
                                if isinstance(
                                    item.get("trend"),
                                    dict,
                                )
                                else trend_payload
                            ),
                            videos=observations,
                            constraints=(
                                constraint_texts
                                or None
                            ),
                            metadata={
                                "source": "topic_items",
                            },
                        )

                        prepared = (
                            opportunity_prepare_for_director(
                                opportunity
                            )
                            if opportunity_prepare_for_director
                            else opportunity
                        )

                        opportunities.append(
                            serialize(prepared)
                        )

                    except Exception:
                        logger.debug(
                            "Opportunity assessment failed "
                            "for item",
                            exc_info=True,
                        )

                analytics_data["opportunities"] = (
                    opportunities
                )

            except Exception:
                logger.exception(
                    "Opportunity analysis failed"
                )

        return analytics_data


# ---------------------------------------------------------------------------
# Data adapter
# ---------------------------------------------------------------------------


class DataAdapter:
    """
    DATA layer adapter.

    This class does not decide strategy.
    """

    def __init__(
        self,
        *,
        storage: Any = None,
    ) -> None:
        self.storage = storage
        self.youtube_registry = None
        self.research_manager = None
        self.relations = None
        self.opportunity_registry = None

        try:
            if YouTubeDataRegistry is not None:
                self.youtube_registry = (
                    YouTubeDataRegistry()
                )
        except Exception:
            logger.exception(
                "Failed to initialize YouTubeDataRegistry"
            )

        try:
            if ResearchSetManager is not None:
                self.research_manager = (
                    ResearchSetManager()
                )
        except Exception:
            logger.exception(
                "Failed to initialize ResearchSetManager"
            )

        try:
            if DataRelations is not None:
                self.relations = DataRelations(
                    youtube_registry=self.youtube_registry,
                    research_manager=self.research_manager,
                )
        except Exception:
            logger.exception(
                "Failed to initialize DataRelations"
            )


        try:
            if OpportunityDataRegistry is not None:
                self.opportunity_registry = OpportunityDataRegistry()
        except Exception:
            logger.exception(
                "Failed to initialize OpportunityDataRegistry"
            )

    async def get_project_state(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        """
        Return whatever structured DATA state is available.

        The DATA layer remains deliberately conservative here.
        """

        result: dict[str, Any] = {
            "project_id": project_id,
            "observations": [],
            "research_sets": [],
            "relations": [],
            "channels": [],
            "channel_snapshots": [],
            "niches": [],
            "niche_snapshots": [],
            "data_inventory": {
                "video_count": 0,
                "snapshot_count": 0,
                "query_count": 0,
                "research_set_count": 0,
                "relation_count": 0,
                "channel_count": 0,
                "channel_snapshot_count": 0,
                "niche_count": 0,
                "niche_snapshot_count": 0,
            },
        }

        if self.youtube_registry is not None:
            try:
                loader = getattr(
                    self.storage,
                    "load_youtube_data",
                    None,
                )

                if callable(loader):
                    persisted = loader(
                        project_id=project_id,
                    )

                    if isinstance(persisted, dict):
                        loaded_registry = (
                            YouTubeDataRegistry.from_dict(
                                persisted
                            )
                        )

                        self.youtube_registry.clear()

                        for query in loaded_registry.queries():
                            self.youtube_registry.add_query(query)

                        for video in loaded_registry.videos():
                            self.youtube_registry.add_video(video)

                        for snapshot in loaded_registry.snapshots():
                            self.youtube_registry.add_snapshot(snapshot)

                # Channel/niche DATA has its own persistence contour.
                opportunity_loader = getattr(
                    self.storage,
                    "load_opportunity_data",
                    None,
                )
                if callable(opportunity_loader) and self.opportunity_registry is not None:
                    persisted_opportunity = opportunity_loader(project_id=project_id)
                    if isinstance(persisted_opportunity, dict):
                        from data.opportunity_registry import OpportunityDataRegistry
                        self.opportunity_registry = OpportunityDataRegistry.from_dict(persisted_opportunity)

                # Research/query/relation DATA has its own persistence
                # contour. Load it through Memory storage, then expose it
                # to Director as ordinary DATA objects.
                research_loader = getattr(
                    self.storage,
                    "load_research_data",
                    None,
                )

                if callable(research_loader):
                    persisted_research = research_loader(
                        project_id=project_id,
                    )

                    if isinstance(persisted_research, dict):
                        queries = persisted_research.get("queries") or []
                        for row in queries:
                            if not isinstance(row, dict):
                                continue
                            try:
                                from data.youtube import YouTubeQuery
                                self.youtube_registry.add_query(
                                    YouTubeQuery.from_dict(row)
                                )
                            except Exception:
                                logger.exception(
                                    "Failed to restore YouTube query"
                                )

                        if self.research_manager is not None:
                            from data.research_sets import ResearchSet
                            self.research_manager.clear()
                            for row in persisted_research.get("research_sets") or []:
                                if isinstance(row, dict):
                                    try:
                                        self.research_manager.add(
                                            ResearchSet.from_dict(row)
                                        )
                                    except Exception:
                                        logger.exception(
                                            "Failed to restore research set"
                                        )

                        if self.relations is not None:
                            from data.relations import DataRelation
                            self.relations.clear()
                            for row in persisted_research.get("relations") or []:
                                if isinstance(row, dict):
                                    try:
                                        self.relations.add_relation(
                                            DataRelation.from_dict(row)
                                        )
                                    except Exception:
                                        logger.exception(
                                            "Failed to restore data relation"
                                        )

                if hasattr(
                    self.youtube_registry,
                    "videos",
                ):
                    videos = (
                        self.youtube_registry.videos()
                    )

                    observations: list[Any] = []

                    for video in videos:
                        observation = (
                            video.to_dict()
                            if hasattr(
                                video,
                                "to_dict",
                            )
                            else serialize(video)
                        )

                        if not isinstance(
                            observation,
                            dict,
                        ):
                            continue

                        # Lift stable video metadata (topics etc.) to
                        # the top level so analytics can read it.
                        video_metadata = (
                            observation.get(
                                "metadata",
                                {},
                            )
                            if isinstance(
                                observation.get(
                                    "metadata",
                                    {},
                                ),
                                dict,
                            )
                            else {}
                        )

                        for meta_key, meta_value in (
                            video_metadata.items()
                        ):
                            observation.setdefault(
                                meta_key,
                                meta_value,
                            )

                        # Enrich with the latest snapshot metrics so the
                        # analytics layer receives numeric observations.
                        snapshot = None

                        if hasattr(
                            self.youtube_registry,
                            "latest_snapshot",
                        ):
                            try:
                                snapshot = (
                                    self.youtube_registry
                                    .latest_snapshot(
                                        video_id=(
                                            getattr(
                                                video,
                                                "video_id",
                                                None,
                                            )
                                        )
                                    )
                                )
                            except Exception:
                                snapshot = None

                        if snapshot is not None:
                            metrics = (
                                snapshot.metrics
                                if hasattr(
                                    snapshot,
                                    "metrics",
                                )
                                else (
                                    snapshot.get(
                                        "metrics",
                                        {},
                                    )
                                    if isinstance(
                                        snapshot,
                                        dict,
                                    )
                                    else {}
                                )
                            )

                            if isinstance(
                                metrics,
                                dict,
                            ):
                                for key, value in (
                                    metrics.items()
                                ):
                                    observation.setdefault(
                                        key,
                                        value,
                                    )

                        observations.append(
                            observation
                        )

                    result["observations"] = (
                        observations
                    )

                    # Expose DATA inventory explicitly so Director can
                    # distinguish "no data" from "data exists but has not
                    # been analyzed yet".
                    try:
                        result["data_inventory"] = {
                            "video_count": len(
                                self.youtube_registry.videos()
                            ),
                            "snapshot_count": len(
                                self.youtube_registry.snapshots()
                            ),
                            "query_count": len(
                                self.youtube_registry.queries()
                            ),
                            "research_set_count": len(self.research_manager.all()) if self.research_manager is not None and hasattr(self.research_manager, "all") else 0,
                            "relation_count": len(self.relations.all()) if self.relations is not None and hasattr(self.relations, "all") else 0,
                            "channel_count": self.opportunity_registry.counts().get("channels", 0) if self.opportunity_registry is not None else 0,
                            "channel_snapshot_count": self.opportunity_registry.counts().get("channel_snapshots", 0) if self.opportunity_registry is not None else 0,
                            "niche_count": self.opportunity_registry.counts().get("niches", 0) if self.opportunity_registry is not None else 0,
                            "niche_snapshot_count": self.opportunity_registry.counts().get("niche_snapshots", 0) if self.opportunity_registry is not None else 0,
                        }
                    except Exception:
                        result["data_inventory"] = {
                            "video_count": len(observations),
                            "snapshot_count": 0,
                            "query_count": 0,
                        }
            except Exception:
                logger.exception(
                    "Failed to load youtube observations"
                )

        if self.research_manager is not None:
            try:
                if hasattr(
                    self.research_manager,
                    "all",
                ):
                    research_sets = (
                        self.research_manager.all()
                    )

                    result["research_sets"] = serialize(
                        research_sets
                    )
            except Exception:
                logger.exception(
                    "Failed to load research sets"
                )

        if self.opportunity_registry is not None:
            try:
                saver = getattr(self.storage, "save_opportunity_data", None)
                if callable(saver):
                    result["persistence"] = result.get("persistence", {})
                    result["persistence"]["opportunity"] = saver(
                        project_id=project_id,
                        data=self.opportunity_registry.to_dict(),
                    )
            except Exception:
                logger.exception("Failed to persist opportunity DATA")

        if self.relations is not None:
            try:
                if hasattr(
                    self.relations,
                    "all",
                ):
                    result["relations"] = serialize(
                        self.relations.all()
                    )
            except Exception:
                logger.exception(
                    "Failed to load data relations"
                )

        # Persist the complete in-memory research graph after it has been
        # assembled. Upserts make this idempotent, so repeated state reads
        # do not create duplicate DATA records.
        saver = getattr(
            self.storage,
            "save_research_data",
            None,
        )
        if callable(saver):
            try:
                query_payload = [
                    query.to_dict()
                    for query in self.youtube_registry.queries()
                ] if self.youtube_registry is not None else []
                research_payload = [
                    research.to_dict()
                    for research in self.research_manager.all()
                ] if self.research_manager is not None else []
                relation_payload = [
                    relation.to_dict()
                    for relation in self.relations.all()
                ] if self.relations is not None else []
                persistence = saver(
                    project_id=project_id,
                    queries=query_payload,
                    research_sets=research_payload,
                    relations=relation_payload,
                )
                existing_persistence = result.get("persistence")
                if isinstance(existing_persistence, dict) and isinstance(persistence, dict):
                    existing_persistence.update(persistence)
                    result["persistence"] = existing_persistence
                else:
                    result["persistence"] = persistence
            except Exception:
                logger.exception(
                    "Failed to persist research DATA"
                )

        return result


# ---------------------------------------------------------------------------
# AI adapter
# ---------------------------------------------------------------------------


class AIAdapter:
    """
    AI integration layer.

    AI provides reasoning assistance.
    Director owns decisions.
    """

    def __init__(self) -> None:
        self.provider = None

        if create_ai_provider is None:
            return

        # In FREE_MODE without an API key there is no AI backend to
        # call; disable the provider cleanly instead of failing later.
        api_key = (
            os.getenv("OPENROUTER_API_KEY")
            or os.getenv("DIRECTOR_AI_KEY")
        )

        if FREE_MODE and not api_key:
            logger.info(
                "FREE_MODE: AI provider disabled "
                "(no API key configured)"
            )
            return

        try:
            self.provider = create_ai_provider()
            logger.info("AI provider initialized")
        except Exception:
            logger.exception(
                "AI provider unavailable"
            )
            self.provider = None

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    async def generate_decision(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Provide structured AI reasoning for a Director decision.

        Director remains the decision owner: AI only receives a
        structured context and returns structured JSON.
        """

        if not self.provider:
            return {}

        try:
            from ai.provider import AIMessage
            from ai.prompts import (
                build_decision_prompt,
                get_system_prompt,
            )

            prompt = build_decision_prompt(
                context=context,
            )

            messages = [
                AIMessage(
                    role="system",
                    content=get_system_prompt(),
                ),
                AIMessage(
                    role="user",
                    content=prompt,
                ),
            ]

            response = await self.provider.generate_json(
                messages=messages,
            )

            if isinstance(response, dict):
                return response

            if hasattr(response, "content"):
                content = response.content

                if isinstance(content, dict):
                    return content

                try:
                    return json.loads(content)
                except Exception:
                    return {}

        except Exception:
            logger.exception(
                "AI decision generation failed"
            )

        return {}


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class Runtime:
    """
    Application-wide runtime dependencies.
    """

    def __init__(self) -> None:
        self.memory = ServerMemory()
        self.analytics = AnalyticsAdapter()
        self.data = DataAdapter(
            storage=self.memory.backend,
        )
        self.ai = AIAdapter()

        self.scheduler = (
            create_scheduler(
                enabled=AUTONOMOUS_ENABLED,
                project_id=DEFAULT_PROJECT_ID,
            )
            if create_scheduler
            else None
        )

        self.wakeup = (
            create_wakeup_manager(
                enabled=AUTONOMOUS_ENABLED,
            )
            if create_wakeup_manager
            else None
        )

        self.jobs = (
            JobRunner(
                enabled=AUTONOMOUS_ENABLED,
            )
            if JobRunner
            else None
        )

        self.directors: dict[str, Director] = {}

        # The scheduler/wakeup objects are deliberately kept in Runtime so
        # the background bridge can drive them without putting timing logic
        # into Director itself.
        self.autonomous_worker: asyncio.Task | None = None

    def get_director(
        self,
        project_id: str,
        mode: DirectorMode | None = None,
    ) -> Director:
        existing = self.directors.get(project_id)

        if existing is not None:
            return existing

        if mode is None:
            mode = (
                DirectorMode.AUTONOMOUS
                if AUTONOMOUS_ENABLED
                else DirectorMode.ASSISTED
            )

        director = create_director(
            project_id=project_id,
            mode=mode,
            memory_service=self.memory,
            analytics_service=self.analytics,
            ai_service=self.ai,
            data_service=self.data,
        )

        self.directors[project_id] = director

        return director


runtime = Runtime()


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class DirectorRunRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    objective: str | None = None
    language: str = "en"
    region_code: str = DEFAULT_REGION_CODE
    hours_back: int = Field(
        default=72,
        ge=1,
        le=24 * 30,
    )
    max_results: int = Field(
        default=25,
        ge=1,
        le=100,
    )


class DirectorChatRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    message: str


class FeedbackRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    feedback_type: str
    scope: str = "recommendation"
    message: str
    recommendation_id: str | None = None
    decision_id: str | None = None
    target: str | None = None
    reason: str | None = None
    constraint: str | None = None
    preference: str | None = None


class RecommendationActionRequest(BaseModel):
    action: str
    message: str | None = None


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


app = FastAPI(
    title="AI Director",
    version="2.0",
    description=(
        "AI Director for YouTube research, analysis and "
        "strategic recommendations."
    ),
)


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the repository frontend from the same FastAPI process."""
    return FileResponse("index.html", media_type="text/html")


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


cors_origins = os.getenv(
    "CORS_ORIGINS",
    "*",
)

if cors_origins == "*":
    allow_origins = ["*"]
else:
    allow_origins = [
        origin.strip()
        for origin in cors_origins.split(",")
        if origin.strip()
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def request_logging(
    request: Request,
    call_next: Any,
) -> JSONResponse:
    started = datetime.now(timezone.utc)

    try:
        response = await call_next(request)
        return response

    finally:
        elapsed = (
            datetime.now(timezone.utc) - started
        ).total_seconds()

        logger.info(
            "%s %s %.3fs",
            request.method,
            request.url.path,
            elapsed,
        )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    """
    Infrastructure health endpoint.

    Must remain lightweight and must not execute Director logic.
    """

    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS_ENABLED,
        "ai_enabled": runtime.ai.enabled,
        "ai_provider": (
            os.getenv(
                "AI_PROVIDER",
                os.getenv(
                    "OPENROUTER_PROVIDER",
                    "openrouter",
                ),
            )
            if runtime.ai.enabled
            else None
        ),
        "supabase_enabled": runtime.memory.enabled,
        "director_memory": (
            "supabase"
            if runtime.memory.enabled
            else "disabled"
        ),
        "timestamp": utc_now(),
    }


# ---------------------------------------------------------------------------
# Director status
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# System / AI status compatibility endpoints
# ---------------------------------------------------------------------------

@app.get("/system/status")
async def system_status() -> dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS_ENABLED,
        "memory_enabled": runtime.memory.enabled,
        "mcp_url": os.getenv("YOUTUBE_MCP_URL") or os.getenv("MCP_URL") or "",
        "timestamp": utc_now(),
    }

@app.get("/ai/status")
async def ai_status() -> dict[str, Any]:
    return {
        "enabled": runtime.ai.enabled,
        "provider": (os.getenv("AI_PROVIDER") or os.getenv("OPENROUTER_PROVIDER") or "openrouter") if runtime.ai.enabled else None,
    }


@app.get("/director/status")
async def director_status(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    director = runtime.get_director(
        project_id=project_id,
    )

    try:
        result = director.status()
        return serialize(result)

    except Exception:
        logger.exception(
            "Director status failed"
        )

        return {
            "project_id": project_id,
            "status": "error",
        }


# ---------------------------------------------------------------------------
# Director run
# ---------------------------------------------------------------------------


@app.get("/director/run")
async def director_run_get(
    project_id: str = DEFAULT_PROJECT_ID,
    language: str = "en",
    region_code: str = DEFAULT_REGION_CODE,
    hours_back: int = 72,
    max_results: int = 25,
) -> dict[str, Any]:
    """
    Existing external contract.

    ai-youtube-system currently calls GET /director/run.
    Keep this route.
    """

    return await _run_director(
        project_id=project_id,
        language=language,
        region_code=region_code,
        hours_back=hours_back,
        max_results=max_results,
        objective=None,
    )


@app.post("/director/run")
async def director_run_post(
    request: DirectorRunRequest,
) -> dict[str, Any]:
    """
    New POST API for internal/UI callers.
    """

    return await _run_director(
        project_id=request.project_id,
        language=request.language,
        region_code=request.region_code,
        hours_back=request.hours_back,
        max_results=request.max_results,
        objective=request.objective,
    )


async def _run_director(
    *,
    project_id: str,
    language: str,
    region_code: str,
    hours_back: int,
    max_results: int,
    objective: str | None,
) -> dict[str, Any]:
    director = runtime.get_director(
        project_id=project_id,
    )

    if objective:
        director.context.objective = objective

    # ---------------------------------------------------------------
    # The current modular Director owns the strategic cycle.
    # Server does not independently decide what to research.
    # ---------------------------------------------------------------

    try:
        result = await call_maybe_async(
            director.run_once,
        )

        serialized = serialize(result)

        # ---------------------------------------------------------------
        # Persist the strategic outputs through Memory 2.0 so that the
        # decision and the recommendation can be retrieved back later.
        # ---------------------------------------------------------------

        # Persist the run first so every entity created by this
        # Director cycle can carry the same persistent run_id.
        run_id = await runtime.memory.save_run(
            project_id=project_id,
            run={
                "run_id": (
                    serialized.get("run_id")
                    if isinstance(serialized, dict)
                    else None
                ),
                "created_at": utc_now(),
                "language": language,
                "region_code": region_code,
                "hours_back": hours_back,
                "max_results": max_results,
                "result": serialized,
            },
        )

        decision = getattr(
            result,
            "decision",
            None,
        )

        decision_db_id = None

        if decision is not None:
            decision_db_id = await runtime.memory.save_decision(
                project_id=project_id,
                decision=decision,
                run_id=run_id,
            )

        recommendation = getattr(
            result,
            "recommendation",
            None,
        )

        recommendation_db_id = None

        if recommendation is not None:
            recommendation_db_id = (
                await runtime.memory.save_recommendation(
                    project_id=project_id,
                    recommendation=recommendation,
                    decision_db_id=decision_db_id,
                    run_id=run_id,
                )
            )

        result_db_id = await runtime.memory.save_result(
            project_id=project_id,
            result={
                "type": "director_cycle",
                "summary": (
                    serialized.get("message", "")
                    if isinstance(serialized, dict)
                    else ""
                ),
                "result": serialized,
            },
            run_id=run_id,
            decision_db_id=decision_db_id,
            recommendation_db_id=recommendation_db_id,
        )

        await runtime.memory.save_event(
            project_id=project_id,
            event_type="director_run",
            data={
                "run_id": run_id,
                "decision_id": decision_db_id,
                "recommendation_id": recommendation_db_id,
                "result_id": result_db_id,
                "status": (
                    serialized.get("status")
                    if isinstance(
                        serialized,
                        dict,
                    )
                    else None
                ),
            },
        )

        if isinstance(serialized, dict):
            serialized.setdefault(
                "project_id",
                project_id,
            )

            serialized.setdefault(
                "research_parameters",
                {
                    "language": language,
                    "region_code": region_code,
                    "hours_back": hours_back,
                    "max_results": max_results,
                },
            )

        return serialized

    except Exception as exc:
        logger.exception(
            "Director run failed: project=%s",
            project_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Не удалось выполнить цикл Директора.",
        ) from exc


# ---------------------------------------------------------------------------
# Autonomous Director
# ---------------------------------------------------------------------------


async def _execute_autonomous_cycle(
    *,
    project_id: str,
    objective: str | None = None,
) -> dict[str, Any]:
    """Run one autonomous Director cycle and persist its complete result."""
    director = runtime.get_director(
        project_id=project_id,
        mode=DirectorMode.AUTONOMOUS,
    )

    if objective:
        director.context.objective = objective

    result = await call_maybe_async(
        director.run_autonomous_cycle,
        objective=objective,
    )

    serialized = serialize(result)

    # Persist the autonomous run first so all outputs share one run_id.
    run_id = await runtime.memory.save_run(
        project_id=project_id,
        run={
            "type": "autonomous_cycle",
            "created_at": utc_now(),
            "result": serialized,
        },
    )

    decision = getattr(
        director.last_result,
        "decision",
        None,
    )

    decision_db_id = None

    if decision is not None:
        decision_db_id = await runtime.memory.save_decision(
            project_id=project_id,
            decision=decision,
            run_id=run_id,
        )

    recommendation = getattr(
        director.last_result,
        "recommendation",
        None,
    )

    recommendation_db_id = None

    if recommendation is not None:
        recommendation_db_id = (
            await runtime.memory.save_recommendation(
                project_id=project_id,
                recommendation=recommendation,
                decision_db_id=decision_db_id,
                run_id=run_id,
            )
        )

    result_db_id = await runtime.memory.save_result(
        project_id=project_id,
        result={
            "type": "autonomous_cycle",
            "summary": (
                serialized.get("message", "")
                if isinstance(serialized, dict)
                else ""
            ),
            "result": serialized,
        },
        run_id=run_id,
        decision_db_id=decision_db_id,
        recommendation_db_id=recommendation_db_id,
    )

    await runtime.memory.save_event(
        project_id=project_id,
        event_type="director_autonomous_run",
        data={
            "run_id": run_id,
            "decision_id": decision_db_id,
            "recommendation_id": recommendation_db_id,
            "result_id": result_db_id,
        },
    )

    return serialized


@app.post("/director/autonomous/run")
async def director_autonomous_run(
    project_id: str = DEFAULT_PROJECT_ID,
    objective: str | None = None,
) -> dict[str, Any]:
    if not AUTONOMOUS_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Автономный режим отключён.",
        )

    try:
        return await _execute_autonomous_cycle(
            project_id=project_id,
            objective=objective,
        )

    except Exception as exc:
        logger.exception(
            "Autonomous Director cycle failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Не удалось выполнить автономный цикл.",
        ) from exc


async def _autonomous_worker_loop() -> None:
    """Continuously bridge Scheduler/WakeupManager to Director execution."""
    logger.info(
        "Autonomous wakeup worker started: poll=%ss interval=%ss",
        AUTONOMOUS_POLL_INTERVAL_SECONDS,
        AUTONOMOUS_WAKE_INTERVAL_SECONDS,
    )

    # The scheduler is in-memory, so bootstrap one recurring schedule for
    # the default project when autonomous mode is enabled. Existing active
    # schedules are preserved.
    if runtime.scheduler is not None and runtime.wakeup is not None:
        active = runtime.scheduler.list(
            project_id=DEFAULT_PROJECT_ID,
        )
        if not active:
            runtime.scheduler.schedule_interval(
                interval_seconds=AUTONOMOUS_WAKE_INTERVAL_SECONDS,
                reason="autonomous_cycle",
                project_id=DEFAULT_PROJECT_ID,
                first_run_at=utc_now(),
                metadata={"source": "autonomous_worker"},
            )

    while True:
        try:
            if (
                runtime.scheduler is not None
                and runtime.wakeup is not None
            ):
                # Scheduler -> WakeupManager.
                runtime.wakeup.collect_due(
                    runtime.scheduler,
                )

                # WakeupManager -> Director.
                while True:
                    signal = runtime.wakeup.next()
                    if signal is None:
                        break

                    try:
                        objective = signal.payload.get("objective")
                        if not isinstance(objective, str):
                            objective = None

                        await _execute_autonomous_cycle(
                            project_id=signal.project_id,
                            objective=objective,
                        )
                    except Exception:
                        logger.exception(
                            "Autonomous wakeup failed: project=%s reason=%s",
                            signal.project_id,
                            signal.reason,
                        )
                    finally:
                        # A failed cycle must not block the whole wakeup queue.
                        runtime.wakeup.consume(signal.wakeup_id)

            await asyncio.sleep(
                AUTONOMOUS_POLL_INTERVAL_SECONDS,
            )

        except asyncio.CancelledError:
            logger.info("Autonomous wakeup worker stopped.")
            raise
        except Exception:
            logger.exception("Autonomous wakeup worker iteration failed.")
            await asyncio.sleep(
                AUTONOMOUS_POLL_INTERVAL_SECONDS,
            )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@app.get("/dashboard")
async def dashboard(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    director = runtime.get_director(
        project_id=project_id,
    )

    status = serialize(
        director.status()
    )

    memory_context = await runtime.memory.get_context(
        project_id=project_id,
        limit_runs=20,
        limit_decisions=20,
        limit_events=20,
        limit_chat=20,
        limit_actions=20,
        limit_results=20,
        limit_recommendations=20,
        limit_constraints=20,
    )

    return {
        "project_id": project_id,
        "director": status,
        "memory": serialize(
            memory_context,
        ),
        "autonomous": AUTONOMOUS_ENABLED,
        "ai_enabled": runtime.ai.enabled,
    }


@app.get("/director/dashboard")
async def director_dashboard(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    return await dashboard(
        project_id=project_id,
    )


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


@app.get("/director/recommendations")
async def director_recommendations(
    project_id: str = DEFAULT_PROJECT_ID,
    limit: int = 20,
) -> dict[str, Any]:
    context = await runtime.memory.get_context(
        project_id=project_id,
        limit_runs=limit,
        limit_decisions=limit,
        limit_events=limit,
        limit_chat=limit,
        limit_actions=limit,
        limit_results=limit,
        limit_recommendations=limit,
        limit_constraints=limit,
    )

    recommendations = context.get(
        "recommendations",
        [],
    )

    return {
        "project_id": project_id,
        "recommendations": serialize(
            recommendations
        ),
    }


@app.get(
    "/director/recommendations/{recommendation_id}"
)
async def director_recommendation(
    recommendation_id: str,
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    context = await runtime.memory.get_context(
        project_id=project_id,
        limit_runs=100,
        limit_decisions=100,
        limit_events=100,
        limit_chat=100,
        limit_actions=100,
        limit_results=100,
        limit_recommendations=100,
        limit_constraints=100,
    )

    recommendations = context.get(
        "recommendations",
        [],
    )

    for recommendation in recommendations:
        data = serialize(recommendation)

        if (
            isinstance(data, dict)
            and data.get("recommendation_id")
            == recommendation_id
        ):
            return data

    raise HTTPException(
        status_code=404,
        detail="Рекомендация не найдена.",
    )


# ---------------------------------------------------------------------------
# Recommendation actions
# ---------------------------------------------------------------------------


@app.post(
    "/director/recommendations/{recommendation_id}/action"
)
async def recommendation_action(
    recommendation_id: str,
    request: RecommendationActionRequest,
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    context = await runtime.memory.get_context(
        project_id=project_id,
        limit_runs=100,
        limit_decisions=100,
        limit_events=100,
        limit_chat=100,
        limit_actions=100,
        limit_results=100,
        limit_recommendations=100,
        limit_constraints=100,
    )

    recommendations = context.get(
        "recommendations",
        [],
    )

    recommendation = None
    memory_id: int | None = None

    for item in recommendations:
        item_dict = serialize(item)

        if (
            isinstance(item_dict, dict)
            and item_dict.get("recommendation_id")
            == recommendation_id
        ):
            recommendation = item

            try:
                memory_id = int(
                    item_dict.get("id")
                )
            except (TypeError, ValueError):
                memory_id = None

            break

    if recommendation is None:
        raise HTTPException(
            status_code=404,
            detail="Рекомендация не найдена.",
        )

    # Reconstruct the Director-facing model from the Memory row so the
    # lifecycle helpers receive the object they expect.
    updated = _memory_row_to_director_recommendation(
        recommendation
        if isinstance(recommendation, dict)
        else serialize(recommendation)
    )

    action = request.action.lower().strip()

    try:
        feedback_payload: dict[str, Any] | None = None

        if action == "accept":
            if accept_recommendation is None:
                raise RuntimeError(
                    "Recommendation lifecycle unavailable"
                )

            updated = accept_recommendation(
                updated,
                feedback=request.message,
            )

            feedback_payload = {
                "recommendation_id": memory_id,
                "feedback_type": "accept",
                "message": request.message,
                "reason": request.message,
                "scope": "recommendation",
            }

        elif action == "reject":
            if reject_recommendation is None:
                raise RuntimeError(
                    "Recommendation lifecycle unavailable"
                )

            updated = reject_recommendation(
                updated,
                reason=request.message,
            )

            feedback_payload = {
                "recommendation_id": memory_id,
                "feedback_type": "reject",
                "message": request.message,
                "reason": request.message,
                "scope": "recommendation",
            }

        elif action == "discuss":
            if discuss_recommendation is None:
                raise RuntimeError(
                    "Recommendation lifecycle unavailable"
                )

            updated = discuss_recommendation(
                updated,
                message=request.message,
            )

            feedback_payload = {
                "recommendation_id": memory_id,
                "feedback_type": "clarify",
                "message": request.message,
                "scope": "recommendation",
            }

        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Поддерживаются действия: "
                    "accept, reject, discuss."
                ),
            )

        # Persist the state change through the Memory 2.0 feedback
        # contour (updates the stored recommendation status).
        saved = None

        if feedback_payload is not None:
            saved = (
                await runtime.memory.apply_recommendation_feedback(
                    project_id=project_id,
                    feedback=feedback_payload,
                )
            )

        return {
            "success": True,
            "recommendation": serialize(
                updated,
            ),
            "saved": serialize(saved),
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Recommendation action failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Не удалось обработать рекомендацию.",
        ) from exc


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


@app.post("/director/feedback")
async def director_feedback(
    request: FeedbackRequest,
) -> dict[str, Any]:
    if create_feedback is None:
        raise HTTPException(
            status_code=503,
            detail="Feedback module unavailable.",
        )

    try:
        feedback = create_feedback(
            feedback_type=request.feedback_type,
            scope=request.scope,
            message=request.message,
            recommendation_id=request.recommendation_id,
            decision_id=request.decision_id,
            target=request.target,
            reason=request.reason,
            constraint=request.constraint,
            preference=request.preference,
        )

        director = runtime.get_director(
            project_id=request.project_id,
        )

        # Director owns the feedback contour: it updates its context and
        # persists the feedback through the existing Memory 2.0 API.
        if hasattr(
            director,
            "apply_feedback",
        ):
            await call_maybe_async(
                director.apply_feedback,
                feedback,
            )

        return {
            "success": True,
            "feedback": serialize(
                feedback,
            ),
        }

    except Exception as exc:
        logger.exception(
            "Feedback processing failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить обратную связь.",
        ) from exc


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


@app.post("/director/chat")
async def director_chat(
    request: DirectorChatRequest,
) -> dict[str, Any]:
    """
    Chat is a command interface to Director.
    """

    if parse_chat_command is None:
        raise HTTPException(
            status_code=503,
            detail="Chat module unavailable.",
        )

    director = runtime.get_director(
        project_id=request.project_id,
    )

    command = parse_chat_command(
        request.message,
    )

    async def run_research(_: Any) -> Any:
        result = director.plan_research()

        return {
            "message": (
                "Я подготовил следующий план исследования."
            ),
            "research_plan": serialize(result),
        }

    async def run_analysis(_: Any) -> Any:
        result = await director.analyze()

        return {
            "message": (
                "Анализ текущих данных завершён."
            ),
            "analysis": serialize(result),
        }

    async def generate_recommendation(
        _: Any,
    ) -> Any:
        # -------------------------------------------------------
        # chat -> intent -> Director decision -> recommendation
        # -> Memory -> user
        # -------------------------------------------------------

        analysis = None
        decision = None

        if (
            director.last_result is not None
            and director.last_result.decision is not None
        ):
            decision = director.last_result.decision
            analysis = director.last_result.data.get(
                "analysis"
            )
        else:
            analysis = await director.analyze()
            decision = await director.decide(
                analysis
            )

        recommendation = director.create_recommendation(
            decision,
            analysis=analysis,
        )

        decision_db_id = (
            await runtime.memory.save_decision(
                project_id=request.project_id,
                decision=decision,
            )
        )

        saved = await runtime.memory.save_recommendation(
            project_id=request.project_id,
            recommendation=recommendation,
            decision_db_id=decision_db_id,
        )

        return {
            "message": (
                "Я подготовил рекомендацию."
            ),
            "recommendation": serialize(
                recommendation
            ),
            "decision": serialize(decision),
            "saved": serialize(saved),
        }

    async def inspect_state(_: Any) -> Any:
        return {
            "message": (
                "Текущее состояние Директора."
            ),
            "status": serialize(
                director.status()
            ),
        }

    async def continue_cycle(_: Any) -> Any:
        result = await call_maybe_async(
            director.run_once,
        )

        return {
            "message": (
                "Продолжаю текущий цикл."
            ),
            "result": serialize(result),
        }

    async def stop_cycle(_: Any) -> Any:
        director.state.sleep_reason = (
            "Остановлено пользователем."
        )

        return {
            "message": (
                "Цикл остановлен. Я не буду "
                "продолжать работу без нового сигнала."
            ),
        }

    async def accept_recommendation(
        command: Any,
    ) -> Any:
        target = command.target

        if not target:
            return {
                "message": (
                    "Укажи, какую рекомендацию "
                    "нужно принять."
                ),
            }

        return {
            "message": (
                "Принятие рекомендации будет "
                "обработано через feedback-контур."
            ),
            "recommendation_id": target,
        }

    async def reject_recommendation(
        command: Any,
    ) -> Any:
        target = command.target

        return {
            "message": (
                "Отклонение рекомендации будет "
                "сохранено как обратная связь."
            ),
            "recommendation_id": target,
        }

    async def ask_clarification(_: Any) -> Any:
        return {
            "message": (
                "Я не до конца понял задачу. "
                "Уточни, что именно нужно исследовать, "
                "проанализировать или изменить."
            ),
        }

    handlers = {
        "start_research": run_research,
        "run_analysis": run_analysis,
        "generate_recommendation": (
            generate_recommendation
        ),
        "inspect_state": inspect_state,
        "continue_cycle": continue_cycle,
        "stop_cycle": stop_cycle,
        "accept_recommendation": (
            accept_recommendation
        ),
        "reject_recommendation": (
            reject_recommendation
        ),
        "ask_clarification": ask_clarification,
    }

    try:
        result = await execute_chat_command(
            command,
            handlers=handlers,
        )

        await runtime.memory.save_chat_message(
            project_id=request.project_id,
            role="user",
            message=request.message,
        )

        message_text = (
            result.message
            if isinstance(result, ChatResult)
            else str(result)
        )

        await runtime.memory.save_chat_message(
            project_id=request.project_id,
            role="assistant",
            message=message_text,
            data={
                "action": (
                    getattr(result, "action", None)
                    if isinstance(result, ChatResult)
                    else None
                ),
            },
        )

        serialized = serialize(result)

        # Keep the chat API contract consumed by the current frontend:
        # the human-readable Director reply is exposed as result.answer.
        return {
            "result": {
                "answer": (
                    result.message
                    if isinstance(result, ChatResult)
                    else (
                        serialized.get("message", "")
                        if isinstance(serialized, dict)
                        else str(serialized)
                    )
                ),
                "data": (
                    result.data
                    if isinstance(result, ChatResult)
                    else serialized
                ),
            },
            "message": (
                result.message
                if isinstance(result, ChatResult)
                else (
                    serialized.get("message", "")
                    if isinstance(serialized, dict)
                    else str(serialized)
                )
            ),
            "chat": serialized,
        }

    except Exception as exc:
        logger.exception(
            "Director chat failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Не удалось обработать сообщение.",
        ) from exc


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------


@app.post("/director/research")
async def director_research(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    director = runtime.get_director(
        project_id=project_id,
    )

    try:
        plan = director.plan_research()

        return {
            "project_id": project_id,
            "research_plan": serialize(plan),
        }

    except Exception as exc:
        logger.exception(
            "Research planning failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Не удалось подготовить исследование.",
        ) from exc


# ---------------------------------------------------------------------------
# Compatibility endpoints
# ---------------------------------------------------------------------------


@app.post("/director/decision")
async def director_decision(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Compatibility wrapper.

    Decision creation remains owned by Director.
    """

    project_id = str(
        payload.get(
            "project_id",
            DEFAULT_PROJECT_ID,
        )
    )

    director = runtime.get_director(
        project_id=project_id,
    )

    try:
        decision = await director.decide()

        saved = await runtime.memory.save_decision(
            project_id=project_id,
            decision=decision,
        )

        return {
            "decision": serialize(decision),
            "saved": serialize(saved),
        }

    except Exception as exc:
        logger.exception(
            "Decision endpoint failed"
        )

        raise HTTPException(
            status_code=503,
            detail="Decision service unavailable.",
        ) from exc


@app.post("/director/result")
async def director_result(
    payload: dict[str, Any],
) -> dict[str, Any]:
    project_id = str(
        payload.get(
            "project_id",
            DEFAULT_PROJECT_ID,
        )
    )

    result = payload.get(
        "result",
        payload,
    )

    saved = await runtime.memory.save_result(
        project_id=project_id,
        result=result,
    )

    return {
        "success": True,
        "saved": serialize(saved),
    }


# ---------------------------------------------------------------------------
# Wakeup / scheduler
# ---------------------------------------------------------------------------


@app.get("/director/wakeup")
async def director_wakeup(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    if runtime.wakeup is None:
        return {
            "enabled": False,
            "pending": [],
        }

    pending = runtime.wakeup.pending(
        project_id=project_id,
    )

    return {
        "enabled": AUTONOMOUS_ENABLED,
        "pending": serialize(pending),
    }


@app.post("/director/wakeup")
async def director_wakeup_trigger(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    if not AUTONOMOUS_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Автономный режим отключён.",
        )

    if runtime.wakeup is None:
        raise HTTPException(
            status_code=503,
            detail="Wakeup manager unavailable.",
        )

    signal = runtime.wakeup.notify_manual(
        project_id=project_id,
    )

    return {
        "created": True,
        "signal": serialize(signal),
    }


@app.get("/director/cron")
async def director_cron(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    """
    Compatibility endpoint.

    Does not automatically enable autonomy.
    """

    if runtime.scheduler is None:
        return {
            "enabled": False,
            "schedules": [],
        }

    schedules = runtime.scheduler.list(
        project_id=project_id,
    )

    return {
        "enabled": AUTONOMOUS_ENABLED,
        "schedules": serialize(schedules),
    }


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@app.get("/events")
async def events(
    project_id: str = DEFAULT_PROJECT_ID,
    limit: int = 50,
) -> dict[str, Any]:
    context = await runtime.memory.get_context(
        project_id=project_id,
        limit_runs=limit,
        limit_decisions=limit,
        limit_events=limit,
        limit_chat=limit,
        limit_actions=limit,
        limit_results=limit,
        limit_recommendations=limit,
        limit_constraints=limit,
    )

    return {
        "project_id": project_id,
        "events": serialize(
            context.get(
                "events",
                [],
            )
        ),
    }


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@app.get("/director/history")
async def director_history(
    project_id: str = DEFAULT_PROJECT_ID,
    limit: int = 50,
) -> dict[str, Any]:
    context = await runtime.memory.get_context(
        project_id=project_id,
        limit_runs=limit,
        limit_decisions=limit,
        limit_events=limit,
        limit_chat=limit,
        limit_actions=limit,
        limit_results=limit,
        limit_recommendations=limit,
        limit_constraints=limit,
    )

    return {
        "project_id": project_id,
        "runs": serialize(
            context.get(
                "runs",
                [],
            )
        ),
        "decisions": serialize(
            context.get(
                "decisions",
                [],
            )
        ),
        "recommendations": serialize(
            context.get(
                "recommendations",
                [],
            )
        ),
        "results": serialize(
            context.get(
                "results",
                [],
            )
        ),
    }


# ---------------------------------------------------------------------------
# Debug endpoints
# ---------------------------------------------------------------------------


@app.get("/director-debug")
async def director_debug(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    director = runtime.get_director(
        project_id=project_id,
    )

    return {
        "project_id": project_id,
        "director": serialize(
            director.status()
        ),
        "context": serialize(
            director.context,
        ),
        "runtime": {
            "memory": runtime.memory.enabled,
            "ai": runtime.ai.enabled,
            "autonomous": AUTONOMOUS_ENABLED,
        },
    }


@app.get("/radar-debug")
async def radar_debug(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    """
    DATA / research diagnostic endpoint.

    No strategic decision is made here.
    """

    state = await runtime.data.get_project_state(
        project_id=project_id,
    )

    return {
        "project_id": project_id,
        "data": serialize(state),
    }


# ---------------------------------------------------------------------------
# Radar compatibility endpoint
# ---------------------------------------------------------------------------


@app.get("/radar")
async def radar(
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    """
    Radar is intentionally represented as a DATA/research view.

    Actual strategic interpretation belongs to Director.
    """

    state = await runtime.data.get_project_state(
        project_id=project_id,
    )

    return {
        "project_id": project_id,
        "status": "available",
        "data": serialize(state),
    }


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def unhandled_exception(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "Unhandled request error: %s %s",
        request.method,
        request.url.path,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": (
                "Внутренняя ошибка сервера."
            ),
        },
    )


# ---------------------------------------------------------------------------
# Application startup / shutdown
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup() -> None:
    logger.info(
        "Starting %s",
        SERVICE_NAME,
    )

    logger.info(
        "Director memory: %s",
        "enabled"
        if runtime.memory.enabled
        else "disabled",
    )

    logger.info(
        "AI provider: %s",
        "enabled"
        if runtime.ai.enabled
        else "disabled",
    )

    logger.info(
        "Autonomous mode: %s",
        "enabled"
        if AUTONOMOUS_ENABLED
        else "disabled",
    )

    if AUTONOMOUS_ENABLED:
        runtime.autonomous_worker = asyncio.create_task(
            _autonomous_worker_loop(),
        )


@app.on_event("shutdown")
async def shutdown() -> None:
    if runtime.autonomous_worker is not None:
        runtime.autonomous_worker.cancel()
        try:
            await runtime.autonomous_worker
        except asyncio.CancelledError:
            pass
        finally:
            runtime.autonomous_worker = None

    logger.info(
        "Stopping %s",
        SERVICE_NAME,
    )


# ---------------------------------------------------------------------------
# ASGI entry point
# ---------------------------------------------------------------------------

application = app
