import pytest

import server


@pytest.mark.asyncio
async def test_analytics_adapter_does_not_treat_raw_videos_as_opportunities(monkeypatch):
    assessed = []

    monkeypatch.setattr(server, "analytics_prepare_for_director", None)
    monkeypatch.setattr(server, "analyze_topics", lambda _items: {"topics": []})
    monkeypatch.setattr(server, "topics_prepare_for_director", None)
    monkeypatch.setattr(server, "analyze_trend", None)

    def fake_assess_opportunity(**kwargs):
        assessed.append(kwargs)
        return {}

    monkeypatch.setattr(server, "assess_opportunity", fake_assess_opportunity)

    observations = [
        {"video_id": f"video-{index}", "title": f"Video {index}"}
        for index in range(5193)
    ]

    result = await server.AnalyticsAdapter().analyze(
        {"observations": observations}
    )

    assert result["opportunities"] == []
    assert assessed == []


@pytest.mark.asyncio
async def test_research_analytics_preserves_exact_collection_and_previous_trend(monkeypatch):
    from analytics.analytics import AggregateMetrics, ResearchAnalytics

    calls = []
    result = ResearchAnalytics(
        metrics=AggregateMetrics(),
        top_videos=[],
        topic_distribution={},
        channel_distribution={},
        trend=None,
        signals=[],
        confidence=0.0,
        metadata={},
    )

    def fake_analyze(observations, *, previous_videos=None):
        calls.append((observations, previous_videos))
        return result

    monkeypatch.setattr(server, "analyze_research", fake_analyze)
    monkeypatch.setattr(server, "analytics_prepare_for_director", lambda _result: {})
    monkeypatch.setattr(server, "analyze_topics", None)
    monkeypatch.setattr(server, "analyze_trend", None)
    monkeypatch.setattr(server, "assess_opportunity", None)

    observations = [{"video_id": f"video-{index}"} for index in range(300)]
    previous = [{"video_id": f"previous-{index}"} for index in range(120)]

    await server.AnalyticsAdapter().analyze({
        "observations": observations,
        "previous_observations": previous,
        "trend_current_observations": observations,
    })

    assert len(calls) == 1
    assert calls[0][0] is observations
    assert calls[0][1] is previous


@pytest.mark.asyncio
async def test_analytics_releases_raw_observations_after_analysis(monkeypatch):
    monkeypatch.setattr(server, "analytics_prepare_for_director", None)
    monkeypatch.setattr(server, "analyze_topics", lambda _items: {"topics": []})
    monkeypatch.setattr(server, "topics_prepare_for_director", None)
    monkeypatch.setattr(server, "analyze_trend", None)
    monkeypatch.setattr(server, "assess_opportunity", None)

    observations = [
        {"video_id": f"video-{index}", "title": f"Video {index}"}
        for index in range(1200)
    ]
    context = {"observations": observations, "metadata": {}}

    await server.AnalyticsAdapter().analyze(context)

    assert len(observations) == 100
    assert context["metadata"]["last_analysis_observation_count"] == 1200
    assert context["metadata"]["last_analysis_context_sample_size"] == 100



@pytest.mark.asyncio
async def test_opportunity_assessment_receives_topic_specific_evidence(monkeypatch):
    assessed = []

    monkeypatch.setattr(server, "analytics_prepare_for_director", None)
    monkeypatch.setattr(
        server,
        "analyze_topics",
        lambda _items: {
            "topics": [
                {
                    "topic_id": "gardening",
                    "name": "Gardening",
                    "video_ids": ["video-5"],
                }
            ]
        },
    )
    monkeypatch.setattr(server, "topics_prepare_for_director", None)
    monkeypatch.setattr(server, "analyze_trend", None)
    monkeypatch.setattr(server, "opportunity_prepare_for_director", None)

    def fake_assess_opportunity(**kwargs):
        assessed.append(kwargs)
        return {}

    monkeypatch.setattr(server, "assess_opportunity", fake_assess_opportunity)
    observations = [
        {"video_id": f"video-{index}", "title": f"Video {index}"}
        for index in range(10)
    ]

    await server.AnalyticsAdapter().analyze(
        {"observations": observations, "metadata": {}}
    )

    assert len(assessed) == 1
    assert [item["video_id"] for item in assessed[0]["videos"]] == ["video-5"]



def test_director_state_keeps_full_counts_after_evidence_compaction():
    from director.director import Director

    director = Director(project_id="test")
    director.context.observations = [
        {"video_id": f"video-{index}", "views": 100}
        for index in range(100)
    ]
    director.context.metadata = {
        "last_analysis_observation_count": 1200,
        "last_analysis_metric_observation_count": 1100,
        "last_analysis_velocity_observation_count": 900,
        "last_analysis_known_topic_label_count": 12,
        "last_analysis_latest_snapshot_at": "2026-11-06T12:00:00Z",
        "data_inventory": {"video_count": 1200, "snapshot_count": 2400},
    }

    director._refresh_project_state()

    project_state = director.context.metadata["project_state"]
    assert project_state["observation_count"] == 1200
    assert project_state["metric_observation_count"] == 1100
    assert project_state["velocity_observation_count"] == 900
    assert project_state["coverage"]["known_topic_labels"] == 12
