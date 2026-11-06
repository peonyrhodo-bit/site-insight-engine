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
