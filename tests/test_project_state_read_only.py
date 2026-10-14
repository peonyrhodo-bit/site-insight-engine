from server import DataAdapter


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


class StorageSpy:
    def __init__(self):
        self.save_calls = 0

    def load_youtube_data(self, *, project_id):
        return None

    def load_opportunity_data(self, *, project_id):
        return None

    def load_research_data(self, *, project_id):
        return None

    def save_research_data(self, **kwargs):
        self.save_calls += 1
        return {"saved": True}


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
