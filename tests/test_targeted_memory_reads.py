"""Offline regression tests for targeted Memory 2.0 collection reads."""

from types import SimpleNamespace

import pytest

from memory.director_adapter import ServerMemory
from memory.read_status import MemoryReadError, MemoryTableReadError


@pytest.mark.asyncio
async def test_recommendations_reader_only_fetches_recommendations():
    calls = []

    class Backend:
        def get_recent_recommendations(self, *, project_id, limit):
            calls.append(("recommendations", project_id, limit))
            return [
                {"id": 5, "source_data": {"director_recommendation_id": "rec-5"}},
            ]

        def get_context(self, **kwargs):
            raise AssertionError("Full eight-table context must not be read")

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = SimpleNamespace(get_context=adapter.backend.get_context)

    rows = await adapter.get_collection("recommendations", project_id="alpha", limit=3)

    assert calls == [("recommendations", "alpha", 3)]
    assert rows[0]["recommendation_id"] == "rec-5"


@pytest.mark.asyncio
async def test_events_reader_only_fetches_events():
    calls = []

    class Backend:
        def get_recent_events(self, *, project_id, limit):
            calls.append((project_id, limit))
            return [{"id": 1, "event": "created"}]

        def get_context(self, **kwargs):
            raise AssertionError("Full context must not be read")

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = SimpleNamespace(get_context=adapter.backend.get_context)

    rows = await adapter.get_collection("events", project_id="beta", limit=2)

    assert calls == [("beta", 2)]
    assert rows == [{"id": 1, "event": "created"}]


@pytest.mark.asyncio
async def test_targeted_read_failure_is_not_silently_empty():
    class Backend:
        def get_recent_events(self, **kwargs):
            raise RuntimeError("database unavailable")

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = object()

    with pytest.raises(MemoryReadError) as error:
        await adapter.get_collection("events", project_id="alpha")

    assert error.value.status == "error"
    assert "database unavailable" in error.value.errors["events"]


@pytest.mark.asyncio
async def test_partial_page_failure_is_not_silently_accepted():
    class Backend:
        def get_recent_recommendations(self, **kwargs):
            raise MemoryTableReadError(
                "director_recommendations",
                partial_rows=[{"id": 1}],
                cause=RuntimeError("page two failed"),
            )

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = object()

    with pytest.raises(MemoryReadError) as error:
        await adapter.get_collection("recommendations", project_id="alpha")

    assert error.value.status == "partial"
    assert error.value.context["recommendations"] == [{"id": 1}]
    assert "page two failed" in error.value.errors["recommendations"]


@pytest.mark.asyncio
async def test_missing_reader_uses_full_context_fail_closed_fallback():
    adapter = object.__new__(ServerMemory)
    adapter.backend = object()
    adapter.memory = SimpleNamespace(
        get_context=lambda **kwargs: {
            "recommendations": [{"id": 7}],
            "_memory_read": {"status": "complete", "tables": {}, "errors": {}},
        },
    )

    rows = await adapter.get_collection("recommendations", project_id="alpha")

    assert rows[0]["recommendation_id"] == 7


@pytest.mark.asyncio
async def test_unavailable_backend_fails_closed():
    adapter = object.__new__(ServerMemory)
    adapter.backend = None
    adapter.memory = None

    with pytest.raises(MemoryReadError):
        await adapter.get_collection("events")


@pytest.mark.asyncio
async def test_unknown_collection_is_rejected():
    adapter = object.__new__(ServerMemory)
    adapter.backend = object()
    adapter.memory = object()

    with pytest.raises(ValueError):
        await adapter.get_collection("runs")


def test_supabase_recommendations_do_not_swallow_database_failure():
    from memory.supabase import SupabaseMemoryBackend

    backend = object.__new__(SupabaseMemoryBackend)

    def fail(*args, **kwargs):
        raise RuntimeError("supabase 402 quota exceeded")

    backend._recent_for_project = fail

    with pytest.raises(RuntimeError, match="402"):
        backend.get_recent_recommendations(project_id="alpha", limit=5)


