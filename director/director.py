"""
Valery — the central Director.

This module orchestrates:
    state
    research
    analytics
    AI
    decisions
    recommendations
    feedback
    memory
    autonomy

It is the strategic brain of the system.

It does not replace specialized systems.
"""

from __future__ import annotations

import json
import os

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable

import logging

from .autonomy import (
    AutonomyConfig,
    CycleStatus,
    DirectorAutonomy,
    DirectorCycle,
    DirectorPhase,
    DirectorState,
)
from .decision import (
    DecisionType,
    DirectorDecision,
    build_decision,
    decide_from_opportunity,
)
from .feedback import (
    DirectorFeedback,
    feedback_to_memory_record,
)
from .hypothesis import (
    DirectorHypothesis,
    build_hypothesis,
)
from .language import build_director_message
from .recommendations import (
    DirectorRecommendation,
    RecommendationEvidence,
    RecommendationStatus,
    RecommendationTarget,
    create_recommendation,
)
from .research import (
    ResearchPlan,
    ResearchPriority,
    build_query,
    plan_next_research,
)


logger = logging.getLogger(__name__)


class DirectorMode(str, Enum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTONOMOUS = "autonomous"


class DirectorStatus(str, Enum):
    IDLE = "idle"
    RESEARCHING = "researching"
    ANALYZING = "analyzing"
    DECIDING = "deciding"
    WAITING = "waiting"
    EVALUATING = "evaluating"
    SLEEPING = "sleeping"
    ERROR = "error"


@dataclass
class DirectorContext:
    """
    Snapshot of everything Valery currently knows about the project.
    """

    project_id: str | None = None

    objective: str | None = None

    channels: list[dict[str, Any]] = field(default_factory=list)
    strategies: list[dict[str, Any]] = field(default_factory=list)

    observations: list[dict[str, Any]] = field(default_factory=list)
    analytics: dict[str, Any] = field(default_factory=dict)
    topics: dict[str, Any] = field(default_factory=dict)
    opportunities: list[dict[str, Any]] = field(default_factory=list)

    research_history: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)

    feedback: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)

    resources: dict[str, Any] = field(default_factory=dict)
    available_actions: list[str] = field(default_factory=list)

    missing_data: list[str] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_analysis_dict(self) -> dict[str, Any]:
        """Return a read-only context view without deep-copying large evidence sets.

        Analytics and AI only inspect this context. dataclasses.asdict() recursively
        copies every video/snapshot and can temporarily multiply memory use enough
        to exceed small worker limits. Keep the same field shape but reuse existing
        collections; consumers of this view must not mutate them.
        """
        return {
            "project_id": self.project_id,
            "objective": self.objective,
            "channels": self.channels,
            "strategies": self.strategies,
            "observations": self.observations,
            "analytics": self.analytics,
            "topics": self.topics,
            "opportunities": self.opportunities,
            "research_history": self.research_history,
            "decisions": self.decisions,
            "recommendations": self.recommendations,
            "feedback": self.feedback,
            "constraints": self.constraints,
            "resources": self.resources,
            "available_actions": self.available_actions,
            "missing_data": self.missing_data,
            "metadata": self.metadata,
        }


