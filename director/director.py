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

        self.state.evidence_available = bool(
            self.context.observations
            or self.context.analytics
            or self.context.topics
            or self.context.opportunities
        )

        return self.context

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

        return {
            "objective": objective,
            "evidence_available": self.state.evidence_available,
            "observations_count": len(
                self.context.observations
            ),
            "topics_available": bool(
                self.context.topics
            ),
            "opportunities_available": bool(
                self.context.opportunities
            ),
            "missing_data": list(
                self.context.missing_data
            ),
            "constraints": list(
                self.context.constraints
            ),
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
            }

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

        recommendation = create_recommendation(
            title=title,
            summary=summary,
            proposed_action=(
                decision.next_action
                or "Обсудить следующий шаг."
            ),
            reason=decision.rationale,
            confidence=decision.confidence,
            target=target,
            evidence=evidence,
            risks=decision.risks,
            constraints=decision.missing_data,
            decision=decision,
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

    def _autonomy_research(
        self,
        state: DirectorState,
        _: Any,
    ) -> dict[str, Any]:
        plan = self.plan_research()

        state.current_research_id = (
            plan.research_id
        )

        return {
            "research_plan": plan.to_dict(),
            "missing_data": [
                gap.description
                for gap in plan.gaps
            ],
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
        # Assessment happens before analysis in the autonomous loop.
        # At this point the authoritative evidence flag comes from inspect().
        # Do not require opportunities yet: analytics creates them later.
        missing = list(
            self.context.missing_data
            or []
        )

        sufficient = bool(
            state.evidence_available
            and not missing
        )

        return {
            "evidence_sufficient": sufficient,
            "missing_data": missing,
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
