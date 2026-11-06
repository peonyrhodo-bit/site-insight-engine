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


def test_research_analytics_runs_in_bounded_batches(monkeypatch):
    from types import SimpleNamespace

    calls = []

    class Metrics:
        def __init__(self, count):
            self.count = count
            self.total_views = count * 10
            self.median_views = 10
            self.average_views = 10
            self.average_likes = 1
            self.average_comments = 1
            self.average_like_rate = 0.1
            self.average_comment_rate = 0.1
            self.average_engagement_rate = 0.2
            self.average_views_per_hour = 1
            self.average_performance_score = 0.5
            self.top_video_id = None
            self.top_video_score = 0

    class Aggregate:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Research:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    def fake_analyze(batch):
        calls.append(len(batch))
        count = len(batch)
        return SimpleNamespace(
            metrics=Metrics(count),
            topic_distribution={"gardening": count},
            channel_distribution={"channel-1": count},
            top_videos=[], signals=["measurable_momentum"], confidence=0.8,
        )

    monkeypatch.setattr(server, "analyze_research", fake_analyze)
    monkeypatch.setattr(server, "AggregateMetrics", Aggregate)
    monkeypatch.setattr(server, "ResearchAnalytics", Research)

    result = server._analyze_research_in_batches(
        [{"video_id": str(index)} for index in range(1200)],
        batch_size=100,
    )

    assert calls == [100] * 12
    assert result.metrics.count == 1200
    assert result.metadata["batch_count"] == 12
    assert result.metadata["processing"] == "bounded_batches"


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

    assert observations == []
    assert context["metadata"]["last_analysis_observation_count"] == 1200
