"""
Director autonomy cycle.

This module defines the execution shell around the Director.

The autonomy layer does NOT make strategic decisions itself.

Its responsibility is only to control the cycle:

WAKE
→ LOAD STATE
→ ASK DIRECTOR WHAT TO DO
→ EXECUTE ALLOWED ACTION
→ SAVE RESULT
→ EVALUATE
→ CONTINUE OR STOP
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AutonomyConfig:
    max_steps: int = 5
    enabled: bool = False
    stop_on_error: bool = True


@dataclass
class AutonomyResult:
    run_id: int | None
    status: str
    steps: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class DirectorAutonomy:
    """
    Thin execution loop around the Director.

    The actual strategic choice belongs to director.py.
    """

    def __init__(
        self,
        *,
        director: Any,
        memory: Any | None = None,
        config: AutonomyConfig | None = None,
    ) -> None:
        self.director = director
        self.memory = memory
        self.config = config or AutonomyConfig()

        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def run(
        self,
        *,
        run_id: int | None = None,
        context: dict[str, Any] | None = None,
        action_executor: Callable[[Any], Any] | None = None,
    ) -> AutonomyResult:
        """
        Run a bounded Director cycle.

        This first implementation is intentionally conservative:
        autonomy must be explicitly enabled and every run is bounded.
        """

        if not self.config.enabled:
            return AutonomyResult(
                run_id=run_id,
                status="disabled",
            )

        if self._running:
            return AutonomyResult(
                run_id=run_id,
                status="already_running",
            )

        self._running = True

        result = AutonomyResult(
            run_id=run_id,
            status="running",
        )

        try:
            current_context = dict(context or {})

            for step in range(self.config.max_steps):
                result.steps += 1

                decision = self._ask_director(
                    context=current_context,
                    run_id=run_id,
                )

                if decision is None:
                    result.status = "stopped"
                    break

                if not self._should_continue(decision):
                    result.status = "completed"
                    break

                action_result = self._execute_action(
                    decision,
                    action_executor=action_executor,
                )

                normalized_result = self._normalize_result(
                    action_result
                )

                result.results.append(normalized_result)

                if self.memory is not None:
                    self.memory.save_result(
                        result_type="autonomy_step",
                        summary=normalized_result.get(
                            "summary",
                            "",
                        ),
                        run_id=run_id,
                        data=normalized_result,
                    )

                current_context["last_result"] = normalized_result

            else:
                result.status = "max_steps_reached"

        except Exception as exc:
            result.status = "error"
            result.error = str(exc)

            if self.memory is not None:
                try:
                    self.memory.save_result(
                        result_type="autonomy_error",
                        summary=str(exc),
                        run_id=run_id,
                        data={
                            "error": str(exc),
                        },
                    )
                except Exception:
                    pass

            if self.config.stop_on_error:
                return result

        finally:
            self._running = False

        return result

    def _ask_director(
        self,
        *,
        context: dict[str, Any],
        run_id: int | None,
    ) -> Any:
        """
        Delegate the actual decision to Director.

        Different Director implementations may expose different
        method names during migration, so this adapter supports the
        currently expected forms without implementing strategy here.
        """

        if hasattr(self.director, "decide_next_action"):
            return self.director.decide_next_action(
                context=context,
                run_id=run_id,
            )

        if hasattr(self.director, "decide"):
            return self.director.decide(
                context=context,
                run_id=run_id,
            )

        if hasattr(self.director, "run"):
            return self.director.run(
                context=context,
                run_id=run_id,
            )

        raise AttributeError(
            "Director does not expose a supported decision method"
        )

    @staticmethod
    def _should_continue(decision: Any) -> bool:
        if decision is None:
            return False

        if isinstance(decision, dict):
            if decision.get("continue") is False:
                return False

            if decision.get("should_continue") is False:
                return False

            if decision.get("next_action") is None:
                return False

            return True

        if hasattr(decision, "next_action"):
            return getattr(
                decision,
                "next_action",
                None,
            ) is not None

        return True

    @staticmethod
    def _execute_action(
        decision: Any,
        *,
        action_executor: Callable[[Any], Any] | None,
    ) -> Any:
        if action_executor is not None:
            return action_executor(decision)

        if isinstance(decision, dict):
            return {
                "status": "pending",
                "summary": "Action selected but no executor configured.",
                "decision": decision,
            }

        return {
            "status": "pending",
            "summary": "Action selected but no executor configured.",
            "decision": getattr(
                decision,
                "next_action",
                None,
            ),
        }

    @staticmethod
    def _normalize_result(
        value: Any,
    ) -> dict[str, Any]:
        if isinstance(value, dict):
            return value

        return {
            "status": "completed",
            "summary": str(value),
        }
