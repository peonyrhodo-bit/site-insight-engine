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

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    from ai.provider import create_ai_provider
except Exception:
    create_ai_provider = None


# Analytics imports are intentionally modular.
try:
    from analytics.analytics import (
        prepare_for_director as analytics_prepare_for_director,
    )
except Exception:
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


class ServerMemory:
    """
    Thin compatibility layer around Memory 2.0.

    server.py should not know Supabase table details.
    """

    def __init__(self) -> None:
        self.backend = None
        self.memory = None

        if Memory is None:
            logger.warning("Memory module unavailable")
            return

        try:
            if SupabaseMemoryBackend is not None:
                self.backend = SupabaseMemoryBackend()

            self.memory = Memory(
                backend=self.backend,
            )

            logger.info("Director memory initialized")

        except Exception:
            logger.exception("Failed to initialize memory")
            self.backend = None
            self.memory = None

    @property
    def enabled(self) -> bool:
        return self.memory is not None

    async def get_context(
        self,
        project_id: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        if not self.memory:
            return {}

        try:
            result = self.memory.get_context(
                project_id=project_id,
                limit=limit,
            )

            if hasattr(result, "__await__"):
                result = await result

            return result if isinstance(result, dict) else {}

        except Exception:
            logger.exception(
                "Memory get_context failed: project=%s",
                project_id,
            )
            return {}

    async def save_run(
        self,
        project_id: str,
        run: dict[str, Any],
    ) -> Any:
        if not self.memory:
            return None

        try:
            result = self.memory.save_run(
                project_id=project_id,
                run=run,
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
    ) -> Any:
        if not self.memory:
            return None

        try:
            if hasattr(self.memory, "save_decision_model"):
                result = self.memory.save_decision_model(
                    project_id=project_id,
                    decision=decision,
                )
            else:
                result = self.memory.save_decision(
                    project_id=project_id,
                    decision=serialize(decision),
                )

            if hasattr(result, "__await__"):
                result = await result

            return result

        except Exception:
            logger.exception("Memory save_decision failed")
            return None

    async def save_recommendation(
        self,
        project_id: str,
        recommendation: Any,
    ) -> Any:
        if not self.memory:
            return None

        try:
            result = self.memory.save_recommendation(
                project_id=project_id,
                recommendation=recommendation,
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        except Exception:
            logger.exception(
                "Memory save_recommendation failed"
            )
            return None

    async def save_feedback(
        self,
        project_id: str,
        feedback: Any,
    ) -> Any:
        """
        Compatibility wrapper.

        Memory 2.0 uses recommendation feedback rather than
        the old save_feedback() API.
        """

        if not self.memory:
            return None

        payload = serialize(feedback)

        try:
            if hasattr(
                self.memory,
                "save_recommendation_feedback",
            ):
                result = (
                    self.memory.save_recommendation_feedback(
                        project_id=project_id,
                        feedback=payload,
                    )
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

            if hasattr(self.memory, "save_event"):
                result = self.memory.save_event(
                    project_id=project_id,
                    event={
                        "type": "director_feedback",
                        "data": payload,
                    },
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        except Exception:
            logger.exception("Memory save_feedback failed")

        return None

    async def save_result(
        self,
        project_id: str,
        result: Any,
    ) -> Any:
        if not self.memory:
            return None

        try:
            if hasattr(self.memory, "save_result"):
                saved = self.memory.save_result(
                    project_id=project_id,
                    result=serialize(result),
                )

                if hasattr(saved, "__await__"):
                    saved = await saved

                return saved

        except Exception:
            logger.exception("Memory save_result failed")

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

        analytics_data: dict[str, Any] = {}

        # ---------------------------------------------------------------
        # Basic analytics
        # ---------------------------------------------------------------

        if analytics_prepare_for_director is not None:
            try:
                prepared = analytics_prepare_for_director(
                    observations,
                )

                if prepared is not None:
                    analytics_data["analytics"] = serialize(
                        prepared
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

        previous = context.get(
            "previous_observations",
            [],
        )

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

                for item in topic_items or []:
                    try:
                        opportunity = assess_opportunity(
                            item,
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

    def __init__(self) -> None:
        self.youtube_registry = None
        self.research_manager = None
        self.relations = None

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
        }

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
        Compatibility method for Director.

        The current Director expects generate_decision().
        New AI provider is intentionally kept behind this adapter.
        """

        if not self.provider:
            return {}

        try:
            from ai.prompts import (
                build_decision_prompt,
            )

            prompt = build_decision_prompt(
                context=context,
            )

            response = await self.provider.generate_json(
                prompt=prompt,
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
        self.data = DataAdapter()
        self.ai = AIAdapter()

        self.scheduler = (
            create_scheduler(
                enabled=AUTONOMOUS_ENABLED,
                default_project_id=DEFAULT_PROJECT_ID,
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
            memory_service=self.memory.memory,
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

        await runtime.memory.save_run(
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

    director = runtime.get_director(
        project_id=project_id,
        mode=DirectorMode.AUTONOMOUS,
    )

    if objective:
        director.context.objective = objective

    try:
        result = await call_maybe_async(
            director.run_autonomous_cycle,
            objective=objective,
        )

        serialized = serialize(result)

        await runtime.memory.save_run(
            project_id=project_id,
            run={
                "type": "autonomous_cycle",
                "created_at": utc_now(),
                "result": serialized,
            },
        )

        return serialized

    except Exception as exc:
        logger.exception(
            "Autonomous Director cycle failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Не удалось выполнить автономный цикл.",
        ) from exc


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
        limit=20,
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
        limit=limit,
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
        limit=100,
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
        limit=100,
    )

    recommendations = context.get(
        "recommendations",
        [],
    )

    recommendation = None

    for item in recommendations:
        item_dict = serialize(item)

        if (
            isinstance(item_dict, dict)
            and item_dict.get("recommendation_id")
            == recommendation_id
        ):
            recommendation = item
            break

    if recommendation is None:
        raise HTTPException(
            status_code=404,
            detail="Рекомендация не найдена.",
        )

    action = request.action.lower().strip()

    try:
        if action == "accept":
            if accept_recommendation is None:
                raise RuntimeError(
                    "Recommendation lifecycle unavailable"
                )

            updated = accept_recommendation(
                recommendation,
                feedback=request.message,
            )

        elif action == "reject":
            if reject_recommendation is None:
                raise RuntimeError(
                    "Recommendation lifecycle unavailable"
                )

            updated = reject_recommendation(
                recommendation,
                reason=request.message,
            )

        elif action == "discuss":
            if discuss_recommendation is None:
                raise RuntimeError(
                    "Recommendation lifecycle unavailable"
                )

            updated = discuss_recommendation(
                recommendation,
                message=request.message,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Поддерживаются действия: "
                    "accept, reject, discuss."
                ),
            )

        saved = await runtime.memory.save_recommendation(
            project_id=project_id,
            recommendation=updated,
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

        await runtime.memory.save_feedback(
            project_id=request.project_id,
            feedback=feedback,
        )

        director = runtime.get_director(
            project_id=request.project_id,
        )

        if hasattr(
            director,
            "apply_feedback",
        ):
            try:
                director.apply_feedback(
                    feedback,
                )
            except Exception:
                logger.exception(
                    "Director apply_feedback failed"
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
        result = director.analyze()

        return {
            "message": (
                "Анализ текущих данных завершён."
            ),
            "analysis": serialize(result),
        }

    async def generate_recommendation(
        _: Any,
    ) -> Any:
        result = director.create_recommendation()

        return {
            "message": (
                "Я подготовил рекомендацию."
            ),
            "recommendation": serialize(result),
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
        result = execute_chat_command(
            command,
            handlers=handlers,
        )

        if hasattr(result, "__await__"):
            result = await result

        return serialize(result)

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
        decision = director.decide()

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

    signal = runtime.wakeup.manual(
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
        limit=limit,
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
        limit=limit,
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


@app.on_event("shutdown")
async def shutdown() -> None:
    logger.info(
        "Stopping %s",
        SERVICE_NAME,
    )


# ---------------------------------------------------------------------------
# ASGI entry point
# ---------------------------------------------------------------------------

application = app