@dataclass
class DirectorResult:
    """
    Result of one strategic Director step.
    """

    status: DirectorStatus
    phase: DirectorPhase

    message: str

    decision: DirectorDecision | None = None
    recommendation: DirectorRecommendation | None = None
    research_plan: ResearchPlan | None = None

    data: dict[str, Any] = field(default_factory=dict)

    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Director:
    """
    Main Valery object.

    The Director owns orchestration and strategic interpretation.
    """

    def __init__(
        self,
        *,
        project_id: str | None = None,
        mode: DirectorMode = DirectorMode.MANUAL,

        # Optional external services.
        research_service: Any = None,
        analytics_service: Any = None,
        memory_service: Any = None,
        ai_service: Any = None,
        data_service: Any = None,

        autonomy_config: AutonomyConfig | None = None,
    ) -> None:
        self.project_id = project_id
        self.mode = mode

        self.research_service = research_service
        self.analytics_service = analytics_service
        self.memory_service = memory_service
        self.ai_service = ai_service
        self.data_service = data_service

        self.autonomy_config = (
            autonomy_config or AutonomyConfig(
                enabled=mode == DirectorMode.AUTONOMOUS
            )
        )

        self.state = DirectorState(
            project_id=project_id,
        )

        self.context = DirectorContext(
            project_id=project_id,
        )

        self.last_result: DirectorResult | None = None
        self.last_cycle: DirectorCycle | None = None

    def to_ai_decision_dict(self) -> dict[str, Any]:
        """Build a bounded context payload for decision-enrichment AI.

        The full evidence set remains available to local analytics, but sending
        thousands of raw video/snapshot rows to the AI provider creates an
        avoidable serialization and prompt-memory spike. Decision enrichment
        should use the current analysis plus a small representative sample.
        """
        sample_fields = (
            "video_id", "title", "name", "channel_title", "channel_id",
            "views", "viewCount", "likes", "likeCount", "comments",
            "commentCount", "views_per_hour", "velocity", "growth_rate",
            "published_at", "metrics",
        )
        observation_sample = []
        for item in self.observations[:8]:
            if not isinstance(item, dict):
                continue
            observation_sample.append({
                key: item[key]
                for key in sample_fields
                if key in item
            })

        return {
            "project_id": self.project_id,
            "objective": self.objective,
            "channels": self.channels[:20],
            "strategies": self.strategies[:10],
            "observations": {
                "total_count": len(self.observations),
                "sample": observation_sample,
            },
            "analytics": self.analytics,
            "topics": self.topics,
            "opportunities": self.opportunities[:20],
            "research_history": self.research_history[-10:],
            "decisions": self.decisions[-10:],
            "recommendations": self.recommendations[-10:],
            "feedback": self.feedback[-10:],
            "constraints": self.constraints[:20],
            "resources": self.resources,
            "available_actions": self.available_actions,
            "missing_data": self.missing_data,
            "metadata": {
                key: self.metadata[key]
                for key in (
                    "project_state", "data_inventory", "capabilities",
                    "signal_interpretation", "current_hypothesis",
                )
                if key in self.metadata
            },
        }

    # ============================================================
    # CAPABILITIES
    # ============================================================

    def discover_capabilities(self) -> dict[str, Any]:
        """Build the runtime map of capabilities actually available now."""
        services = {
            "research": self.research_service,
            "analytics": self.analytics_service,
            "memory": self.memory_service,
            "ai": self.ai_service,
            "data": self.data_service,
        }
        connected = {name: service is not None for name, service in services.items()}

        actions: list[str] = ["inspect", "understand", "assess", "decide"]
        if self.research_service is not None and getattr(self.research_service, "plan", None):
            actions.extend(["research", "plan_research"])
        if self.analytics_service is not None and getattr(self.analytics_service, "analyze", None):
            actions.append("analyze")
        if self.ai_service is not None:
            actions.append("ai_assistance")
        actions.extend(["formulate_hypothesis", "create_recommendation", "record_feedback"])
        actions.append(
            "execute_allowed_external_action"
            if self.autonomy_config.allow_external_actions
            else "request_human_confirmation"
        )

        constraints = {
            "external_actions_allowed": self.autonomy_config.allow_external_actions,
            "max_steps_per_cycle": self.autonomy_config.max_steps_per_cycle,
            "max_research_steps": self.autonomy_config.max_research_steps,
            "max_action_steps": self.autonomy_config.max_action_steps,
        }
        capabilities = {
            "connected_services": connected,
            "available_actions": actions,
            "constraints": constraints,
            "mode": self.mode.value,
        }

        self.context.available_actions = actions
        self.context.resources = {"services": connected, "mode": self.mode.value}
        self.context.metadata["capabilities"] = capabilities

        logger.info(
            "DIRECTOR CAPABILITIES: project=%s actions=%s services=%s external_actions=%s",
            self.project_id, actions, connected, self.autonomy_config.allow_external_actions,
        )
        return capabilities

    # ============================================================
    # STATE
    # ============================================================

    async def inspect(self) -> DirectorContext:
        """
        Build a current strategic context.

        External memory/data services can enrich it later.
        """
        if self.memory_service is not None:
            loader = getattr(
                self.memory_service,
                "get_context",
                None,
            )

            if loader:
                external_context = loader(
                    project_id=self.project_id,
                    limit_runs=10,
                    limit_decisions=20,
                    limit_events=30,
                    limit_chat=20,
                    limit_actions=20,
                    limit_results=20,
                    limit_recommendations=20,
                    limit_constraints=20,
                )

                if hasattr(
                    external_context,
                    "__await__",
                ):
                    external_context = (
                        await external_context
                    )

                if isinstance(external_context, dict):
                    self._merge_context(external_context)

        if self.data_service is not None:
            loader = getattr(
                self.data_service,
                "get_project_state",
                None,
            )

            if loader:
                external_state = loader(
                    project_id=self.project_id
                )

                if hasattr(
                    external_state,
                    "__await__",
                ):
                    external_state = (
                        await external_state
                    )

                if isinstance(external_state, dict):
                    self._merge_context(external_state)

        self._refresh_project_state()
        return self.context

    def _refresh_project_state(self) -> None:
        """Reconcile persisted evidence into an operational project state."""
        observations = [
            item for item in self.context.observations
            if isinstance(item, dict)
        ]

        inventory = self.context.metadata.get("data_inventory")
        if not isinstance(inventory, dict):
            inventory = {}

        observation_count = len(observations)
        try:
            snapshot_count = int(inventory.get("snapshot_count") or 0)
        except (TypeError, ValueError):
            snapshot_count = 0

        metric_keys = {
            "views", "viewCount", "views_per_hour",
            "likes", "likeCount", "comments", "commentCount",
            "engagement",
        }

        metric_observations = 0
        velocity_observations = 0

        for observation in observations:
            metrics = observation.get("metrics")
            if not isinstance(metrics, dict):
                metrics = {}

            merged = dict(observation)
            merged.update(metrics)

            if any(
                key in merged and merged.get(key) is not None
                for key in metric_keys
            ):
                metric_observations += 1

            if any(
                key in merged and merged.get(key) is not None
                for key in ("views_per_hour", "velocity", "growth_rate")
            ):
                velocity_observations += 1

        gaps: list[str] = []

        # Distinguish raw evidence from the structural evidence needed
        # for a strategic YouTube decision. DATA supplies inventory;
        # the Director decides which missing ingredients matter next.
        def inventory_count(key: str) -> int:
            try:
                return int(inventory.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        inventory_counts = {
            "videos": inventory_count("video_count"),
            "video_snapshots": snapshot_count,
            "queries": inventory_count("query_count"),
            "research_sets": inventory_count("research_set_count"),
            "relations": inventory_count("relation_count"),
            "channels": inventory_count("channel_count"),
            "channel_snapshots": inventory_count("channel_snapshot_count"),
            "niches": inventory_count("niche_count"),
            "niche_snapshots": inventory_count("niche_snapshot_count"),
        }

        requirements: list[dict[str, Any]] = []

        def require(key: str, description: str, priority: str, *, needed_when: bool = True) -> None:
            count = inventory_counts[key]
            requirements.append({
                "key": key,
                "description": description,
                "priority": priority,
                "available": count > 0,
                "count": count,
                "needed_now": bool(needed_when and count == 0),
            })

        # Inventory is descriptive, not a global checklist. Only raw evidence
        # needed to begin the current discovery objective is requested
        # automatically. Other entities become requirements only for a task
        # that actually needs them.
        require("videos", "Видео для первичной картины спроса, тем и результатов.", "critical", needed_when=inventory_counts["videos"] == 0)
        require("video_snapshots", "История метрик видео для определения скорости и динамики роста.", "high", needed_when=inventory_counts["videos"] > 0 and inventory_counts["video_snapshots"] == 0)
        require("queries", "Сохранённые поисковые запросы, показывающие что именно уже искали.", "high", needed_when=False)
        require("research_sets", "История исследований, чтобы не повторять уже выполненную работу.", "high", needed_when=False)
        require("relations", "Связи между исследованиями, запросами, видео, результатами и решениями.", "medium", needed_when=False)
        require("channels", "Сущности каналов для оценки конкуренции и распределения результата.", "high", needed_when=False)
        require("channel_snapshots", "История каналов для оценки роста каналов и конкурентной динамики.", "medium", needed_when=False)
        require("niches", "Явные сущности ниш/направлений, которые можно сравнивать между собой.", "critical", needed_when=False)
        require("niche_snapshots", "История ниш для оценки роста, конкуренции и изменения opportunity.", "high", needed_when=False)

        for requirement in requirements:
            if requirement["needed_now"]:
                gaps.append(f"{requirement['description']} (отсутствует: {requirement['key']}).")

        if observation_count > 0 and metric_observations == 0:
            gaps.append("У сохранённых видео нет доступных числовых метрик.")

        if observation_count > 0 and velocity_observations == 0:
            gaps.append("Нет метрик скорости роста (views/hour или эквивалента).")

        self.context.missing_data = gaps
        self.state.evidence_available = observation_count > 0
        # This flag means "enough raw evidence to begin analysis", not
        # "every possible metric exists". Missing velocity lowers confidence
        # and may become a task-specific gap, but must not block all analysis.
        self.state.evidence_sufficient = (
            observation_count > 0
            and metric_observations > 0
        )

        # Freshness is based on metric capture time, never publication date.
        snapshot_times: list[datetime] = []
        for observation in observations:
            captured = observation.get("snapshot_captured_at") or observation.get("captured_at")
            if not captured:
                continue
            try:
                parsed = datetime.fromisoformat(str(captured).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                snapshot_times.append(parsed.astimezone(timezone.utc))
            except (TypeError, ValueError):
                continue
        latest_snapshot = max(snapshot_times) if snapshot_times else None
        now_utc = datetime.now(timezone.utc)
        snapshot_age_hours = (
            max((now_utc - latest_snapshot).total_seconds() / 3600, 0)
            if latest_snapshot else None
        )
        freshness_status = (
            "unknown" if snapshot_age_hours is None
            else "fresh" if snapshot_age_hours <= 24
            else "stale"
        )

        topic_names: set[str] = set()
        for observation in observations:
            for key in ("topic", "category", "niche"):
                value = observation.get(key)
                if isinstance(value, str) and value.strip():
                    topic_names.add(value.strip().lower())
            metadata = observation.get("metadata")
            if isinstance(metadata, dict):
                for key in ("topic", "category", "niche"):
                    value = metadata.get(key)
                    if isinstance(value, str) and value.strip():
                        topic_names.add(value.strip().lower())

        search_limit = int(os.getenv("YOUTUBE_SEARCH_DAILY_LIMIT", "100"))
        search_used = inventory_count("youtube_search_calls_today")
        search_remaining = max(search_limit - search_used, 0)
        quota_limit = int(os.getenv("YOUTUBE_OTHER_DAILY_QUOTA_UNITS", "10000"))
        quota_used = inventory_count("youtube_other_units_today")
        quota_remaining = max(quota_limit - quota_used, 0)

        self.context.metadata["data_requirements"] = requirements
        self.context.metadata["project_state"] = {
            "observation_count": observation_count,
            "snapshot_count": snapshot_count,
            "metric_observation_count": metric_observations,
            "velocity_observation_count": velocity_observations,
            "inventory": inventory_counts,
            "freshness": {
                "status": freshness_status,
                "latest_snapshot_at": latest_snapshot.isoformat() if latest_snapshot else None,
                "age_hours": round(snapshot_age_hours, 2) if snapshot_age_hours is not None else None,
                "threshold_hours": 24,
            },
            "coverage": {
                "known_topic_labels": len(topic_names),
                "stored_search_queries": inventory_counts["queries"],
                "known_channels": inventory_counts["channels"],
            },
            "quota": {
                "accounting": "persisted_director_mcp_calls",
                "search_calls_used_today": search_used,
                "search_calls_limit": search_limit,
                "search_calls_remaining": search_remaining,
                "other_units_used_today": quota_used,
                "other_units_limit": quota_limit,
                "remaining_units_today": quota_remaining,
                "estimated_other_units_per_search": 1,
                "estimated_searches_affordable": min(search_remaining, quota_remaining),
            },
            "has_topics": bool(self.context.topics),
            "has_analytics": bool(self.context.analytics),
            "has_opportunities": bool(self.context.opportunities),
            "has_research_history": bool(self.context.research_history),
            "raw_evidence_ready_for_analytics": self.state.evidence_sufficient,
            "missing_raw_data": list(gaps),
        }

    def _merge_context(
        self,
        data: dict[str, Any],
    ) -> None:
        """
        Conservative context merge.

        We do not overwrite non-empty local state with empty external values.
        """
        for key, value in data.items():
            if not hasattr(self.context, key):
                self.context.metadata[key] = value
                continue

            current = getattr(self.context, key)

            if value in (None, "", [], {}):
                continue

            if isinstance(current, list) and isinstance(value, list):
                setattr(self.context, key, value)
            elif isinstance(current, dict) and isinstance(value, dict):
                merged = dict(current)
                merged.update(value)
                setattr(self.context, key, merged)
            else:
                setattr(self.context, key, value)

    # ============================================================
    # UNDERSTANDING
    # ============================================================

    def understand(self) -> dict[str, Any]:
        """
        Convert raw project state into a strategic problem definition.
        """
        objective = self.context.objective

        if not objective:
            objective = (
                "Найти и проверить перспективные направления "
                "для YouTube-проекта."
            )

            self.context.objective = objective

        self._refresh_project_state()
        project_state = self.context.metadata.get(
            "project_state",
            {},
        )

        return {
            "objective": objective,
            "evidence_available": self.state.evidence_available,
            "evidence_sufficient": self.state.evidence_sufficient,
            "observations_count": len(self.context.observations),
            "topics_available": bool(self.context.topics),
            "analytics_available": bool(self.context.analytics),
            "opportunities_available": bool(self.context.opportunities),
            "research_history_available": bool(
                self.context.research_history
            ),
            "missing_data": list(self.context.missing_data),
            "data_requirements": list(self.context.metadata.get("data_requirements", [])),
            "constraints": list(self.context.constraints),
            "project_state": dict(project_state),
        }

    # ============================================================
    # RESEARCH
    # ============================================================

    def plan_research(
        self,
        *,
        objective: str | None = None,
        missing_data: Iterable[Any] | None = None,
    ) -> ResearchPlan:
        """
        Ask the research layer what should be investigated next.
        """
        objective = (
            objective
            or self.context.objective
            or "Исследовать перспективные направления YouTube."
        )

        if self.research_service is not None:
            planner = getattr(
                self.research_service,
                "plan",
                None,
            )

            if planner:
                research_context = self.context.to_analysis_dict()
                if missing_data is not None:
                    # The planner sees gaps for this task, not every empty
                    # table in the project schema.
                    research_context["missing_data"] = list(missing_data)
                    metadata = research_context.get("metadata")
                    if isinstance(metadata, dict):
                        metadata = dict(metadata)
                        metadata["data_requirements"] = []
                        research_context["metadata"] = metadata
                result = planner(
                    objective=objective,
                    context=research_context,
                )

                if isinstance(result, ResearchPlan):
                    project_state = self.context.metadata.get("project_state", {})
                    quota = project_state.get("quota", {}) if isinstance(project_state, dict) else {}
                    freshness = project_state.get("freshness", {}) if isinstance(project_state, dict) else {}
                    coverage = project_state.get("coverage", {}) if isinstance(project_state, dict) else {}
                    stored_query_count = int(coverage.get("stored_search_queries", 0) or 0)
                    force_broad_discovery = any("широк" in str(item).lower() for item in (missing_data or []))
                    if stored_query_count < 12 or freshness.get("status") != "fresh" or force_broad_discovery:
                        seed_batches = [
                            [
                                ("emerging YouTube trends 2026", "en", "US"),
                                ("fast growing YouTube Shorts topics", "en", "US"),
                                ("новые тренды YouTube 2026", "ru", "RU"),
                                ("популярные новые форматы YouTube Shorts", "ru", "RU"),
                            ],
                            [
                                ("new YouTube channel niches with low competition", "en", "US"),
                                ("recently viral educational videos YouTube", "en", "GB"),
                                ("растущие ниши YouTube с низкой конкуренцией", "ru", "RU"),
                                ("вирусные образовательные видео YouTube", "ru", "RU"),
                            ],
                            [
                                ("popular DIY and home improvement Shorts", "en", "US"),
                                ("new gaming and entertainment trends YouTube", "en", "CA"),
                                ("популярные DIY и домашние проекты Shorts", "ru", "RU"),
                                ("новые игровые и развлекательные тренды YouTube", "ru", "RU"),
                            ],
                            [
                                ("new creator formats and faceless channels YouTube", "en", "US"),
                                ("fast growing lifestyle and hobby topics YouTube", "en", "AU"),
                                ("новые форматы авторских и безликих каналов YouTube", "ru", "RU"),
                                ("быстрорастущие темы лайфстайл и хобби YouTube", "ru", "RU"),
                            ],
                        ]
                        batch_index = (stored_query_count // 4) % len(seed_batches)
                        existing = {
                            (str(q.query).strip().lower(), str(q.language).lower())
                            for q in result.queries
                        }
                        for text, language, region in seed_batches[batch_index]:
                            if (text.lower(), language) in existing:
                                continue
                            result.queries.append(build_query(
                                query=text,
                                language=language,
                                region_code=region,
                                purpose="Широкое обнаружение новых направлений вне прежних гипотез.",
                                priority=ResearchPriority.HIGH,
                                metadata={"discovery_batch": batch_index, "broad_discovery": True},
                            ))
                    remaining_units = quota.get("remaining_units_today")
                    remaining_search_calls = quota.get("search_calls_remaining")
                    if remaining_units is not None and remaining_search_calls is not None:
                        estimated_cost = int(quota.get("estimated_other_units_per_search", 1) or 1)
                        max_queries = max(min(int(remaining_units) // estimated_cost, int(remaining_search_calls)), 0)
                        original_count = len(result.queries)
                        result.queries = result.queries[:max_queries]
                        result.metadata["quota_budget"] = {
                            "remaining_units": int(remaining_units),
                            "estimated_other_units_per_search": estimated_cost,
                            "search_calls_remaining": int(remaining_search_calls),
                            "queries_allowed": max_queries,
                            "queries_planned_before_cap": original_count,
                            "queries_planned_after_cap": len(result.queries),
                            "other_units_used_today": quota.get("other_units_used_today", 0),
                        }
                        logger.info("DIRECTOR RESEARCH PLAN: objective=%s queries=%s quota_budget=%s", result.objective, [q.query for q in result.queries], result.metadata["quota_budget"])
                    return result

        gaps = list(missing_data) if missing_data is not None else list(self.context.missing_data)
        return plan_next_research(
            objective=objective,
            missing_data=gaps,
            current_topics=self._current_topic_names(),
        )

    def _current_topic_names(self) -> list[str]:
        topics = self.context.topics

        if not isinstance(topics, dict):
            return []

        result = topics.get("topics", topics.get("items", []))

        names: list[str] = []

        if isinstance(result, dict):
            result = result.values()

        for item in result or []:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("topic")
                    or item.get("title")
                )

                if name:
                    names.append(str(name))

        return names

    # ============================================================
    # ANALYSIS
    # ============================================================

    async def analyze(self) -> dict[str, Any]:
        """
        Run analytical services.

        Analytics produces facts and assessments.
        Valery interprets them later.
        """
        result: dict[str, Any] = {
            "topics": self.context.topics,
            "opportunities": self.context.opportunities,
            "analytics": self.context.analytics,
        }

        if self.analytics_service is not None:
            analyzer = getattr(
                self.analytics_service,
                "analyze",
                None,
            )

            if analyzer:
                external = analyzer(
                    context=self.context.to_analysis_dict()
                )

                if hasattr(external, "__await__"):
                    external = await external

                if isinstance(external, dict):
                    result.update(external)

        # Keep the Director context in sync with the latest analysis.
        interpretation = self.interpret_signals(result)
        result["signal_interpretation"] = interpretation

        hypothesis = self.formulate_hypothesis(result)
        result["hypothesis"] = (
            hypothesis.to_dict() if hypothesis is not None else None
        )

        self.context.analytics = (
            result.get(
                "analytics",
                self.context.analytics,
            )
            or self.context.analytics
        )

        self.context.topics = (
            result.get(
                "topics",
                self.context.topics,
            )
            or self.context.topics
        )

        self.context.opportunities = (
            result.get(
                "opportunities",
                self.context.opportunities,
            )
            or self.context.opportunities
        )

        return result

    # ============================================================
    # SIGNAL INTERPRETATION
    # ============================================================

    def interpret_signals(
        self,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Translate Analytics signals into Director-level meaning.

        Analytics calculates signals and scores; the Director is
        responsible for interpreting what those signals mean together,
        including contradictions, evidence quality, and uncertainty.
        """
        opportunities = analysis.get("opportunities") or []
        if not isinstance(opportunities, list):
            opportunities = [opportunities]

        interpretations: list[dict[str, Any]] = []

        for item in opportunities:
            if not isinstance(item, dict):
                continue

            signals = [
                str(x)
                for x in (item.get("signals") or [])
                if str(x).strip()
            ]
            strengths = [
                str(x)
                for x in (item.get("strengths") or [])
                if str(x).strip()
            ]
            risks = [
                str(x)
                for x in (item.get("risks") or [])
                if str(x).strip()
            ]
            missing = [
                str(x)
                for x in (item.get("missing_data") or [])
                if str(x).strip()
            ]

            score = self._safe_score(item.get("overall_score"))
            confidence = self._safe_score(item.get("confidence"))
            dimensions = item.get("dimensions") or {}

            positive = [
                signal for signal in signals
                if signal in {
                    "strong_opportunity_signal",
                    "positive_opportunity_signal",
                    "high_evidence_confidence",
                    "positive_dynamics",
                }
            ]
            negative = [
                signal for signal in signals
                if signal in {
                    "weak_opportunity_signal",
                    "negative_dynamics",
                    "dense_competition",
                    "low_evidence_confidence",
                }
            ]

            interpretation = (
                "Есть положительный сигнал по направлению, "
                "но решение зависит от качества доказательств."
            )

            if positive and negative:
                interpretation = (
                    "Сигналы смешанные: потенциал присутствует, "
                    "но есть факторы, ограничивающие уверенность."
                )
            elif negative and not positive:
                interpretation = (
                    "Преимущественно отрицательные сигналы: "
                    "текущее направление не даёт достаточного основания "
                    "для активного действия."
                )
            elif positive:
                interpretation = (
                    "Преимущественно положительные сигналы: "
                    "направление выглядит перспективным при текущем "
                    "уровне доказательств."
                )

            if confidence < 0.55 or missing:
                interpretation += (
                    " Уверенность ограничена неполнотой данных."
                )

            interpretations.append({
                "opportunity_id": item.get("opportunity_id"),
                "title": item.get("title", ""),
                "interpretation": interpretation,
                "positive_signals": positive,
                "negative_signals": negative,
                "signals": signals,
                "strengths": strengths[:8],
                "risks": risks[:8],
                "missing_data": missing[:8],
                "overall_score": score,
                "confidence": confidence,
                "dimensions": dimensions,
            })

        result = {
            "items": interpretations,
            "count": len(interpretations),
        }

        self.context.metadata["signal_interpretation"] = result
        return result

    @staticmethod
    def _safe_score(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value or 0.0)))
        except (TypeError, ValueError):
            return 0.0

    def formulate_hypothesis(
        self,
        analysis: dict[str, Any],
    ) -> DirectorHypothesis | None:
        """
        Turn interpreted signals into a falsifiable strategic hypothesis.

        A hypothesis must explain *why* an opportunity may work and define
        what observation would support or falsify it. It is intentionally
        separate from the later decision/recommendation layers.
        """
        interpretation = analysis.get("signal_interpretation") or self.context.metadata.get(
            "signal_interpretation",
            {},
        )
        items = interpretation.get("items", []) if isinstance(interpretation, dict) else []
        if not items:
            return None

        candidate = max(
            [item for item in items if isinstance(item, dict)],
            key=lambda item: self._safe_score(item.get("overall_score")),
            default=None,
        )
        if candidate is None:
            return None

        title = str(
            candidate.get("title")
            or "Перспективное направление"
        ).strip()
        opportunity_id = candidate.get("opportunity_id")
        signals = [
            str(x) for x in (candidate.get("signals") or []) if str(x).strip()
        ]
        strengths = [
            str(x) for x in (candidate.get("strengths") or []) if str(x).strip()
        ]
        risks = [
            str(x) for x in (candidate.get("risks") or []) if str(x).strip()
        ]
        missing = [
            str(x) for x in (candidate.get("missing_data") or []) if str(x).strip()
        ]
        confidence = self._safe_score(candidate.get("confidence"))

        positive = [
            str(x)
            for x in (candidate.get("positive_signals") or [])
            if str(x).strip()
        ]
        negative = [
            str(x)
            for x in (candidate.get("negative_signals") or [])
            if str(x).strip()
        ]

        if not positive and strengths:
            positive = strengths[:4]

        signal_text = ", ".join(positive[:4]) or "наблюдаемые положительные сигналы"
        statement = (
            f"Если развивать направление «{title}» в формате небольшого теста, "
            f"то оно способно показать устойчивый спрос, потому что {signal_text}."
        )

        if negative:
            rationale = (
                f"Гипотеза основана на положительных сигналах ({', '.join(positive[:3]) or 'есть'}) "
                f"при наличии ограничивающих факторов ({', '.join(negative[:3])})."
            )
        else:
            rationale = (
                f"Гипотеза основана на интерпретации текущих сигналов: "
                f"{', '.join(positive[:4]) or 'положительная совокупная оценка'}."
            )

        test = (
            f"Провести ограниченный тест контента по направлению «{title}» "
            "и сравнить фактическую динамику просмотров и вовлечения "
            "с текущим ориентиром выборки."
        )
        expected = (
            "Направление подтверждается, если тест показывает устойчиво "
            "положительную динамику и вовлечение не ниже текущего ориентира."
        )
        falsification = [
            "Тест не показывает ожидаемой положительной динамики просмотров.",
            "Вовлечение устойчиво ниже текущего ориентира.",
        ]
        if missing:
            falsification.append(
                "После получения недостающих данных ключевые положительные сигналы не подтверждаются."
            )

        evidence: list[dict[str, Any]] = []
        for item in (candidate.get("evidence") or [])[:8]:
            if isinstance(item, dict):
                evidence.append(dict(item))
            elif item:
                evidence.append({"statement": str(item)})

        hypothesis = build_hypothesis(
            title=title,
            statement=statement,
            opportunity_id=str(opportunity_id) if opportunity_id is not None else None,
            rationale=rationale,
            supporting_signals=signals[:8],
            evidence=evidence,
            risks=risks[:8],
            missing_data=missing[:8],
            test=test,
            expected_outcome=expected,
            falsification_criteria=falsification,
            confidence=confidence,
            metadata={
                "overall_score": self._safe_score(candidate.get("overall_score")),
                "positive_signals": positive[:8],
                "negative_signals": negative[:8],
                "source": "director_signal_interpretation",
            },
        )

        self.context.metadata["current_hypothesis"] = hypothesis.to_dict()
        return hypothesis

    # ============================================================
    # DECISION
    # ============================================================

    async def decide(
        self,
        analysis: dict[str, Any] | None = None,
    ) -> DirectorDecision:
        """
        Central strategic decision point.
        """
        if analysis is None:
            analysis = await self.analyze()

        opportunities = list(analysis.get(
            "opportunities",
            self.context.opportunities,
        ) or [])
        all_opportunities = list(opportunities)
        completed = self.state.metadata.get("completed_task_keys", [])
        completed_tasks = set(completed if isinstance(completed, list) else [])
        opportunities = [
            item for item in opportunities
            if self._opportunity_task_key(item) not in completed_tasks
        ]

        # If all current candidates were already handled during this wake,
        # wait for new evidence instead of repeating a recommendation.
        if not opportunities and all_opportunities and completed_tasks:
            return build_decision(
                decision_type=DecisionType.WAIT,
                objective=self.context.objective or "Оценить следующий полезный шаг.",
                rationale="Все доступные направления уже рассмотрены в текущем цикле. Повторять ту же задачу без новых данных не нужно.",
                confidence=0.65,
                next_action="Дождаться новых данных или следующего пробуждения.",
                metadata={"reason": "all_current_opportunities_handled"},
            )

        if not opportunities and self.state.metadata.get("research_task_exhausted"):
            return build_decision(
                decision_type=DecisionType.WAIT,
                objective=self.context.objective or "Оценить следующий полезный шаг.",
                rationale="Доступное исследование уже выполнялось в этом цикле, а новых направлений для полезной работы пока нет.",
                confidence=0.6,
                next_action="Дождаться новых данных или следующего пробуждения.",
                metadata={"reason": "research_already_attempted"},
            )

        # --------------------------------------------------------
        # No evidence => research first.
        # --------------------------------------------------------
        if not opportunities:
            return build_decision(
                decision_type=DecisionType.RESEARCH,
                objective=(
                    self.context.objective
                    or "Исследовать перспективные направления."
                ),
                rationale=(
                    "У меня пока нет достаточной базы возможностей, "
                    "поэтому следующим шагом должно быть исследование."
                ),
                confidence=0.30,
                missing_data=[
                    "Недостаточно исследованных направлений."
                ],
                next_action="Провести исследование YouTube.",
            )

        # --------------------------------------------------------
        # Choose the strongest analytical candidate.
        #
        # IMPORTANT:
        # This is analytical ordering, not a user-facing ranking.
        # Final strategic interpretation can still be delegated to AI.
        # --------------------------------------------------------
        candidate = self._select_candidate(opportunities)

        decision = decide_from_opportunity(
            candidate,
            objective=self.context.objective or "",
        )
        decision.metadata["task_key"] = self._opportunity_task_key(candidate)
        decision.metadata["opportunity_id"] = (
            candidate.get("opportunity_id")
            if isinstance(candidate, dict)
            else getattr(candidate, "opportunity_id", None)
        )

        hypothesis = analysis.get("hypothesis")
        if isinstance(hypothesis, dict):
            decision.metadata["hypothesis_id"] = hypothesis.get("hypothesis_id")
            decision.metadata["hypothesis"] = hypothesis

        # AI may enrich rationale, but does not replace the Director.
        if self.ai_service is not None:
            decision = await self._enrich_decision_with_ai(
                decision,
                analysis,
            )

        return decision

    @staticmethod
    def _opportunity_task_key(item: Any) -> str:
        if isinstance(item, dict):
            identifier = item.get("opportunity_id") or item.get("id")
            title = item.get("title") or item.get("topic") or item.get("name")
        else:
            identifier = getattr(item, "opportunity_id", None) or getattr(item, "id", None)
            title = getattr(item, "title", None) or getattr(item, "topic", None) or getattr(item, "name", None)
        value = identifier or title or repr(item)
        return f"opportunity:{str(value).strip().lower()}"

    def _select_candidate(
        self,
        opportunities: Iterable[Any],
    ) -> Any:
        def score(item: Any) -> float:
            if isinstance(item, dict):
                value = item.get(
                    "overall_score",
                    item.get("score", 0),
                )
            else:
                value = getattr(
                    item,
                    "overall_score",
                    getattr(item, "score", 0),
                )

            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        return max(
            list(opportunities),
            key=score,
        )

    async def _enrich_decision_with_ai(
        self,
        decision: DirectorDecision,
        analysis: dict[str, Any],
    ) -> DirectorDecision:
        """
        AI helps formulate/explain the decision.

        It does not change the Director's architectural authority.
        """
        generator = getattr(
            self.ai_service,
            "generate_decision",
            None,
        )

        if generator is None:
            return decision

        try:
            # AI receives a structured context and returns a structured
            # result. The Director keeps ownership of the decision.
            result = generator(
                context={
                    "decision": decision.to_dict(),
                    "analysis": analysis,
                    "director_context": (
                        self.context.to_ai_decision_dict()
                    ),
                }
            )

            if hasattr(result, "__await__"):
                result = await result

            if isinstance(result, dict):
                if result.get("rationale"):
                    decision.rationale = str(
                        result["rationale"]
                    )

                if result.get("confidence") is not None:
                    decision.confidence = max(
                        0.0,
                        min(
                            1.0,
                            float(result["confidence"]),
                        ),
                    )

                if result.get("next_action"):
                    decision.next_action = str(
                        result["next_action"]
                    )

        except Exception as exc:
            decision.metadata["ai_enrichment_error"] = str(exc)

        return decision

    # ============================================================
    # RECOMMENDATION
    # ============================================================

    def create_recommendation(
        self,
        decision: DirectorDecision,
        *,
        analysis: dict[str, Any] | None = None,
    ) -> DirectorRecommendation:
        """
        Convert a strategic decision into a concise human-facing proposal.
        """
        if analysis is None:
            # Reuse the already-collected context instead of triggering
            # a new (possibly async) analytics pass.
            analysis = {
                "topics": self.context.topics,
                "opportunities": self.context.opportunities,
                "analytics": self.context.analytics,
                "hypothesis": self.context.metadata.get(
                    "current_hypothesis"
                ),
                "signal_interpretation": self.context.metadata.get(
                    "signal_interpretation",
                    {},
                ),
            }

        # A recommendation must be traceable to the hypothesis that
        # produced the decision. This keeps the chain explicit:
        # signals -> interpretation -> hypothesis -> decision -> recommendation.
        hypothesis = analysis.get("hypothesis")
        if not isinstance(hypothesis, dict):
            hypothesis = self.context.metadata.get("current_hypothesis")
        if not isinstance(hypothesis, dict):
            hypothesis = decision.metadata.get("hypothesis")
        if not isinstance(hypothesis, dict):
            hypothesis = None

        target = self._build_recommendation_target(
            analysis,
            decision=decision,
        )

        evidence = self._build_recommendation_evidence(
            analysis,
            decision=decision,
        )

        title = self._recommendation_title(
            target,
            decision,
        )

        summary = self._recommendation_summary(
            target,
            decision,
        )

        proposed_action = (
            decision.next_action
            or (
                hypothesis.get("test")
                if hypothesis
                else None
            )
            or "Обсудить следующий шаг."
        )

        reason = decision.rationale
        if hypothesis:
            hypothesis_rationale = str(
                hypothesis.get("rationale") or ""
            ).strip()
            if hypothesis_rationale:
                reason = (
                    f"{reason} "
                    f"Основание гипотезы: {hypothesis_rationale}"
                ).strip()

        recommendation_metadata = {
            "source": "director_hypothesis",
            "hypothesis_id": (
                hypothesis.get("hypothesis_id")
                if hypothesis
                else None
            ),
            "hypothesis": hypothesis,
            "hypothesis_test": (
                hypothesis.get("test")
                if hypothesis
                else None
            ),
            "expected_outcome": (
                hypothesis.get("expected_outcome")
                if hypothesis
                else None
            ),
            "falsification_criteria": (
                hypothesis.get("falsification_criteria", [])
                if hypothesis
                else []
            ),
        }

        recommendation = create_recommendation(
            title=title,
            summary=summary,
            proposed_action=proposed_action,
            reason=reason,
            confidence=decision.confidence,
            target=target,
            evidence=evidence,
            risks=decision.risks,
            constraints=decision.missing_data,
            decision=decision,
            metadata=recommendation_metadata,
        )

        self.context.recommendations.append(
            recommendation.to_dict()
        )

        self.state.current_recommendation_id = (
            recommendation.recommendation_id
        )

        return recommendation

    def _build_recommendation_target(
        self,
        analysis: dict[str, Any],
        *,
        decision: DirectorDecision | None = None,
    ) -> RecommendationTarget | None:
        opportunities = analysis.get(
            "opportunities",
            [],
        )

        if not opportunities:
            return None

        candidate = self._candidate_for_decision(opportunities, decision)

        if isinstance(candidate, dict):
            title = (
                candidate.get("title")
                or candidate.get("topic")
                or candidate.get("name")
                or "Перспективное направление"
            )

            description = candidate.get(
                "description",
                "",
            )

            audience = candidate.get(
                "audience"
            )

            format_name = candidate.get(
                "format"
            )

        else:
            title = (
                getattr(candidate, "title", None)
                or getattr(candidate, "topic", None)
                or getattr(candidate, "name", None)
                or "Перспективное направление"
            )

            description = getattr(
                candidate,
                "description",
                "",
            )

            audience = getattr(
                candidate,
                "audience",
                None,
            )

            format_name = getattr(
                candidate,
                "format",
                None,
            )

        return RecommendationTarget(
            kind="youtube_direction",
            title=str(title),
            description=str(description or ""),
            audience=(
                str(audience)
                if audience
                else None
            ),
            format=(
                str(format_name)
                if format_name
                else None
            ),
            language="ru",
        )

    def _build_recommendation_evidence(
        self,
        analysis: dict[str, Any],
        *,
        decision: DirectorDecision | None = None,
    ) -> list[RecommendationEvidence]:
        evidence: list[RecommendationEvidence] = []

        opportunities = analysis.get(
            "opportunities",
            [],
        )

        if not opportunities:
            return evidence

        candidate = self._candidate_for_decision(opportunities, decision)

        if isinstance(candidate, dict):
            raw_evidence = candidate.get(
                "evidence",
                [],
            )

            signals = candidate.get(
                "signals",
                [],
            )

        else:
            raw_evidence = getattr(
                candidate,
                "evidence",
                [],
            )

            signals = getattr(
                candidate,
                "signals",
                [],
            )

        for item in list(raw_evidence or [])[:8]:
            if isinstance(item, dict):
                statement = (
                    item.get("statement")
                    or item.get("description")
                    or item.get("text")
                )

                if not statement:
                    continue

                evidence.append(
                    RecommendationEvidence(
                        statement=str(statement),
                        source=item.get("source"),
                        reference_id=item.get(
                            "reference_id"
                        ),
                        strength=float(
                            item.get("strength", 0.5)
                        ),
                    )
                )
            elif item:
                evidence.append(
                    RecommendationEvidence(
                        statement=str(item)
                    )
                )

        for signal in list(signals or [])[:5]:
            if signal:
                evidence.append(
                    RecommendationEvidence(
                        statement=str(signal)
                    )
                )

        return evidence

    def _candidate_for_decision(
        self,
        opportunities: Iterable[Any],
        decision: DirectorDecision | None,
    ) -> Any:
        items = list(opportunities or [])
        target_id = decision.metadata.get("opportunity_id") if decision else None
        if target_id is not None:
            for item in items:
                item_id = item.get("opportunity_id") if isinstance(item, dict) else getattr(item, "opportunity_id", None)
                if str(item_id) == str(target_id):
                    return item
        return self._select_candidate(items)

    def _recommendation_title(
        self,
        target: RecommendationTarget | None,
        decision: DirectorDecision,
    ) -> str:
        if target:
            return f"Предлагаю проверить направление: {target.title}"

        return "Следующий шаг по проекту"

    def _recommendation_summary(
        self,
        target: RecommendationTarget | None,
        decision: DirectorDecision,
    ) -> str:
        if target:
            details = []

            hypothesis = self.context.metadata.get(
                "current_hypothesis"
            )
            if isinstance(hypothesis, dict):
                statement = str(
                    hypothesis.get("statement") or ""
                ).strip()
                if statement:
                    details.append(
                        f"Гипотеза: {statement}"
                    )

            if target.audience:
                details.append(
                    f"Аудитория: {target.audience}"
                )

            if target.format:
                details.append(
                    f"Формат: {target.format}"
                )

            return build_director_message(
                summary=(
                    f"Я вижу потенциал в направлении "
                    f"«{target.title}» и предлагаю не "
                    f"масштабировать его сразу, а сначала "
                    f"проверить небольшим экспериментом."
                ),
                details=details,
                next_step=decision.next_action,
            )

        return build_director_message(
            summary=decision.rationale,
            next_step=decision.next_action,
        )

    # ============================================================
    # FEEDBACK
    # ============================================================

    async def apply_feedback(
        self,
        feedback: DirectorFeedback,
    ) -> None:
        """
        Feedback becomes part of Director context and future memory.

        Persistence uses the existing Memory 2.0 API
        (apply_recommendation_feedback / save_constraint).
        """
        record = feedback_to_memory_record(
            feedback
        )

        self.context.feedback.append(record)

        if feedback.constraint:
            self.context.constraints.append(
                {
                    "type": "user_constraint",
                    "value": feedback.constraint,
                    "source": feedback.feedback_id,
                }
            )

        if feedback.preference:
            self.context.metadata.setdefault(
                "user_preferences",
                [],
            ).append(
                {
                    "value": feedback.preference,
                    "source": feedback.feedback_id,
                }
            )

        if self.memory_service is None:
            return

        # ------------------------------------------------------------
        # Memory 2.0 persistence
        # ------------------------------------------------------------

        try:
            feedback_type = (
                feedback.feedback_type.value
                if hasattr(
                    feedback.feedback_type,
                    "value",
                )
                else str(feedback.feedback_type)
            )

            feedback_payload = {
                "recommendation_id": (
                    feedback.recommendation_id
                ),
                "feedback_type": feedback_type,
                "message": feedback.message,
                "reason": feedback.reason,
                "scope": (
                    feedback.scope.value
                    if hasattr(feedback.scope, "value")
                    else str(feedback.scope)
                ),
                "creates_constraint": bool(
                    feedback.constraint
                ),
                "metadata": dict(feedback.metadata),
            }

            writer = getattr(
                self.memory_service,
                "apply_recommendation_feedback",
                None,
            )

            if writer:
                saved = writer(
                    self.project_id,
                    feedback_payload,
                )

                if hasattr(saved, "__await__"):
                    await saved

            if feedback.constraint:
                constraint_writer = getattr(
                    self.memory_service,
                    "save_constraint",
                    None,
                )

                if constraint_writer:
                    saved_constraint = (
                        constraint_writer(
                            self.project_id,
                            {
                                "title": (
                                    "Ограничение пользователя"
                                ),
                                "description": (
                                    str(
                                        feedback.constraint
                                    )
                                ),
                                "constraint_type": "avoid",
                                "scope": (
                                    feedback.scope.value
                                    if hasattr(
                                        feedback.scope,
                                        "value",
                                    )
                                    else str(
                                        feedback.scope
                                    )
                                ),
                                "status": "active",
                                "reason": str(
                                    feedback.message
                                ),
                                "source_feedback_id": None,
                                "metadata": {
                                    "director_feedback_id": (
                                        feedback.feedback_id
                                    ),
                                },
                            }
                        )
                    )

                    if hasattr(
                        saved_constraint,
                        "__await__",
                    ):
                        await saved_constraint

        except Exception:
            # Feedback must never break the main request flow.
            pass

    # ============================================================
    # AUTONOMY
    # ============================================================

    async def run_autonomous_cycle(
        self,
        *,
        objective: str | None = None,
    ) -> DirectorCycle:
        """
        Start one bounded autonomous wake cycle.
        """
        autonomy = DirectorAutonomy(
            config=self.autonomy_config,
            capabilities=self._autonomy_capabilities,
            inspect=self._autonomy_inspect,
            understand=self._autonomy_understand,
            research=self._autonomy_research,
            analyze=self._autonomy_analyze,
            assess=self._autonomy_assess,
            decide=self._autonomy_decide,
            act=self._autonomy_act,
            recommend=self._autonomy_recommend,
            evaluate=self._autonomy_evaluate,
            learn=self._autonomy_learn,
        )

        logger.info(
            "DIRECTOR WAKE UP: starting autonomous cycle project=%s objective=%s",
            self.project_id,
            objective or self.context.objective,
        )

        cycle = await autonomy.run(
            project_id=self.project_id,
            objective=objective or self.context.objective,
            initial_state=self.state,
        )

        self.last_cycle = cycle
        self.state = cycle.state

        return cycle

    def _autonomy_capabilities(
        self,
        state: DirectorState,
        _: Any,
    ) -> dict[str, Any]:
        return self.discover_capabilities()

    async def _autonomy_inspect(
        self,
        state: DirectorState,
        _: Any,
    ) -> dict[str, Any]:
        context = await self.inspect()
        inventory = context.metadata.get("data_inventory", {})
        logger.info(
            "DIRECTOR STATE UNDERSTOOD: project=%s videos=%s snapshots=%s channels=%s queries=%s research_sets=%s relations=%s missing=%s",
            self.project_id,
            inventory.get("video_count", 0),
            inventory.get("snapshot_count", 0),
            inventory.get("channel_count", 0),
            inventory.get("query_count", 0),
            inventory.get("research_set_count", 0),
            inventory.get("relation_count", 0),
            context.missing_data,
        )

        inventory = context.metadata.get("data_inventory", {})
        project_state = context.metadata.get("project_state", {})
        capabilities = context.metadata.get("capabilities", {})
        recent_research = [
            {
                key: item.get(key)
                for key in ("research_id", "name", "objective", "status", "created_at", "completed_at")
                if key in item
            }
            for item in (context.research_history[-8:] if context.research_history else [])
            if isinstance(item, dict)
        ]
        wake_snapshot = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "project_id": self.project_id,
            "objective": context.objective or state.objective,
            "inventory": {
                "videos": inventory.get("video_count", project_state.get("observation_count", 0)),
                "video_snapshots": inventory.get("snapshot_count", project_state.get("snapshot_count", 0)),
                "search_queries": inventory.get("query_count", project_state.get("coverage", {}).get("stored_search_queries", 0)),
                "research_sets": inventory.get("research_set_count", 0),
                "relations": inventory.get("relation_count", 0),
                "channels": inventory.get("channel_count", 0),
                "niches": inventory.get("niche_count", 0),
            },
            "freshness": project_state.get("freshness", {}),
            "coverage": project_state.get("coverage", {}),
            "quota": project_state.get("quota", {}),
            "hypothesis": context.metadata.get("current_hypothesis", {}),
            "topics_summary": {
                "available": bool(context.topics),
                "keys": list(context.topics.keys())[:20] if isinstance(context.topics, dict) else [],
            },
            "analytics_summary": {
                "available": bool(context.analytics),
                "keys": list(context.analytics.keys())[:20] if isinstance(context.analytics, dict) else [],
            },
            "opportunity_count": len(context.opportunities),
            "recent_research": recent_research,
            "missing_data": list(context.missing_data),
            "available_actions": list(context.available_actions),
            "connected_services": capabilities.get("connected_services", {}),
        }
        state.metadata["wake_snapshot"] = wake_snapshot
        logger.info(
            "DIRECTOR WAKE SNAPSHOT: %s",
            json.dumps(wake_snapshot, ensure_ascii=False, default=str),
        )

        return {
            "evidence_available": state.evidence_available,
            "context": context.to_analysis_dict(),
            "wake_snapshot": wake_snapshot,
        }

    def _autonomy_understand(
        self,
        state: DirectorState,
        _: Any,
    ) -> dict[str, Any]:
        return self.understand()

    async def _autonomy_research(
        self,
        state: DirectorState,
        _: Any,
    ) -> dict[str, Any]:
        task_gaps = None
        task_objective = None
        selected_work_plan_task = None
        if isinstance(_, dict):
            task_gaps = _.get("missing_data")
            task_objective = _.get("objective") or _.get("next_action")
            work_plan = _.get("work_plan")
            if isinstance(work_plan, dict):
                execution_order = work_plan.get("execution_order", [])
                tasks = work_plan.get("tasks", [])
                if execution_order and isinstance(tasks, list):
                    selected_id = execution_order[0]
                    selected_work_plan_task = next(
                        (item for item in tasks if isinstance(item, dict) and item.get("id") == selected_id),
                        None,
                    )
                    if selected_work_plan_task:
                        task_objective = selected_work_plan_task.get("task") or task_objective
                        task_gaps = [
                            selected_work_plan_task.get("task", ""),
                            selected_work_plan_task.get("reason", ""),
                        ]
        elif _ is not None:
            task_gaps = getattr(_, "missing_data", None)
            task_objective = getattr(_, "objective", None) or getattr(_, "next_action", None)

        plan = self.plan_research(
            objective=str(task_objective) if task_objective else None,
            missing_data=task_gaps if isinstance(task_gaps, (list, tuple)) else None,
        )
        if selected_work_plan_task:
            plan.metadata["work_plan_task"] = selected_work_plan_task
            state.metadata["selected_work_plan_task"] = selected_work_plan_task
            logger.info(
                "DIRECTOR SELECTED WORK PLAN TASK: cycle=%s task=%s reason=%s",
                state.cycle_count,
                selected_work_plan_task.get("id"),
                selected_work_plan_task.get("reason", ""),
            )
        query_signature = "|".join(sorted(
            f"{str(getattr(query, 'query', '')).strip().lower()}:{getattr(query, 'language', '')}"
            for query in plan.queries
        ))
        operation_signature = "|".join(sorted(
            str(item.get("operation") or item.get("requirement_key") or "")
            for item in plan.metadata.get("operations", [])
            if isinstance(item, dict)
        ))
        task_key = "research:" + "|".join([
            str(plan.objective or "").strip().lower(),
            query_signature,
            operation_signature,
        ])
        completed_tasks = state.metadata.setdefault("completed_task_keys", [])
        if task_key in completed_tasks:
            state.metadata["research_task_exhausted"] = True
            return {
                "status": "skipped",
                "duplicate_task": True,
                "task_key": task_key,
                "research_plan": plan.to_dict(),
                "missing_data": list(self.context.missing_data),
            }

        state.current_research_id = (
            plan.research_id
        )

        execution: dict[str, Any] = {
            "status": "not_executed",
            "queries_sent": 0,
            "results": [],
        }

        executor = getattr(
            self.research_service,
            "execute",
            None,
        )

        logger.info(
            "DIRECTOR RESEARCH PLAN CREATED: cycle=%s research_id=%s objective=%s query_count=%s queries=%s quota_budget=%s",
            state.cycle_count, plan.research_id, plan.objective,
            len(plan.queries), [q.query for q in plan.queries],
            plan.metadata.get("quota_budget", {}),
        )
        if executor is not None:
            execution = executor(plan)
            if hasattr(execution, "__await__"):
                execution = await execution
        else:
            execution = {
                "status": "blocked",
                "reason": "research_executor_unavailable",
                "queries_planned": len(plan.queries),
                "queries_collected": 0,
            }
        logger.info(
            "DIRECTOR RESEARCH EXECUTION: research_id=%s status=%s queries_planned=%s queries_collected=%s queries_failed=%s quota=%s errors=%s",
            plan.research_id,
            execution.get("status") if isinstance(execution, dict) else "invalid_result",
            execution.get("queries_planned", len(plan.queries)) if isinstance(execution, dict) else len(plan.queries),
            execution.get("queries_collected", 0) if isinstance(execution, dict) else 0,
            execution.get("queries_failed", 0) if isinstance(execution, dict) else 0,
            execution.get("quota") if isinstance(execution, dict) else None,
            execution.get("errors", []) if isinstance(execution, dict) else [],
        )

        data_ingestion: dict[str, Any] = {
            "status": "not_executed",
        }

        # Persisted research results must be ingested even when the
        # research is partial: a partial run still contains usable evidence.
        if (
            isinstance(execution, dict)
            and execution.get("status") in {"completed", "partial"}
            and not execution.get("persisted")
        ):
            # YouTubeResearchExecutor already persists the objects it creates.
            # Do not ingest the same MCP payload a second time: that would
            # re-save the entire in-memory opportunity registry and can exhaust
            # the 512 MiB Render instance.
            ingestor = getattr(
                self.data_service,
                "ingest_research_execution",
                None,
            )

            if ingestor is not None:
                data_ingestion = ingestor(
                    project_id=self.project_id or "default",
                    plan=plan,
                    execution=execution,
                )

                if hasattr(data_ingestion, "__await__"):
                    data_ingestion = await data_ingestion

        # Re-read project state after Research has persisted its DATA.
        # This closes the Research -> Director handoff: the next
        # assessment/analyzer sees the newly collected evidence.
        refreshed_context = await self.inspect()

        research_execution = (
            execution if isinstance(execution, dict) else {}
        )
        self.context.metadata["last_research_execution"] = (
            research_execution
        )
        self.context.metadata["last_research_ingestion"] = (
            data_ingestion
        )
        execution_status = str(research_execution.get("status") or "").lower()
        successful_query_count = int(research_execution.get("queries_collected", 0) or 0)
        # Failed, blocked, and zero-query plans remain retryable.
        if execution_status in {"completed", "partial"} and successful_query_count > 0:
            if task_key not in completed_tasks:
                completed_tasks.append(task_key)
        else:
            logger.warning(
                "DIRECTOR RESEARCH NOT MARKED COMPLETE: task_key=%s status=%s queries_collected=%s reason=%s",
                task_key, execution_status, successful_query_count,
                research_execution.get("reason") or research_execution.get("error"),
            )

        return {
            "task_key": task_key,
            "research_plan": plan.to_dict(),
            "research_execution": research_execution,
            "data_ingestion": data_ingestion,
            "project_state": refreshed_context.metadata.get(
                "project_state",
                {},
            ),
            "missing_data": list(self.context.missing_data),
        }

    async def _autonomy_analyze(
        self,
        state: DirectorState,
        _: Any,
    ) -> dict[str, Any]:
        return await self.analyze()

    def _autonomy_assess(
        self,
        state: DirectorState,
        payload: Any,
    ) -> dict[str, Any]:
        # Assessment runs before Analytics. Only raw research/data gaps
        # belong here; topics/opportunities are Analytics outputs.
        self._refresh_project_state()

        missing = list(self.context.missing_data or [])

        # Research must precede Analytics when the Director has identified
        # missing raw/structural evidence. Do not let existing observations
        # make the evidence look sufficient while the research inventory is
        # still incomplete.
        # Empty tables are not evidence that this particular task is blocked.
        # Task-specific gaps are evaluated against the selected opportunity.
        project_state = self.context.metadata.get("project_state", {})
        freshness = project_state.get("freshness", {}) if isinstance(project_state, dict) else {}
        coverage = project_state.get("coverage", {}) if isinstance(project_state, dict) else {}
        quota = project_state.get("quota", {}) if isinstance(project_state, dict) else {}
        freshness_status = freshness.get("status", "unknown")
        if freshness_status != "fresh":
            missing.append(
                "Обновить метрики YouTube: свежесть выборки "
                + ("неизвестна." if freshness_status == "unknown" else "ниже порога 24 часа.")
            )

        quota_remaining = int(quota.get("remaining_units_today", 0) or 0)
        estimated_cost = int(quota.get("estimated_other_units_per_search", 1) or 1)
        search_remaining = int(quota.get("search_calls_remaining", 0) or 0)
        if quota_remaining < estimated_cost or search_remaining < 1:
            missing.append("Исчерпан отдельный лимит поисковых вызовов YouTube или общий бюджет единиц API.")

        stored_query_count = int(coverage.get("stored_search_queries", 0) or 0)
        if stored_query_count < 12:
            missing.append(
                f"Расширить широкое покрытие YouTube: сохранено поисковых запросов {stored_query_count}/12 для первичного сравнения направлений."
            )
        sufficient = (
            bool(self.state.evidence_sufficient)
            and freshness_status == "fresh"
            and stored_query_count >= 12
        )
        if quota_remaining < estimated_cost or search_remaining < 1:
            sufficient = True  # Research is unavailable; analyze what exists and log the hard stop.

        hypothesis = self.context.metadata.get("current_hypothesis")
        hypothesis_status = (
            hypothesis.get("status", "unvalidated")
            if isinstance(hypothesis, dict) else "not_formulated"
        )
        work_plan = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cycle": state.cycle_count,
            "goal": self.context.objective or "Найти и проверить перспективные направления YouTube.",
            "basis": {
                "video_count": project_state.get("observation_count", 0),
                "snapshot_count": project_state.get("snapshot_count", 0),
                "data_inventory": self.context.metadata.get("data_inventory", {}),
                "available_actions": list(self.context.available_actions),
                "connected_services": self.context.metadata.get("capabilities", {}).get("connected_services", {}),
                "freshness": freshness,
                "coverage": coverage,
                "hypothesis_status": hypothesis_status,
                "hypothesis": self.context.metadata.get("current_hypothesis", {}),
                "recent_research": self.context.research_history[-8:],
                "quota": quota,
                "missing_data": list(dict.fromkeys(missing)),
            },
            "tasks": [
                {
                    "id": "refresh_evidence",
                    "task": "Получить свежие метрики YouTube и повторные измерения по уже найденным видео.",
                    "status": ("required" if freshness_status != "fresh" else "satisfied") if getattr(self.research_service, "refresh_existing_video_stats", None) else ("blocked" if freshness_status != "fresh" else "satisfied"),
                    "reason": f"freshness={freshness_status}; refresh_existing_video_stats_available={bool(getattr(self.research_service, 'refresh_existing_video_stats', None))}",
                },
                {
                    "id": "discover_broadly",
                    "task": "Искать новые направления широко — по разным темам, языкам, регионам и форматам, а не только проверять прежние гипотезы.",
                    "status": "required" if coverage.get("stored_search_queries", 0) < 12 else "next",
                    "reason": "Сопоставить новые поисковые результаты с текущей базой.",
                },
                {
                    "id": "validate_hypotheses",
                    "task": "Сформулировать проверяемые гипотезы, собрать сравнимые доказательства и обновить статус каждой гипотезы.",
                    "status": "required" if hypothesis_status in {"not_formulated", "unvalidated", "provisional"} else "next",
                    "reason": f"hypothesis_status={hypothesis_status}",
                },
                {
                    "id": "persist_and_reinspect",
                    "task": "Сохранить поисковые запросы, результаты и снимки метрик; перечитать состояние после исследования.",
                    "status": "required",
                    "reason": "Каждый выполненный поиск должен оставлять проверяемый след.",
                },
                {
                    "id": "use_daily_quota",
                    "task": "Продолжать полезные исследования, пока хватает измеряемого дневного бюджета и доступен MCP.",
                    "status": "required" if quota_remaining >= estimated_cost and search_remaining >= 1 and self.context.metadata.get("capabilities", {}).get("connected_services", {}).get("research", False) else "blocked",
                    "reason": f"search_calls_remaining={search_remaining}; other_units_remaining={quota_remaining}; research_service={self.context.metadata.get('capabilities', {}).get('connected_services', {}).get('research', False)}",
                },
            ],
        }
        work_plan["execution_order"] = [task["id"] for task in work_plan["tasks"] if task.get("status") == "required"]
        work_plan["blockers"] = [{"task_id": task["id"], "reason": task.get("reason", "")} for task in work_plan["tasks"] if task.get("status") == "blocked"]
        work_plan["wake_snapshot"] = state.metadata.get("wake_snapshot", {})
        state.metadata["project_assessment"] = work_plan["basis"]
        state.metadata["work_plan"] = work_plan
        logger.info("DIRECTOR PROJECT ASSESSMENT: %s", json.dumps(work_plan["basis"], ensure_ascii=False, default=str))
        logger.info("DIRECTOR WORK PLAN: %s", json.dumps(work_plan, ensure_ascii=False, default=str))

        return {
            "evidence_sufficient": sufficient,
            "missing_data": list(dict.fromkeys(missing)),
            "project_state": project_state,
            "work_plan": work_plan,
        }

    async def _autonomy_decide(
        self,
        state: DirectorState,
        payload: Any,
    ) -> dict[str, Any]:
        if isinstance(payload, dict):
            analysis = payload
        else:
            analysis = await self.analyze()

        decision = await self.decide(
            analysis
        )

        return decision.to_dict()

    def _autonomy_act(
        self,
        state: DirectorState,
        decision: Any,
    ) -> Any:
        """
        External production/execution will be connected later.

        For now the Director deliberately does not invent an executor.
        """
        return {
            "status": "awaiting_executor",
            "decision": decision,
        }

    def _autonomy_recommend(
        self,
        state: DirectorState,
        decision: Any,
    ) -> dict[str, Any]:
        if isinstance(decision, dict):
            decision_object = DirectorDecision(
                **self._decision_kwargs(
                    decision
                )
            )
        else:
            decision_object = decision

        recommendation = self.create_recommendation(
            decision_object
        )

        self.last_result = DirectorResult(
            status=DirectorStatus.WAITING,
            phase=DirectorPhase.RECOMMEND,
            message=recommendation.summary,
            decision=decision_object,
            recommendation=recommendation,
        )

        return recommendation.to_dict()

    def _decision_kwargs(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Convert serialized decision back to the current dataclass.

        Kept deliberately defensive because autonomy may later cross
        persistence/API boundaries.
        """
        from .decision import (
            DecisionStatus,
            DecisionType,
            DecisionEvidence,
        )

        evidence = []

        for item in data.get("evidence", []) or []:
            if isinstance(item, DecisionEvidence):
                evidence.append(item)
            elif isinstance(item, dict):
                evidence.append(
                    DecisionEvidence(
                        source=str(
                            item.get("source", "")
                        ),
                        statement=str(
                            item.get("statement", "")
                        ),
                        strength=float(
                            item.get("strength", 0.5)
                        ),
                        reference_id=item.get(
                            "reference_id"
                        ),
                        metadata=item.get(
                            "metadata",
                            {},
                        ),
                    )
                )

        decision_type = data.get(
            "decision_type",
            DecisionType.NONE,
        )

        if not isinstance(
            decision_type,
            DecisionType,
        ):
            decision_type = DecisionType(
                decision_type
            )

        status = data.get(
            "status",
            DecisionStatus.PROPOSED,
        )

        if not isinstance(
            status,
            DecisionStatus,
        ):
            status = DecisionStatus(status)

        return {
            "decision_id": data.get(
                "decision_id"
            ),
            "decision_type": decision_type,
            "status": status,
            "objective": data.get(
                "objective",
                "",
            ),
            "rationale": data.get(
                "rationale",
                "",
            ),
            "confidence": data.get(
                "confidence",
                0.0,
            ),
            "opportunity_score": data.get(
                "opportunity_score"
            ),
            "applicability_score": data.get(
                "applicability_score"
            ),
            "evidence": evidence,
            "risks": data.get(
                "risks",
                [],
            ),
            "missing_data": data.get(
                "missing_data",
                [],
            ),
            "next_action": data.get(
                "next_action"
            ),
            "created_at": data.get(
                "created_at"
            ),
            "metadata": data.get(
                "metadata",
                {},
            ),
        }

    def _autonomy_evaluate(
        self,
        state: DirectorState,
        result: Any,
    ) -> dict[str, Any]:
        return {
            "result_available": result is not None,
            "result": result,
            "needs_followup": False,
        }

    async def _autonomy_learn(
        self,
        state: DirectorState,
        evaluation: Any,
    ) -> Any:
        """
        Final learning hook for the autonomous cycle.

        Persistence of the complete cycle is owned by the server
        orchestration so run_id, decision_id, recommendation_id and
        result_id are created in one linked persistence flow.
        """
        return {
            "evaluation": evaluation,
            "persisted_by": "cycle_orchestration",
        }

    # ============================================================
    # PUBLIC ONE-STEP API
    # ============================================================

    async def run_once(
        self,
        *,
        objective: str | None = None,
    ) -> DirectorResult:
        """
        One explicit Director decision cycle.

        This is the safe bridge that will later replace the old
        large /director/run orchestration in server.py.
        """
        try:
            if objective:
                self.context.objective = objective

            self.state.status = CycleStatus.RUNNING
            self.state.phase = DirectorPhase.INSPECT

            await self.inspect()
            understanding = self.understand()

            if not self.state.evidence_available:
                self.state.status = CycleStatus.RUNNING
                self.state.phase = DirectorPhase.RESEARCH

                plan = self.plan_research(
                    objective=objective
                )

                result = DirectorResult(
                    status=DirectorStatus.RESEARCHING,
                    phase=DirectorPhase.RESEARCH,
                    message=(
                        "Данных пока недостаточно. "
                        "Я сформировал следующий этап исследования."
                    ),
                    research_plan=plan,
                    data={
                        "understanding": understanding,
                    },
                )

                self.last_result = result
                return result

            self.state.status = CycleStatus.RUNNING
            self.state.phase = DirectorPhase.ANALYZE

            analysis = await self.analyze()

            self.state.status = CycleStatus.RUNNING
            self.state.phase = DirectorPhase.DECIDE

            decision = await self.decide(
                analysis
            )

            if decision.decision_type in {
                DecisionType.RESEARCH,
            }:
                self.state.status = CycleStatus.RUNNING
                self.state.phase = DirectorPhase.RESEARCH

                plan = self.plan_research(
                    objective=objective
                )

                result = DirectorResult(
                    status=DirectorStatus.RESEARCHING,
                    phase=DirectorPhase.RESEARCH,
                    message=(
                        "Анализ показал, что нужно ещё "
                        "проверить данные перед решением."
                    ),
                    decision=decision,
                    research_plan=plan,
                )

                self.last_result = result
                return result

            if decision.decision_type in {
                DecisionType.WAIT,
                DecisionType.SLEEP,
                DecisionType.NONE,
            }:
                self.state.status = CycleStatus.SLEEPING
                self.state.phase = DirectorPhase.SLEEP

                result = DirectorResult(
                    status=DirectorStatus.SLEEPING,
                    phase=DirectorPhase.SLEEP,
                    message=(
                        "Сейчас нет достаточного основания "
                        "для нового действия. Жду новых данных."
                    ),
                    decision=decision,
                )

                self.last_result = result
                return result

            self.state.status = CycleStatus.WAITING
            self.state.phase = DirectorPhase.RECOMMEND

            recommendation = self.create_recommendation(
                decision,
                analysis=analysis,
            )

            result = DirectorResult(
                status=DirectorStatus.WAITING,
                phase=DirectorPhase.RECOMMEND,
                message=recommendation.summary,
                decision=decision,
                recommendation=recommendation,
                data={
                    "analysis": analysis,
                },
            )

            self.last_result = result

            return result

        except Exception as exc:
            self.state.status = CycleStatus.ERROR
            self.state.phase = DirectorPhase.ERROR

            result = DirectorResult(
                status=DirectorStatus.ERROR,
                phase=DirectorPhase.ERROR,
                message=(
                    "Во время работы Директора произошла ошибка. "
                    "Попробуйте повторить запрос позже."
                ),
                data={
                    "error": str(exc),
                },
            )

            self.last_result = result
            return result

    # ============================================================
    # STATUS
    # ============================================================

    def status(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "mode": self.mode.value,
            "status": self.state.status.value,
            "phase": self.state.phase.value,
            "objective": self.context.objective,
            "evidence_available": self.state.evidence_available,
            "evidence_sufficient": self.state.evidence_sufficient,
            "current_research_id": self.state.current_research_id,
            "current_decision_id": self.state.current_decision_id,
            "current_recommendation_id": (
                self.state.current_recommendation_id
            ),
            "cycle_count": self.state.cycle_count,
            "actions_taken": self.state.actions_taken,
            "sleep_reason": self.state.sleep_reason,
        }


def create_director(
    *,
    project_id: str | None = None,
    mode: DirectorMode = DirectorMode.MANUAL,
    **services: Any,
) -> Director:
    """
    Factory for the central Valery object.
    """
    return Director(
        project_id=project_id,
        mode=mode,
        **services,
    )
