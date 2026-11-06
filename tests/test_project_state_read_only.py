import pytest

from server import DataAdapter
from data.youtube import YouTubeDataRegistry, YouTubeSnapshot


class ReadOnlyRegistry:
    def clear(self):
        pass

    def queries(self):
        return []

    def videos(self):
        return []

    def snapshots(self):
        return []

    def add_query(self, query):
        pass

    def add_video(self, video):
        pass

    def add_snapshot(self, snapshot):
        pass


class OpportunityRegistry:
    def counts(self):
        return {
            "channels": 1,
            "channel_snapshots": 1,
            "niches": 1,
            "niche_snapshots": 1,
        }

    def to_dict(self):
        return {
            "channels": [{"channel_id": "channel-1", "title": "Channel"}],
            "channel_snapshots": [{"channel_id": "channel-1", "captured_at": "2026-01-01T00:00:00Z"}],
            "niches": [{"niche_id": "niche-1", "name": "Niche"}],
            "niche_snapshots": [{"niche_id": "niche-1", "captured_at": "2026-01-01T00:00:00Z"}],
        }


class StorageSpy:
    def __init__(self):
        self.save_calls = 0
        self.youtube_load_calls = 0
        self.opportunity_load_calls = 0
        self.research_load_calls = 0

    def load_youtube_data(self, *, project_id):
        self.youtube_load_calls += 1
        return None

    def load_opportunity_data(self, *, project_id):
        self.opportunity_load_calls += 1
        return None

    def load_research_data(self, *, project_id):
        self.research_load_calls += 1
        return None

    def save_research_data(self, **kwargs):
        self.save_calls += 1
        return {"saved": True}


@pytest.mark.asyncio
async def test_get_project_state_does_not_persist_research_data():
    adapter = DataAdapter.__new__(DataAdapter)
    storage = StorageSpy()
    adapter.storage = storage
    adapter.youtube_registry = ReadOnlyRegistry()
    adapter.research_manager = None
    adapter.relations = None
    adapter.opportunity_registry = None

    result = await adapter.get_project_state("test-project")

    assert result["project_id"] == "test-project"
    assert storage.save_calls == 0


@pytest.mark.asyncio
async def test_get_project_state_loads_persisted_data_only_once_per_project():
    adapter = DataAdapter.__new__(DataAdapter)
    storage = StorageSpy()
    adapter.storage = storage
    adapter.youtube_registry = ReadOnlyRegistry()
    adapter.research_manager = None
    adapter.relations = None
    adapter.opportunity_registry = OpportunityRegistry()

    await adapter.get_project_state("test-project")
    await adapter.get_project_state("test-project")

    assert storage.youtube_load_calls == 1
    assert storage.opportunity_load_calls == 1
    assert storage.research_load_calls == 1


def test_latest_snapshot_does_not_need_chronological_sorting():
    registry = YouTubeDataRegistry()
    registry.add_snapshot(YouTubeSnapshot(snapshot_id="old", video_id="v1", captured_at="2025-01-01T00:00:00+00:00"))
    newest = YouTubeSnapshot(snapshot_id="new", video_id="v1", captured_at="2026-01-01T00:00:00+00:00")
    registry.add_snapshot(newest)
    registry.add_snapshot(YouTubeSnapshot(snapshot_id="middle", video_id="v1", captured_at="2025-06-01T00:00:00+00:00"))

    assert registry.latest_snapshot("v1") is newest


@pytest.mark.asyncio
async def test_get_project_state_exposes_loaded_opportunity_records_to_director():
    adapter = DataAdapter.__new__(DataAdapter)
    storage = StorageSpy()
    adapter.storage = storage
    adapter.youtube_registry = ReadOnlyRegistry()
    adapter.research_manager = None
    adapter.relations = None
    adapter.opportunity_registry = OpportunityRegistry()

    result = await adapter.get_project_state("test-project")

    assert result["channels"][0]["channel_id"] == "channel-1"
    assert result["channel_snapshots"][0]["channel_id"] == "channel-1"
    assert result["niches"][0]["niche_id"] == "niche-1"
    assert result["niche_snapshots"][0]["niche_id"] == "niche-1"

@pytest.mark.asyncio
async def test_trend_cohort_reuses_current_observation_dicts():
    class Video:
        video_id = "video-1"

        def to_dict(self):
            return {
                "video_id": self.video_id,
                "title": "Video",
                "metadata": {"topics": ["topic-a"]},
            }

    class Snapshot:
        def __init__(self, captured_at, views):
            self.captured_at = captured_at
            self.metrics = {"views": views, "likes": 1, "comments": 0}

    class Registry(ReadOnlyRegistry):
        def __init__(self):
            self.video = Video()
            self.history = [
                Snapshot("2026-01-01T00:00:00Z", 10),
                Snapshot("2026-01-02T00:00:00Z", 20),
            ]

        def videos(self):
            return [self.video]

        def snapshots(self):
            return self.history

        def queries(self):
            return []

        def snapshots_for_video(self, *, video_id):
            assert video_id == "video-1"
            return self.history

    adapter = DataAdapter.__new__(DataAdapter)
    adapter.storage = StorageSpy()
    adapter.youtube_registry = Registry()
    adapter.research_manager = None
    adapter.relations = None
    adapter.opportunity_registry = None

    result = await adapter.get_project_state("test-project")

    assert len(result["observations"]) == 1
    assert len(result["previous_observations"]) == 1
    assert len(result["trend_current_observations"]) == 1
    # Trend analysis consumes the matched current cohort, but should not
    # allocate a second full observation dictionary for every matched video.
    assert (
        result["trend_current_observations"][0]
        is result["observations"][0]
    )

