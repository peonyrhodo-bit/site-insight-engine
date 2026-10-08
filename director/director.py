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

        require("videos", "Видео для первичной картины спроса, тем и результатов.", "critical")
        require("video_snapshots", "История метрик видео для определения скорости и динамики роста.", "high", needed_when=inventory_counts["videos"] > 0)
        require("queries", "Сохранённые поисковые запросы, показывающие что именно уже искали.", "high")
        require("research_sets", "История исследований, чтобы не повторять уже выполненную работу.", "high")
        require("relations", "Связи между исследованиями, запросами, видео, результатами и решениями.", "medium")
        require("channels", "Сущности каналов для оценки конкуренции и распределения результата.", "high", needed_when=inventory_counts["videos"] > 0)
        require("channel_snapshots", "История каналов для оценки роста каналов и конкурентной динамики.", "medium", needed_when=inventory_counts["channels"] > 0)
        require("niches", "Явные сущности ниш/направлений, которые можно сравнивать между собой.", "critical", needed_when=inventory_counts["videos"] > 0)
        require("niche_snapshots", "История ниш для оценки роста, конкуренции и изменения opportunity.", "high", needed_when=inventory_counts["niches"] > 0)

        for requirement in requirements:
            if requirement["needed_now"]:
                gaps.append(f"{requirement['description']} (отсутствует: {requirement['key']}).")

        if observation_count > 0 and metric_observations == 0:
            gaps.append("У сохранённых видео нет доступных числовых метрик.")

        if observation_count > 0 and velocity_observations == 0:
            gaps.append("Нет метрик скорости роста (views/hour или эквивалента).")

        self.context.missing_data = gaps
        self.state.evidence_available = observation_count > 0
        self.state.evidence_sufficient = (
            observation_count > 0
            and metric_observations > 0
            and velocity_observations > 0
        )

        self.context.metadata["data_requirements"] = requirements
        self.context.metadata["project_state"] = {
            "observation_count": observation_count,
            "snapshot_count": snapshot_count,
            "metric_observation_count": metric_observations,
            "velocity_observation_count": velocity_observations,
            "inventory": inventory_counts,
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
                result = planner(
                    objective=objective,
                    context=self.context.to_dict(),
                )

                if isinstance(result, ResearchPlan):
                    return result

        return plan_next_research(
            objective=objective,
            missing_data=self.context.missing_data,
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
                    context=self.context.to_dict()
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

        opportunities = analysis.get(
            "opportunities",
            self.context.opportunities,
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
                        self.context.to_dict()
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
            analysis
        )

        evidence = self._build_recommendation_evidence(
            analysis
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
    ) -> RecommendationTarget | None:
        opportunities = analysis.get(
            "opportunities",
            [],
        )

        if not opportunities:
            return None

        candidate = self._select_candidate(
            opportunities
        )

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
    ) -> list[RecommendationEvidence]:
        evidence: list[RecommendationEvidence] = []

        opportunities = analysis.get(
            "opportunities",
            [],
        )

        if not opportunities:
            return evidence

        candidate = self._select_candidate(
            opportunities
        )

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

        return {
            "evidence_available": state.evidence_available,
            "context": context.to_dict(),
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
        plan = self.plan_research()

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

        if executor is not None:
            execution = executor(plan)

            if hasattr(execution, "__await__"):
                execution = await execution

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

        return {
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
        sufficient = bool(
            self.state.evidence_sufficient
            and not missing
        )

        return {
            "evidence_sufficient": sufficient,
            "missing_data": missing,
            "project_state": self.context.metadata.get(
                "project_state",
                {},
            ),
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
