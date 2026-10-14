from director.research import research_from_gaps


def test_diagnostic_gap_is_preserved_but_not_sent_as_search_query():
    plan = research_from_gaps(
        ["Reliable comparison period is unavailable."],
        objective="Compare YouTube channels in the selected niche",
    )

    assert len(plan.gaps) == 1
    assert plan.gaps[0].description == "Reliable comparison period is unavailable."
    assert plan.queries == []


def test_diagnostic_gap_uses_explicit_topic_when_available():
    plan = research_from_gaps(
        [
            {
                "description": "Competitive intensity classification is unavailable.",
                "topic": "YouTube productivity channels competition",
            }
        ],
        objective="Analyze the productivity niche",
        languages=["en"],
    )

    assert len(plan.queries) == 1
    assert plan.queries[0].query == "YouTube productivity channels competition"
    assert "unavailable" not in plan.queries[0].query.casefold()


def test_concrete_gap_description_can_still_become_a_query():
    plan = research_from_gaps(
        ["YouTube channels about beginner home gardening"],
        objective="Explore beginner gardening content",
        languages=["en"],
    )

    assert len(plan.queries) == 1
    assert plan.queries[0].query == "YouTube channels about beginner home gardening"
