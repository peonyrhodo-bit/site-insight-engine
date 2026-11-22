"""Offline regression for autonomous recommendation routing with quota limits."""
import pytest

from director.autonomy import AutonomyConfig, DirectorAutonomy
from director.decision import DecisionType, build_decision


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [DecisionType.TEST, DecisionType.ANALYZE])
async def test_evidence_backed_decision_reaches_recommendation_when_search_unavailable(kind):
    recommendations = []
    async def inspect(state, payload):
        return {"evidence_available": True}
    async def assess(state, payload):
        state.metadata["project_assessment"] = {
            "quota": {"remaining_units_today": 0, "search_calls_remaining": 0}
        }
        return {"evidence_sufficient": True}
    async def decide(state, payload):
        return build_decision(
            decision_type=kind, objective="Use existing evidence",
            rationale="Previously stored analytical evidence", confidence=0.8,
            next_action="Review evidence-backed proposal",
        )
    async def recommend(state, decision):
        recommendations.append(decision)
        return {"recommendation_id": "offline-rec"}
    autonomy = DirectorAutonomy(
        config=AutonomyConfig(max_steps_per_cycle=9, sleep_after_recommendation=False),
        inspect=inspect,
        assess=assess,
        decide=decide,
        recommend=recommend,
    )
    cycle = await autonomy.run(project_id="offline-routing")
    assert recommendations, (
        f"{kind.value} decision with sufficient evidence must not be lost "
        f"when YouTube search quota is unavailable: {cycle.state.sleep_reason}"
    )
