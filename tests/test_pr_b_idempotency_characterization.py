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


@pytest.mark.asyncio
async def test_same_project_same_key_atomic_reservation_contract():
    """Proposed DB contract, modeled offline; no production implementation yet."""
    import asyncio
    import threading

    class FakeAtomicReservations:
        def __init__(self):
            self.lock = threading.Lock()
            self.records = {}
            self.executions = 0

        def reserve(self, project, key):
            with self.lock:
                identity = (project, key)
                if identity in self.records:
                    row = self.records[identity]
                    if row["status"] == "completed":
                        return ("replay", row["result"])
                    return ("conflict", None)
                self.records[identity] = {"status": "in_progress", "result": None}
                self.executions += 1
                return ("reserved", None)

        def complete(self, project, key, result):
            with self.lock:
                self.records[(project, key)] = {
                    "status": "completed", "result": result
                }

    db = FakeAtomicReservations()
    first, second = await asyncio.gather(
        asyncio.to_thread(db.reserve, "alpha", "same-key"),
        asyncio.to_thread(db.reserve, "alpha", "same-key"),
    )
    assert sorted([first[0], second[0]]) == ["conflict", "reserved"]
    assert db.executions == 1

    original = {"status": "completed", "run_id": 42, "result": {"ok": True}}
    db.complete("alpha", "same-key", original)
    assert db.reserve("alpha", "same-key") == ("replay", original)
    assert db.executions == 1


def test_idempotency_contract_isolated_by_project_and_rejects_failed_key():
    """Fake reservation semantics to be enforced by future transactional RPC."""
    class FakeReservations:
        def __init__(self):
            self.rows = {}

        def reserve(self, project, key):
            identity = (project, key)
            if identity not in self.rows:
                self.rows[identity] = "in_progress"
                return "reserved"
            return "conflict"

    db = FakeReservations()
    assert db.reserve("alpha", "key-1") == "reserved"
    assert db.reserve("beta", "key-1") == "reserved"
    db.rows[("alpha", "key-1")] = "failed"
    assert db.reserve("alpha", "key-1") == "conflict"
    assert db.reserve("beta", "key-1") == "conflict"


class FakeDurableReservationStore:
    """Offline transactional contract model, not a Supabase implementation."""

    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self.rows = {}
        self.executions = 0

    def reserve(self, project, key, fingerprint):
        with self._lock:
            identity = (project, key)
            row = self.rows.get(identity)
            if row is not None:
                if row["fingerprint"] != fingerprint:
                    return ("conflict", None)
                if row["status"] == "completed":
                    result = row["result"]
                    if not isinstance(result, dict) or not result:
                        return ("storage_error", None)
                    return ("replay", result)
                return ("conflict", None)
            self.rows[identity] = {
                "fingerprint": fingerprint,
                "status": "in_progress",
                "result": None,
                "generation": 1,
            }
            self.executions += 1
            return ("reserved", 1)

    def complete(self, project, key, generation, result, *, crash_before_commit=False):
        with self._lock:
            row = self.rows[(project, key)]
            if row["generation"] != generation or row["status"] != "in_progress":
                return False
            if crash_before_commit:
                raise RuntimeError("connection lost before commit")
            # Atomic in-memory assignment models one database commit.
            self.rows[(project, key)] = {
                **row, "status": "completed", "result": result
            }
            return True


def test_crash_before_completion_does_not_replay_partial_result():
    store = FakeDurableReservationStore()
    assert store.reserve("alpha", "key", "request-a") == ("reserved", 1)
    with pytest.raises(RuntimeError, match="before commit"):
        store.complete(
            "alpha", "key", 1, {"run_id": 10},
            crash_before_commit=True,
        )
    assert store.reserve("alpha", "key", "request-a") == ("conflict", None)
    assert store.rows[("alpha", "key")]["result"] is None
    assert store.executions == 1


def test_crash_after_completion_replays_exact_persisted_result():
    store = FakeDurableReservationStore()
    store.reserve("alpha", "key", "request-a")
    original = {"run_id": 10, "status": "completed", "nested": {"ok": True}}
    assert store.complete("alpha", "key", 1, original)
    # A worker crash after commit does not erase the durable result.
    assert store.reserve("alpha", "key", "request-a") == ("replay", original)
    assert store.executions == 1


def test_changed_request_fingerprint_and_missing_result_fail_closed():
    store = FakeDurableReservationStore()
    store.reserve("alpha", "key", "request-a")
    assert store.reserve("alpha", "key", "request-b") == ("conflict", None)
    store.complete("alpha", "key", 1, {})
    assert store.reserve("alpha", "key", "request-a") == ("storage_error", None)
    assert store.executions == 1


def test_superseded_worker_fencing_token_blocks_late_completion():
    store = FakeDurableReservationStore()
    store.reserve("alpha", "key", "request-a")
    # Model a separately authorized takeover; not a production retry policy.
    store.rows[("alpha", "key")]["generation"] = 2
    assert not store.complete("alpha", "key", 1, {"old": True})
    assert store.complete("alpha", "key", 2, {"new": True})
    assert store.reserve("alpha", "key", "request-a") == (
        "replay", {"new": True}
    )
