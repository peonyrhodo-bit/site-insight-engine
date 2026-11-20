"""Offline characterization tests for PR-B idempotency read/write paths.

These tests describe CURRENT behavior; they do not authorize a migration.
"""
from types import SimpleNamespace

import pytest

from memory.director_adapter import ServerMemory


@pytest.mark.asyncio
async def test_create_run_currently_reads_entire_project_history():
    calls = []

    class Backend:
        TABLE_RUNS = "director_runs"

        def _recent_for_project(self, table, *, limit, project_id, order_key):
            calls.append(("read", table, limit, project_id, order_key))
            return []

        def save_run(self, *, language, region_code, data):
            calls.append(("insert", data["project_id"]))
            return 17

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = object()

    result = await adapter.create_run("alpha", {"status": "requested"})

    assert result == 17
    assert calls == [
        ("read", "director_runs", None, "alpha", "created_at"),
        ("insert", "alpha"),
    ]


@pytest.mark.asyncio
async def test_create_run_read_failure_does_not_insert():
    class Backend:
        TABLE_RUNS = "director_runs"

        def _recent_for_project(self, *args, **kwargs):
            raise RuntimeError("supabase quota exceeded")

        def save_run(self, **kwargs):
            raise AssertionError("must not insert after history read failure")

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = object()

    with pytest.raises(RuntimeError, match="quota exceeded"):
        await adapter.create_run("alpha", {"status": "requested"})


@pytest.mark.asyncio
async def test_update_run_false_result_fails_closed():
    adapter = object.__new__(ServerMemory)
    adapter.memory = SimpleNamespace(update_run=lambda **kwargs: False)

    with pytest.raises(RuntimeError, match="affected no row"):
        await adapter.update_run(
            5, project_id="alpha", fields={"idempotency_status": "completed"}
        )


def test_supabase_update_run_reads_json_before_writing():
    from memory.supabase import SupabaseMemoryBackend

    calls = []

    class Query:
        def select(self, columns):
            calls.append(("select", columns))
            return self

        def eq(self, column, value):
            calls.append(("eq", column, value))
            return self

        def limit(self, value):
            return self

        def update(self, payload):
            calls.append(("update", payload))
            return self

        def execute(self):
            if calls[-1][0] == "eq":
                return SimpleNamespace(data=[{"data_json": {"existing": True}}])
            return SimpleNamespace(data=[{"id": 5}])

    class Client:
        def table(self, name):
            assert name == "director_runs"
            return Query()

    backend = object.__new__(SupabaseMemoryBackend)
    backend.client = Client()

    assert backend.update_run(run_id=5, data={"idempotency_status": "completed"})
    assert calls[0] == ("select", "data_json")
    assert any(
        call[0] == "update"
        and call[1]["data_json"] == {
            "existing": True, "idempotency_status": "completed"
        }
        for call in calls
    )
