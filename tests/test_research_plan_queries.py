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

    assert len(plan.queries) == 2  # default research languages: English and Russian
    assert {query.language for query in plan.queries} == {"en", "ru"}
    assert all(query.query == "YouTube productivity channels competition" for query in plan.queries)
    assert all("unavailable" not in query.query.casefold() for query in plan.queries)


def test_concrete_gap_description_can_still_become_a_query():
    plan = research_from_gaps(
        ["YouTube channels about beginner home gardening"],
        objective="Explore beginner gardening content",
        languages=["en"],
    )

    assert len(plan.queries) == 2  # default research languages: English and Russian
    assert {query.language for query in plan.queries} == {"en", "ru"}
    assert all(query.query == "YouTube channels about beginner home gardening" for query in plan.queries)



def test_diagnostic_gap_without_topic_never_becomes_a_query_in_supported_languages():
    diagnostics = [
        "Reliable comparison period is unavailable.",
        "Competitive intensity classification is not available.",
        "Insufficient data to determine audience overlap.",
        "Недостаточно данных для определения динамики.",
    ]
    plan = research_from_gaps(
        diagnostics,
        objective="Validate missing-data handling",
    )

    assert len(plan.gaps) == len(diagnostics)
    assert plan.queries == []
