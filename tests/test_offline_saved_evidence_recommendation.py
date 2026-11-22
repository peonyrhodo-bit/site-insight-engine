"""Offline regression for stored evidence -> analytics -> decision -> recommendation.

Uses in-memory stored fixtures only; no YouTube, Supabase or network calls.
"""
import pytest

from director.director import Director
from director.decision import DecisionType
from web.recommendations import RecommendationStore


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "confidence", "applicability", "missing", "expected"),
    [
        (0.85, 0.90, 0.80, [], DecisionType.TEST),
        (0.60, 0.80, 0.80, [], DecisionType.ANALYZE),
        (0.85, 0.40, 0.80, ["insufficient sample"], DecisionType.RESEARCH),
        (0.25, 0.90, 0.80, [], DecisionType.WAIT),
    ],
)
async def test_saved_opportunity_reaches_correct_decision_and_recommendation(
    score, confidence, applicability, missing, expected
):
    # Simulates evidence previously saved and restored into Director context.
    stored = {
        "topic": "Engineering stories",
        "title": "Unusual engineering solutions",
        "overall_score": score,
        "confidence": confidence,
        "applicability": applicability,
        "missing_data": missing,
        "signals": ["observed audience interest"],
        "evidence": [{"statement": "offline stored fixture"}],
    }
    director = Director(project_id="offline-recommendation-chain")
    director.context.opportunities = [stored]
    analysis = await director.analyze()
    assert analysis["opportunities"] == [stored]

    decision = await director.decide(analysis)
    assert decision.decision_type == expected

    if expected in {DecisionType.RESEARCH, DecisionType.WAIT}:
        # Those decisions are not production recommendations by themselves.
        return

    recommendation = director.create_recommendation(decision, analysis=analysis)
    store = RecommendationStore()
    store.save(recommendation)
    restored = store.get(recommendation.recommendation_id)

    assert restored is not None
    assert restored.recommendation_id == recommendation.recommendation_id
    assert restored.decision.decision_id == decision.decision_id
    assert restored.title
    assert restored.summary
    assert restored.target is not None
