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
