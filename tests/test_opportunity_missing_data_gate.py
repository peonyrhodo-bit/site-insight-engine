"""Characterize the existing decision gate without weakening evidence rules."""
from director.decision import DecisionType, decide_from_opportunity


def _opportunity(*, missing, confidence=0.9):
    return {
        "overall_score": 0.85,
        "confidence": confidence,
        "dimensions": {"applicability": {"score": 0.8}},
        "missing_data": missing,
    }


def test_high_quality_opportunity_without_gaps_selects_test():
    assert decide_from_opportunity(_opportunity(missing=[])).decision_type == DecisionType.TEST


def test_high_quality_opportunity_with_nonempty_gap_selects_research():
    decision = decide_from_opportunity(
        _opportunity(missing=["Reliable comparison period is unavailable."])
    )
    assert decision.decision_type == DecisionType.RESEARCH
    assert decision.missing_data == ["Reliable comparison period is unavailable."]


def test_low_confidence_without_gaps_still_requires_research():
    assert decide_from_opportunity(
        _opportunity(missing=[], confidence=0.3)
    ).decision_type == DecisionType.RESEARCH
