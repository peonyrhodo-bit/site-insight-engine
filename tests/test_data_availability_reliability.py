import pytest

from director.director import Director, DirectorMode
from server import DataAdapter
from data.youtube import YouTubeQuery


class FailingYouTubeStorage:
    def load_youtube_data(self, *, project_id):
        raise RuntimeError("temporary database outage")


@pytest.mark.asyncio
async def test_data_storage_failure_is_reported_as_unavailable_not_empty():
    adapter = DataAdapter(storage=FailingYouTubeStorage())
    state = await adapter.get_project_state(project_id="outage-project")

    assert state["data_load_status"] == "unavailable"
    assert "temporary database outage" in state["data_load_error"]

    director = Director(
        project_id="outage-project",
        mode=DirectorMode.AUTONOMOUS,
        data_service=adapter,
    )
    director._merge_context(state)
    director._refresh_project_state()

    assert director.state.evidence_sufficient is False
    assert any("наличие данных неизвестно" in gap for gap in director.context.missing_data)
    assert not any("(отсутствует: videos)" in gap for gap in director.context.missing_data)


def test_exhausted_quota_does_not_manufacture_evidence_sufficiency():
    director = Director(project_id="empty-project", mode=DirectorMode.AUTONOMOUS)
    director.context.metadata["project_state"] = {
        "freshness": {"status": "fresh"},
        "coverage": {"stored_search_queries": 12},
        "quota": {
            "remaining_units_today": 0,
            "estimated_other_units_per_search": 1,
            "search_calls_remaining": 0,
        },
    }
    director.context.metadata["data_inventory"] = {
        "video_count": 0,
        "snapshot_count": 0,
        "query_count": 12,
        "research_set_count": 0,
        "relation_count": 0,
        "channel_count": 0,
        "channel_snapshot_count": 0,
        "niche_count": 0,
        "niche_snapshot_count": 0,
    }

    assessment = director._autonomy_assess(director.state, None)

    assert assessment["evidence_sufficient"] is False
    assert director.state.evidence_sufficient is False

def test_persisted_research_sets_are_mapped_into_director_research_history():
    class FakeResearchManager:
        def all(self):
            return [
                {
                    "research_id": "previous-research",
                    "name": "Prior search",
                    "status": "complete",
                    "objective": "avoid repeating the same research",
                }
            ]

    adapter = DataAdapter(storage=None)
    adapter.research_manager = FakeResearchManager()
    state = __import__("asyncio").run(adapter.get_project_state(project_id="history-project"))

    director = Director(project_id="history-project", mode=DirectorMode.AUTONOMOUS)
    director._merge_context(state)

    assert len(director.context.research_history) == 1
    assert director.context.research_history[0]["research_id"] == "previous-research"

@pytest.mark.asyncio
async def test_malformed_quota_metadata_does_not_zero_the_entire_data_inventory():
    adapter = DataAdapter(storage=None)
    adapter.youtube_registry.add_query(
        YouTubeQuery(
            query_id="bad-quota",
            text="sample query",
            metadata={"quota": {"other_units": "not-a-number", "search_calls": None}},
        )
    )

    state = await adapter.get_project_state(project_id="malformed-quota-project")

    assert state["data_inventory"]["query_count"] == 1
    assert state["data_inventory"]["youtube_other_units_today"] == 0
    assert state["data_inventory"]["youtube_search_calls_today"] == 0
