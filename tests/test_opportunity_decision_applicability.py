"""Regression: prepared analytics stores applicability score in dimensions."""
from director.decision import DecisionType, decide_from_opportunity


def test_prepared_analytics_applicability_dimension_can_select_test():
    opportunity = {
        "overall_score": 0.85,
        "confidence": 0.90,
        "missing_data": [],
        "applicability": {"target": "creator"},
        "dimensions": {"applicability": {"score": 0.80, "confidence": 0.9}},
    }
    decision = decide_from_opportunity(opportunity)
    assert decision.decision_type == DecisionType.TEST
    assert decision.applicability_score == 0.80


def test_low_applicability_dimension_does_not_select_test():
    opportunity = {
        "overall_score": 0.85,
        "confidence": 0.90,
        "missing_data": [],
        "applicability": {},
        "dimensions": {"applicability": {"score": 0.30}},
    }
    assert decide_from_opportunity(opportunity).decision_type == DecisionType.ANALYZE


def test_explicit_applicability_score_preserves_existing_contract():
    opportunity = {
        "overall_score": 0.85,
        "confidence": 0.90,
        "missing_data": [],
        "applicability": {"score": 0.75},
    }
    assert decide_from_opportunity(opportunity).decision_type == DecisionType.TEST
