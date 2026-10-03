"""
Web/API routes for the Director.

The router is intentionally thin:
HTTP -> Director -> response.

Strategic logic belongs to director/.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from director.director import (
    Director,
    DirectorMode,
)
from director.feedback import (
    FeedbackScope,
)
from director.recommendations import (
    RecommendationStatus,
)

from .dashboard import build_dashboard
from .recommendations import (
    RecommendationAction,
    RecommendationActionRequest,
    RecommendationController,
)


# ============================================================
# REQUEST MODELS
# ============================================================


class DirectorRunRequest(BaseModel):
    project_id: str | None = None
    objective: str | None = None
    autonomous: bool = False


class RecommendationActionBody(BaseModel):
    action: RecommendationAction
    message: str | None = None
    reason: str | None = None
    scope: FeedbackScope = FeedbackScope.RECOMMENDATION
    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class DirectorFeedbackBody(BaseModel):
    recommendation_id: str | None = None
    decision_id: str | None = None

    feedback_type: str
    scope: FeedbackScope = FeedbackScope.GENERAL

    message: str

    target: str | None = None
    reason: str | None = None
    constraint: str | None = None
    preference: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class DirectorChatRequest(BaseModel):
    message: str
    project_id: str | None = None


# ============================================================
# ROUTER
# ============================================================


def create_router(
    *,
    director_factory: Any,
    recommendation_controller: RecommendationController | None = None,
) -> APIRouter:
    """
    Create the Director web router.

    director_factory must return a Director instance.
    """

    router = APIRouter(
        prefix="/director",
        tags=["director"],
    )

    controller = (
        recommendation_controller
        or RecommendationController()
    )

    # ----------------------------------------------------------
    # HEALTH / STATUS
    # ----------------------------------------------------------

    @router.get("/status")
    async def director_status(
        project_id: str | None = None,
    ) -> dict[str, Any]:
        director = director_factory(
            project_id=project_id
        )

        return director.status()

    # ----------------------------------------------------------
    # RUN ONCE
    # ----------------------------------------------------------

    @router.post("/run")
    async def director_run(
        body: DirectorRunRequest,
    ) -> dict[str, Any]:
        mode = (
            DirectorMode.AUTONOMOUS
            if body.autonomous
            else DirectorMode.MANUAL
        )

        director: Director = director_factory(
            project_id=body.project_id,
            mode=mode,
        )

        if body.autonomous:
            cycle = director.run_autonomous_cycle(
                objective=body.objective
            )

            return {
                "success": True,
                "type": "autonomous_cycle",
                "cycle": cycle.to_dict(),
                "status": director.status(),
            }

        result = director.run_once(
            objective=body.objective
        )

        return {
            "success": result.status.value != "error",
            "type": "director_result",
            "result": result.to_dict(),
            "status": director.status(),
        }

    # ----------------------------------------------------------
    # AUTONOMOUS
    # ----------------------------------------------------------

    @router.post("/autonomous/run")
    async def autonomous_run(
        body: DirectorRunRequest,
    ) -> dict[str, Any]:
        director: Director = director_factory(
            project_id=body.project_id,
            mode=DirectorMode.AUTONOMOUS,
        )

        cycle = director.run_autonomous_cycle(
            objective=body.objective
        )

        return {
            "success": cycle.status.value != "error",
            "cycle": cycle.to_dict(),
            "status": director.status(),
        }

    # ----------------------------------------------------------
    # DASHBOARD
    # ----------------------------------------------------------

    @router.get("/dashboard")
    async def dashboard(
        project_id: str | None = None,
    ) -> dict[str, Any]:
        director: Director = director_factory(
            project_id=project_id
        )

        dashboard_state = build_dashboard(
            director
        )

        return dashboard_state.to_dict()

    # ----------------------------------------------------------
    # RECOMMENDATIONS
    # ----------------------------------------------------------

    @router.get("/recommendations")
    async def recommendations(
        status: RecommendationStatus | None = None,
    ) -> dict[str, Any]:
        items = controller.list(
            status=status
        )

        return {
            "success": True,
            "count": len(items),
            "recommendations": [
                item.to_dict()
                for item in items
            ],
        }

    @router.get(
        "/recommendations/{recommendation_id}"
    )
    async def recommendation(
        recommendation_id: str,
    ) -> dict[str, Any]:
        item = controller.get(
            recommendation_id
        )

        if item is None:
            raise HTTPException(
                status_code=404,
                detail="Рекомендация не найдена.",
            )

        return {
            "success": True,
            "recommendation": item.to_dict(),
        }

    # ----------------------------------------------------------
    # USER ACTIONS
    # ----------------------------------------------------------

    @router.post(
        "/recommendations/{recommendation_id}/action"
    )
    async def recommendation_action(
        recommendation_id: str,
        body: RecommendationActionBody,
    ) -> dict[str, Any]:
        request = RecommendationActionRequest(
            action=body.action,
            recommendation_id=recommendation_id,
            message=body.message,
            reason=body.reason,
            scope=body.scope,
            metadata=body.metadata,
        )

        result = controller.apply(
            request
        )

        if not result.success:
            raise HTTPException(
                status_code=400,
                detail=result.message,
            )

        # Feedback is now available to the Director.
        # Persistence/wiring can be attached through the controller.
        return {
            "success": True,
            "result": result.to_dict(),
        }

    # ----------------------------------------------------------
    # FEEDBACK
    # ----------------------------------------------------------

    @router.post("/feedback")
    async def feedback(
        body: DirectorFeedbackBody,
    ) -> dict[str, Any]:
        from director.feedback import create_feedback

        feedback = create_feedback(
            feedback_type=body.feedback_type,
            scope=body.scope,
            message=body.message,
            recommendation_id=body.recommendation_id,
            decision_id=body.decision_id,
            target=body.target,
            reason=body.reason,
            constraint=body.constraint,
            preference=body.preference,
            metadata=body.metadata,
        )

        return {
            "success": True,
            "feedback": feedback.to_dict(),
        }

    # ----------------------------------------------------------
    # RESEARCH
    # ----------------------------------------------------------

    @router.post("/research")
    async def research(
        project_id: str | None = None,
        objective: str | None = None,
    ) -> dict[str, Any]:
        director: Director = director_factory(
            project_id=project_id
        )

        plan = director.plan_research(
            objective=objective
        )

        return {
            "success": True,
            "research": plan.to_dict(),
        }

    # ----------------------------------------------------------
    # CHAT
    # ----------------------------------------------------------

    @router.post("/chat")
    async def chat(
        body: DirectorChatRequest,
    ) -> dict[str, Any]:
        """
        Thin chat endpoint.

        Actual natural-language intent/action orchestration can be
        connected to director/chat.py without putting strategy here.
        """
        from director.chat import (
            execute_chat_command,
            parse_chat_command,
        )

        director: Director = director_factory(
            project_id=body.project_id
        )

        command = parse_chat_command(
            body.message
        )

        handlers = {
            "inspect_state": lambda _: {
                "message": (
                    "Вот текущее состояние Валерия."
                ),
                "status": director.status(),
            },
            "start_research": lambda _: {
                "message": (
                    "Я подготовил следующий этап исследования."
                ),
                "research": director.plan_research().to_dict(),
            },
            "run_analysis": lambda _: {
                "message": "Анализ выполнен.",
                "analysis": director.analyze(),
            },
            "generate_recommendation": lambda _: (
                director.run_once().to_dict()
            ),
            "continue_cycle": lambda _: (
                director.run_once().to_dict()
            ),
            "stop_cycle": lambda _: {
                "message": "Текущий цикл остановлен.",
            },
            "ask_clarification": lambda _: {
                "message": (
                    "Уточни, пожалуйста, что именно "
                    "ты хочешь, чтобы я сделал."
                ),
            },
        }

        result = execute_chat_command(
            command,
            handlers=handlers,
        )

        return {
            "success": result.handled,
            "command": command.to_dict(),
            "result": result.to_dict(),
        }

    return router