@pytest.mark.asyncio
async def test_supabase_read_failure_propagates_through_adapter():
    from memory.supabase import SupabaseMemoryBackend

    backend = object.__new__(SupabaseMemoryBackend)

    def fail(*args, **kwargs):
        raise RuntimeError("supabase 402 quota exceeded")

    backend._recent_for_project = fail
    adapter = object.__new__(ServerMemory)
    adapter.backend = backend
    adapter.memory = object()

    with pytest.raises(MemoryReadError) as error:
        await adapter.get_collection("recommendations", project_id="alpha", limit=5)

    assert error.value.status == "error"
    assert "402" in error.value.errors["recommendations"]


@pytest.mark.asyncio
async def test_inmemory_backend_keeps_projects_isolated():
    from memory.inmemory import InMemoryMemoryBackend

    backend = InMemoryMemoryBackend()
    backend._recommendations.extend([
        {"id": 1, "project_id": "alpha", "title": "A"},
        {"id": 2, "project_id": "beta", "title": "B"},
    ])
    backend._events.extend([
        {"id": 3, "project_id": "alpha", "event": "A"},
        {"id": 4, "project_id": "beta", "event": "B"},
    ])
    adapter = object.__new__(ServerMemory)
    adapter.backend = backend
    adapter.memory = object()

    recommendations = await adapter.get_collection(
        "recommendations", project_id="alpha",
    )
    events = await adapter.get_collection("events", project_id="beta")

    assert [row["id"] for row in recommendations] == [1]
    assert [row["id"] for row in events] == [4]


@pytest.mark.asyncio
async def test_api_routes_preserve_response_shape_without_full_context(monkeypatch):
    import server

    calls = []

    class MemoryStub:
        async def get_collection(self, name, *, project_id, limit):
            calls.append((name, project_id, limit))
            return [{"id": 9, "recommendation_id": "legacy-9"}] if name == "recommendations" else [{"id": 8}]

        async def get_context(self, **kwargs):
            raise AssertionError("API should not request full memory context")

    monkeypatch.setattr(server.runtime, "memory", MemoryStub())

    recommendations = await server.director_recommendations(
        project_id="alpha", limit=4,
    )
    events = await server.events(project_id="beta", limit=6)

    assert recommendations == {
        "project_id": "alpha",
        "recommendations": [{"id": 9, "recommendation_id": "legacy-9"}],
    }
    assert events == {"project_id": "beta", "events": [{"id": 8}]}
    assert calls == [
        ("recommendations", "alpha", 4),
        ("events", "beta", 6),
    ]

@pytest.mark.asyncio
async def test_director_decision_carries_history_evidence():
    from director.director import Director
    director = Director(project_id='alpha')
    director.context.objective = 'Evaluate YouTube topics'
    history = {'youtube': {'video_count': 321, 'snapshot_count': 654}}
    analysis = {
        'opportunities': [{'opportunity_id': 'topic-1', 'title': 'Topic 1', 'overall_score': 0.9}],
        'history_analytics': history,
    }
    decision = await director.decide(analysis)
    assert decision.metadata['history_analytics'] == history
    assert decision.metadata['opportunity_id'] == 'topic-1'

@pytest.mark.asyncio
async def test_global_history_does_not_falsely_reorder_opportunities():
    from director.director import Director
    director = Director(project_id='alpha')
    director.context.objective = 'Evaluate topics'
    analysis = {
        'opportunities': [
            {'opportunity_id': 'strong', 'overall_score': 0.9},
            {'opportunity_id': 'weak', 'overall_score': 0.2},
        ],
        'history_analytics': {
            'youtube': {'status': 'complete', 'video_count': 5000,
                        'snapshot_count': 10000, 'top_topics': [
                            {'topic': 'weak', 'videos': 3000}
                        ]}
        },
    }
    decision = await director.decide(analysis)
    assert decision.metadata['opportunity_id'] == 'strong'
    assert decision.metadata['history_analytics'] == analysis['history_analytics']
