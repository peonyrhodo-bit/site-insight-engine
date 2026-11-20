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


def test_active_run_metadata_is_narrow_and_project_scoped():
    from memory.supabase import SupabaseMemoryBackend

    calls = []

    class Query:
        def select(self, columns):
            calls.append(("select", columns))
            return self

        def eq(self, column, value):
            calls.append(("eq", column, value))
            return self

        def in_(self, column, values):
            calls.append(("in", column, values))
            return self

        def order(self, column, *, desc):
            calls.append(("order", column, desc))
            return self

        def execute(self):
            return SimpleNamespace(data=[{"id": 4, "status": "running"}])

    class Client:
        def table(self, name):
            assert name == "director_runs"
            return Query()

    backend = object.__new__(SupabaseMemoryBackend)
    backend.client = Client()

    assert backend.get_active_run_metadata(project_id="alpha") == [
        {"id": 4, "status": "running"}
    ]
    assert calls == [
        ("select", "id,project_id,status,created_at,updated_at,started_at,current_step"),
        ("eq", "project_id", "alpha"),
        ("in", "status", ["requested", "running"]),
        ("order", "created_at", True),
    ]


def test_active_run_metadata_rejects_blank_project_without_query():
    from memory.supabase import SupabaseMemoryBackend

    backend = object.__new__(SupabaseMemoryBackend)
    with pytest.raises(ValueError, match="project_id"):
        backend.get_active_run_metadata(project_id="  ")


def test_active_run_metadata_propagates_backend_error():
    from memory.supabase import SupabaseMemoryBackend

    class Query:
        def select(self, *args):
            return self

        def eq(self, *args):
            return self

        def in_(self, *args):
            return self

        def order(self, *args, **kwargs):
            return self

        def execute(self):
            raise RuntimeError("supabase unavailable")

    backend = object.__new__(SupabaseMemoryBackend)
    backend.client = SimpleNamespace(table=lambda _: Query())
    with pytest.raises(RuntimeError, match="supabase unavailable"):
        backend.get_active_run_metadata(project_id="alpha")


def test_legacy_json_only_active_run_is_not_returned_by_narrow_query():
    """Document migration gate: indexed columns cannot see JSON-only legacy rows."""
    from memory.supabase import SupabaseMemoryBackend

    legacy_row = {
        "id": 19,
        "project_id": None,
        "status": None,
        "data_json": {"project_id": "alpha", "status": "running"},
    }

    class Query:
        def select(self, columns):
            assert "data_json" not in columns
            return self

        def eq(self, column, value):
            assert (column, value) == ("project_id", "alpha")
            return self

        def in_(self, column, values):
            assert column == "status"
            return self

        def order(self, *args, **kwargs):
            return self

        def execute(self):
            # Supabase filters out the legacy row because its indexed columns
            # are NULL, despite matching data_json values.
            assert legacy_row["project_id"] is None
            return SimpleNamespace(data=[])

    backend = object.__new__(SupabaseMemoryBackend)
    backend.client = SimpleNamespace(table=lambda _: Query())
    assert backend.get_active_run_metadata(project_id="alpha") == []


@pytest.mark.asyncio
async def test_concurrent_same_project_starts_only_one_cycle():
    """Fake durable unique guard: exactly one of two concurrent starts wins."""
    import asyncio
    from memory.director_adapter import DirectorCycleAlreadyRunning

    class Backend:
        TABLE_RUNS = "director_runs"

        def __init__(self):
            self.lock = __import__("threading").Lock()
            self.saved = 0

        def _recent_for_project(self, *args, **kwargs):
            return []

        def save_run(self, *, language, region_code, data):
            with self.lock:
                if self.saved:
                    raise RuntimeError("duplicate key value violates unique constraint")
                self.saved += 1
                return 42

    backend = Backend()
    adapter = object.__new__(ServerMemory)
    adapter.backend = backend
    adapter.memory = object()

    outcomes = await asyncio.gather(
        adapter.create_run("alpha", {"status": "requested"}),
        adapter.create_run("alpha", {"status": "requested"}),
        return_exceptions=True,
    )
    assert sum(item == 42 for item in outcomes) == 1
    assert sum(isinstance(item, DirectorCycleAlreadyRunning) for item in outcomes) == 1
    assert backend.saved == 1


@pytest.mark.asyncio
async def test_concurrent_different_projects_can_reserve_independently():
    """Fake DB enforces uniqueness per project, not globally."""
    import asyncio
    import threading

    class Backend:
        TABLE_RUNS = "director_runs"

        def __init__(self):
            self.lock = threading.Lock()
            self.projects = set()

        def _recent_for_project(self, *args, **kwargs):
            return []

        def save_run(self, *, language, region_code, data):
            with self.lock:
                project = data["project_id"]
                if project in self.projects:
                    raise RuntimeError("duplicate key")
                self.projects.add(project)
                return len(self.projects)

    backend = Backend()
    adapter = object.__new__(ServerMemory)
    adapter.backend = backend
    adapter.memory = object()

    results = await asyncio.gather(
        adapter.create_run("alpha", {"status": "requested"}),
        adapter.create_run("beta", {"status": "requested"}),
    )
    assert set(results) == {1, 2}
    assert backend.projects == {"alpha", "beta"}
