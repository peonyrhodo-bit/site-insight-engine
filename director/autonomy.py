"""
Director autonomous cycle.

The autonomous loop is intentionally bounded and state-driven.
It must never research forever or execute uncontrolled actions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from uuid import uuid4
import logging


logger = logging.getLogger(__name__)


class DirectorPhase(str, Enum):
    SLEEP = "sleep"
    WAKE = "wake"
    CAPABILITIES = "capabilities"
    INSPECT = "inspect"
    UNDERSTAND = "understand"
    RESEARCH = "research"
    ANALYZE = "analyze"
    ASSESS = "assess"
    DECIDE = "decide"
    ACT = "act"
    RECOMMEND = "recommend"
    WAIT = "wait"
    EVALUATE = "evaluate"
    LEARN = "learn"
    COMPLETE = "complete"
    ERROR = "error"


class CycleStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    SLEEPING = "sleeping"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class DirectorState:
    project_id: str | None = None
    phase: DirectorPhase = DirectorPhase.SLEEP
    status: CycleStatus = CycleStatus.IDLE

    objective: str | None = None

    current_research_id: str | None = None
    current_decision_id: str | None = None
    current_recommendation_id: str | None = None

    last_action: str | None = None
    last_result: Any = None

    evidence_available: bool = False
    evidence_sufficient: bool = False

    cycle_count: int = 0
    actions_taken: int = 0

    sleep_reason: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CycleEvent:
    event_id: str
    phase: DirectorPhase
    event: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AutonomyConfig:
    enabled: bool = False
    max_steps_per_cycle: int = 16
    max_research_steps: int = 2
    max_action_steps: int = 3
    allow_external_actions: bool = False
    sleep_after_recommendation: bool = True
    sleep_after_insufficient_data: bool = False


@dataclass
class DirectorCycle:
    cycle_id: str
    status: CycleStatus
    state: DirectorState
    events: list[CycleEvent] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DirectorAutonomy:
    """
    Orchestrates the Director lifecycle.

    The actual intelligence is injected through callbacks.
    This prevents autonomy.py from becoming a second Director.
    """

    def __init__(
        self,
        *,
        config: AutonomyConfig | None = None,
        capabilities: Callable[[DirectorState, Any], Any] | None = None,
        inspect: Callable[[DirectorState], Any] | None = None,
        understand: Callable[[DirectorState, Any], Any] | None = None,
        research: Callable[[DirectorState, Any], Any] | None = None,
        analyze: Callable[[DirectorState, Any], Any] | None = None,
        assess: Callable[[DirectorState, Any], Any] | None = None,
        decide: Callable[[DirectorState, Any], Any] | None = None,
        act: Callable[[DirectorState, Any], Any] | None = None,
        recommend: Callable[[DirectorState, Any], Any] | None = None,
        evaluate: Callable[[DirectorState, Any], Any] | None = None,
        learn: Callable[[DirectorState, Any], Any] | None = None,
    ) -> None:
        self.config = config or AutonomyConfig()

        self.capabilities_handler = capabilities
        self.inspect_handler = inspect
        self.understand_handler = understand
        self.research_handler = research
        self.analyze_handler = analyze
        self.assess_handler = assess
        self.decide_handler = decide
        self.act_handler = act
        self.recommend_handler = recommend
        self.evaluate_handler = evaluate
        self.learn_handler = learn

    def _event(
        self,
        cycle: DirectorCycle,
        phase: DirectorPhase,
        event: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        cycle.events.append(
            CycleEvent(
                event_id=f"evt_{uuid4().hex[:12]}",
                phase=phase,
                event=event,
                message=message,
                data=dict(data or {}),
            )
        )

    def _set_phase(
        self,
        cycle: DirectorCycle,
        phase: DirectorPhase,
        message: str,
    ) -> None:
        cycle.state.phase = phase

        self._event(
            cycle,
            phase,
            "phase_changed",
            message,
        )

    async def _safe_call(
        self,
        handler: Callable | None,
        state: DirectorState,
        payload: Any,
    ) -> Any:
        if handler is None:
            return None

        handler_name = getattr(handler, "__name__", handler.__class__.__name__)
        logger.info(
            "DIRECTOR STEP START: handler=%s phase=%s cycle=%s",
            handler_name,
            state.phase.value,
            state.cycle_count,
        )

        try:
            result = handler(state, payload)

            if hasattr(result, "__await__"):
                result = await result

            logger.info(
                "DIRECTOR STEP FINISH: handler=%s phase=%s cycle=%s",
                handler_name,
                state.phase.value,
                state.cycle_count,
            )
            return result
        except Exception:
            logger.exception(
                "DIRECTOR STEP FAILED: handler=%s phase=%s cycle=%s",
                handler_name,
                state.phase.value,
                state.cycle_count,
            )
            raise

    async def run(
        self,
        *,
        project_id: str | None = None,
        objective: str | None = None,
        initial_state: DirectorState | None = None,
    ) -> DirectorCycle:
        cycle = DirectorCycle(
            cycle_id=f"cycle_{uuid4().hex[:12]}",
            status=CycleStatus.RUNNING,
            state=initial_state
            or DirectorState(),
        )

        cycle.state.project_id = (
            project_id or cycle.state.project_id
        )
        cycle.state.objective = (
            objective or cycle.state.objective
        )
        cycle.state.status = CycleStatus.RUNNING
        cycle.state.cycle_count += 1

        try:
            return await self._run_cycle(cycle)
        except Exception as exc:
            cycle.status = CycleStatus.ERROR
            cycle.state.status = CycleStatus.ERROR
            cycle.state.phase = DirectorPhase.ERROR

            self._event(
                cycle,
                DirectorPhase.ERROR,
                "cycle_error",
                f"Цикл завершился с ошибкой: {exc}",
            )

            cycle.finished_at = datetime.now(
                timezone.utc
            ).isoformat()

            return cycle

    async def _run_cycle(
        self,
        cycle: DirectorCycle,
    ) -> DirectorCycle:
        steps = 0
        research_steps = 0
        action_steps = 0

        # ---------------------------------------------------------
        # WAKE
        # ---------------------------------------------------------
        self._set_phase(
            cycle,
            DirectorPhase.WAKE,
            "Валерий проснулся и проверяет состояние проекта.",
        )

        # ---------------------------------------------------------
        # CAPABILITIES
        # ---------------------------------------------------------
        self._set_phase(
            cycle,
            DirectorPhase.CAPABILITIES,
            "Проверяю, какие возможности, ресурсы и разрешения доступны сейчас.",
        )

        capabilities = await self._safe_call(
            self.capabilities_handler,
            cycle.state,
            None,
        )
        steps += 1
        if isinstance(capabilities, dict):
            cycle.state.metadata["capabilities"] = capabilities

        # ---------------------------------------------------------
        # INSPECT
        # ---------------------------------------------------------
        self._set_phase(
            cycle,
            DirectorPhase.INSPECT,
            "Проверяю текущее состояние проекта.",
        )

        state_data = await self._safe_call(
            self.inspect_handler,
            cycle.state,
            None,
        )

        steps += 1

        if state_data is None:
            state_data = {}

        cycle.state.evidence_available = bool(
            state_data.get("evidence_available", False)
            if isinstance(state_data, dict)
            else False
        )

        # ---------------------------------------------------------
        # UNDERSTAND
        # ---------------------------------------------------------
        self._set_phase(
            cycle,
            DirectorPhase.UNDERSTAND,
            "Определяю, на каком этапе сейчас находится задача.",
        )

        understanding = await self._safe_call(
            self.understand_handler,
            cycle.state,
            state_data,
        )

        steps += 1

        if understanding is None:
            understanding = state_data

        # ---------------------------------------------------------
        # MAIN LOOP
        # ---------------------------------------------------------
        while steps < self.config.max_steps_per_cycle:
            if research_steps >= self.config.max_research_steps:
                cycle.state.metadata["research_limit_reached"] = True

            # -----------------------------------------------------
            # ASSESS
            # -----------------------------------------------------
            self._set_phase(
                cycle,
                DirectorPhase.ASSESS,
                "Оцениваю, достаточно ли текущих данных.",
            )

            assessment = await self._safe_call(
                self.assess_handler,
                cycle.state,
                understanding,
            )

            steps += 1

            sufficient = False

            if isinstance(assessment, dict):
                sufficient = bool(
                    assessment.get(
                        "evidence_sufficient",
                        assessment.get("sufficient", False),
                    )
                )

            cycle.state.evidence_sufficient = sufficient

            # -----------------------------------------------------
            # RESEARCH
            # -----------------------------------------------------
            if not sufficient:
                if research_steps < self.config.max_research_steps:
                    self._set_phase(
                        cycle,
                        DirectorPhase.RESEARCH,
                        "Данных пока недостаточно — планирую следующий этап исследования.",
                    )

                    research_result = await self._safe_call(
                        self.research_handler,
                        cycle.state,
                        assessment,
                    )

                    research_steps += 1
                    steps += 1

                    cycle.state.last_action = "research"
                    cycle.state.actions_taken += 1
                    cycle.state.last_result = research_result

                    if research_result is not None:
                        understanding = research_result

                    continue

                # We have researched enough for this wake cycle.
                self._set_phase(
                    cycle,
                    DirectorPhase.WAIT,
                    "В рамках текущего цикла дополнительных данных получить не удалось.",
                )

                cycle.state.status = CycleStatus.WAITING
                cycle.state.sleep_reason = (
                    "research_limit_reached"
                )

                cycle.status = CycleStatus.WAITING
                break

            # -----------------------------------------------------
            # ANALYZE
            # -----------------------------------------------------
            self._set_phase(
                cycle,
                DirectorPhase.ANALYZE,
                "Анализирую собранные данные.",
            )

            analysis = await self._safe_call(
                self.analyze_handler,
                cycle.state,
                understanding,
            )

            steps += 1

            if analysis is not None:
                understanding = analysis

            # -----------------------------------------------------
            # DECIDE
            # -----------------------------------------------------
            self._set_phase(
                cycle,
                DirectorPhase.DECIDE,
                "Принимаю решение о следующем шаге.",
            )

            decision = await self._safe_call(
                self.decide_handler,
                cycle.state,
                understanding,
            )

            steps += 1

            if decision is None:
                self._set_phase(
                    cycle,
                    DirectorPhase.WAIT,
                    "Решение не сформировано — останавливаю цикл.",
                )

                cycle.status = CycleStatus.WAITING
                cycle.state.status = CycleStatus.WAITING
                cycle.state.sleep_reason = "no_decision"
                break

            decision_type = None

            if isinstance(decision, dict):
                decision_type = decision.get("decision_type")
                cycle.state.current_decision_id = decision.get(
                    "decision_id"
                )
            else:
                decision_type = getattr(
                    decision,
                    "decision_type",
                    None,
                )
                cycle.state.current_decision_id = getattr(
                    decision,
                    "decision_id",
                    None,
                )

            decision_type = (
                getattr(decision_type, "value", decision_type)
            )

            # -----------------------------------------------------
            # WAIT / SLEEP
            # -----------------------------------------------------
            if decision_type in {
                "wait",
                "sleep",
                "none",
                None,
            }:
                self._set_phase(
                    cycle,
                    DirectorPhase.SLEEP,
                    "Сейчас полезнее остановиться и дождаться новых данных.",
                )

                cycle.status = CycleStatus.SLEEPING
                cycle.state.status = CycleStatus.SLEEPING
                cycle.state.sleep_reason = (
                    "decision_requires_wait"
                )
                break

            # -----------------------------------------------------
            # RECOMMEND
            # -----------------------------------------------------
            if decision_type in {
                "recommend",
                "test",
                "create",
                "publish",
                "ask_user",
            }:
                self._set_phase(
                    cycle,
                    DirectorPhase.RECOMMEND,
                    "Формирую понятное предложение для пользователя.",
                )

                recommendation = await self._safe_call(
                    self.recommend_handler,
                    cycle.state,
                    decision,
                )

                steps += 1
                cycle.state.last_action = "recommend"
                cycle.state.actions_taken += 1

                if recommendation is not None:
                    cycle.state.current_recommendation_id = (
                        recommendation.get("recommendation_id")
                        if isinstance(recommendation, dict)
                        else getattr(
                            recommendation,
                            "recommendation_id",
                            None,
                        )
                    )

                cycle.state.last_result = recommendation

                if self.config.sleep_after_recommendation:
                    self._set_phase(
                        cycle,
                        DirectorPhase.SLEEP,
                        "Рекомендация сформирована. Жду решения пользователя.",
                    )

                    cycle.status = CycleStatus.WAITING
                    cycle.state.status = CycleStatus.WAITING
                    cycle.state.sleep_reason = (
                        "waiting_for_user"
                    )
                    break

            # -----------------------------------------------------
            # ACT
            # -----------------------------------------------------
            elif self.config.allow_external_actions:
                if action_steps >= self.config.max_action_steps:
                    self._set_phase(
                        cycle,
                        DirectorPhase.WAIT,
                        "Достигнут лимит действий текущего цикла.",
                    )

                    cycle.status = CycleStatus.WAITING
                    cycle.state.status = CycleStatus.WAITING
                    cycle.state.sleep_reason = (
                        "action_limit_reached"
                    )
                    break

                self._set_phase(
                    cycle,
                    DirectorPhase.ACT,
                    "Выполняю разрешённое действие.",
                )

                result = await self._safe_call(
                    self.act_handler,
                    cycle.state,
                    decision,
                )

                action_steps += 1
                steps += 1

                cycle.state.last_action = decision_type
                cycle.state.actions_taken += 1
                cycle.state.last_result = result

                # Evaluate action result.
                self._set_phase(
                    cycle,
                    DirectorPhase.EVALUATE,
                    "Проверяю результат выполненного действия.",
                )

                evaluation = await self._safe_call(
                    self.evaluate_handler,
                    cycle.state,
                    result,
                )

                steps += 1

                self._set_phase(
                    cycle,
                    DirectorPhase.LEARN,
                    "Фиксирую результат для следующего цикла.",
                )

                await self._safe_call(
                    self.learn_handler,
                    cycle.state,
                    evaluation,
                )

                steps += 1

                if evaluation is not None:
                    understanding = evaluation

                continue

            else:
                self._set_phase(
                    cycle,
                    DirectorPhase.RECOMMEND,
                    "Действие требует внешнего исполнения, поэтому формирую предложение.",
                )

                recommendation = await self._safe_call(
                    self.recommend_handler,
                    cycle.state,
                    decision,
                )

                steps += 1
                cycle.state.last_action = "recommend"
                cycle.state.actions_taken += 1
                cycle.state.last_result = recommendation

                self._set_phase(
                    cycle,
                    DirectorPhase.WAIT,
                    "Жду разрешения или результата.",
                )

                cycle.status = CycleStatus.WAITING
                cycle.state.status = CycleStatus.WAITING
                cycle.state.sleep_reason = (
                    "external_action_requires_confirmation"
                )
                break

        else:
            cycle.status = CycleStatus.WAITING
            cycle.state.status = CycleStatus.WAITING
            cycle.state.sleep_reason = "step_limit_reached"

        if cycle.status == CycleStatus.RUNNING:
            cycle.status = CycleStatus.COMPLETED
            cycle.state.status = CycleStatus.COMPLETED

        cycle.finished_at = datetime.now(
            timezone.utc
        ).isoformat()

        return cycle


def create_autonomous_director(
    *,
    enabled: bool = False,
    **handlers: Callable | None,
) -> DirectorAutonomy:
    config = AutonomyConfig(
        enabled=enabled,
    )

    return DirectorAutonomy(
        config=config,
        **handlers,
    )
