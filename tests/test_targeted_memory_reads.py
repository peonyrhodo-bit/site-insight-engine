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

    with pytest.raises(MemoryReadError):
        await adapter.get_collection("recommendations", project_id="alpha")


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
