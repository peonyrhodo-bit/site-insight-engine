"""Explicit, verified applicability score is an assessment without a fit label."""
from analytics.opportunity import assess_applicability


def test_explicit_applicability_score_does_not_require_redundant_label():
    result = assess_applicability({"score": 0.75})
    assert result.score == 0.75
    assert "Project applicability has not been explicitly assessed." not in result.missing_data


def test_unknown_applicability_still_requires_research():
    result = assess_applicability({})
    assert "Project applicability has not been explicitly assessed." in result.missing_data


def test_missing_resource_mapping_still_reported_with_explicit_score():
    result = assess_applicability({"score": 0.75, "required_resources": ["video editing"]})
    assert "Available resources have not been mapped." in result.missing_data
