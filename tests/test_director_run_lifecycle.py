from types import SimpleNamespace

import pytest

import server


class FakeMemory:
    def __init__(self, *, fail_result=False):
        self.rows = {}
        self.next_id = 1
        self.fail_result = fail_result
        self.events = []

    async def create_run(self, project_id, run):
        run_id = self.next_id
        self.next_id += 1
        self.rows[run_id] = {**run, "id": run_id, "project_id": project_id}
        return run_id

    async def update_run(self, run_id, *, project_id, fields):
        self.rows[run_id].update(fields)
        self.rows[run_id]["project_id"] = project_id
        return True

    async def save_decision(self, **kwargs):
        return None

    async def save_recommendation(self, **kwargs):
        return None

    async def save_result(self, **kwargs):
        if self.fail_result:
            raise RuntimeError("result persistence failed")
        return 101

    async def save_event(self, **kwargs):
        self.events.append(kwargs)
        return 201


class FakeDirector:
    def __init__(self, fail=False, status="succeeded"):
        self.context = SimpleNamespace(objective=None)
        self.last_result = SimpleNamespace(decision=None, recommendation=None)
        self.fail = fail
        self.status = status

    async def run_autonomous_cycle(self, objective=None):
        if self.fail:
            raise ValueError("cycle failed")
        return {"status": self.status, "message": "ok"}


@pytest.mark.asyncio
async def test_success_registers_before_execution_and_finishes_with_same_run_id(monkeypatch):
    memory = FakeMemory()
    director = FakeDirector()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: director)

    result = await server._execute_autonomous_cycle(project_id="test-project")

    row = memory.rows[result["run_id"]]
    assert row["status"] == "succeeded"
    assert row["finished_at"] is not None
    assert row["current_step"] == "completed"
    assert memory.events[0]["data"]["run_id"] == result["run_id"]


@pytest.mark.asyncio
async def test_director_error_marks_run_failed(monkeypatch):
    memory = FakeMemory()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: FakeDirector(fail=True))

    with pytest.raises(ValueError, match="cycle failed"):
        await server._execute_autonomous_cycle(project_id="test-project")

    row = memory.rows[1]
    assert row["status"] == "failed"
    assert row["current_step"] == "director_cycle"
    assert "cycle failed" in row["error_message"]


@pytest.mark.asyncio
async def test_result_persistence_error_marks_run_partial(monkeypatch):
    memory = FakeMemory(fail_result=True)
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: FakeDirector())

    with pytest.raises(RuntimeError, match="result persistence failed"):
        await server._execute_autonomous_cycle(project_id="test-project")

    row = memory.rows[1]
    assert row["status"] == "partial"
    assert row["current_step"] == "persisting_result"
    assert "result persistence failed" in row["error_message"]


@pytest.mark.asyncio
async def test_repeated_runs_receive_distinct_ids(monkeypatch):
    memory = FakeMemory()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: FakeDirector())

    first = await server._execute_autonomous_cycle(project_id="test-project")
    second = await server._execute_autonomous_cycle(project_id="test-project")

    assert first["run_id"] != second["run_id"]
    assert memory.rows[first["run_id"]]["status"] == "succeeded"
    assert memory.rows[second["run_id"]]["status"] == "succeeded"



@pytest.mark.asyncio
async def test_director_initialization_error_is_recorded(monkeypatch):
    memory = FakeMemory()
    monkeypatch.setattr(server.runtime, "memory", memory)

    def fail_to_initialize(**kwargs):
        raise RuntimeError("director initialization failed")

    monkeypatch.setattr(server.runtime, "get_director", fail_to_initialize)

    with pytest.raises(RuntimeError, match="director initialization failed"):
        await server._execute_autonomous_cycle(project_id="test-project")

    row = memory.rows[1]
    assert row["status"] == "failed"
    assert row["current_step"] == "initializing"
    assert "director initialization failed" in row["error_message"]


@pytest.mark.asyncio
async def test_unknown_director_status_is_not_marked_succeeded(monkeypatch):
    memory = FakeMemory()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(
        server.runtime,
        "get_director",
        lambda **kwargs: FakeDirector(status="waiting"),
    )

    result = await server._execute_autonomous_cycle(project_id="test-project")

    assert result["status"] == "waiting"
    assert memory.rows[result["run_id"]]["status"] == "partial"


class BlockingDirector(FakeDirector):
    def __init__(self):
        super().__init__()
        self.started = __import__("asyncio").Event()
        self.release = __import__("asyncio").Event()

    async def run_autonomous_cycle(self, objective=None):
        self.started.set()
        await self.release.wait()
        return {"status": "succeeded", "message": "ok"}


@pytest.mark.asyncio
async def test_concurrent_cycle_for_same_project_is_rejected_without_duplicate_run(monkeypatch):
    import asyncio

    memory = FakeMemory()
    director = BlockingDirector()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: director)
    server._DIRECTOR_CYCLE_LOCKS.pop("locked-project", None)

    first = asyncio.create_task(
        server._execute_autonomous_cycle(project_id="locked-project")
    )
    await director.started.wait()

    with pytest.raises(server.DirectorCycleAlreadyRunning):
        await server._execute_autonomous_cycle(project_id="locked-project")

    assert len(memory.rows) == 1
    director.release.set()
    result = await first
    assert memory.rows[result["run_id"]]["status"] == "succeeded"


class FakeRunBackend:
    TABLE_RUNS = "director_runs"

    def __init__(self, rows=None, insert_error=None):
        self.rows = list(rows or [])
        self.insert_error = insert_error
        self.inserted = 0

    def _recent_for_project(self, table_name, *, limit, project_id, order_key):
        assert table_name == self.TABLE_RUNS
        return [
            row for row in self.rows
            if str(row.get("project_id")) == str(project_id)
        ]

    def save_run(self, *, language=None, region_code=None, data=None):
        if self.insert_error:
            raise self.insert_error
        self.inserted += 1
        return 900 + self.inserted


class FakeRunMemory:
    def __init__(self, rows):
        self.rows = {row["id"]: dict(row) for row in rows}
        self.updates = []

    def update_run(self, *, run_id, data):
        self.rows[run_id].update(data)
        self.updates.append((run_id, dict(data)))
        return True


@pytest.mark.asyncio
async def test_stale_run_is_marked_failed_with_diagnostic_reason(monkeypatch):
    from datetime import datetime, timedelta, timezone

    old_stamp = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    row = {
        "id": 176,
        "project_id": "stale-project",
        "status": "running",
        "started_at": old_stamp,
        "updated_at": old_stamp,
        "current_step": "director_cycle",
    }
    backend = FakeRunBackend([row])
    memory = FakeRunMemory([row])
    adapter = object.__new__(server.ServerMemory)
    adapter.backend = backend
    adapter.memory = memory
    monkeypatch.setenv("DIRECTOR_RUN_STALE_TIMEOUT_SECONDS", "60")

    run_id = await adapter.create_run("stale-project", {"status": "requested"})

    assert run_id == 901
    assert memory.rows[176]["status"] == "failed"
    assert memory.rows[176]["current_step"] == "stale_timeout"
    assert "timed out" in memory.rows[176]["error_message"]
    assert "last update" in memory.rows[176]["error_message"]


@pytest.mark.asyncio
async def test_fresh_active_run_blocks_new_run(monkeypatch):
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).isoformat()
    row = {
        "id": 176,
        "project_id": "active-project",
        "status": "running",
        "started_at": stamp,
        "updated_at": stamp,
        "current_step": "director_cycle",
    }
    backend = FakeRunBackend([row])
    memory = FakeRunMemory([row])
    adapter = object.__new__(server.ServerMemory)
    adapter.backend = backend
    adapter.memory = memory
    monkeypatch.setenv("DIRECTOR_RUN_STALE_TIMEOUT_SECONDS", "1800")

    with pytest.raises(server.DirectorCycleAlreadyRunning, match="176"):
        await adapter.create_run("active-project", {"status": "requested"})

    assert backend.inserted == 0
    assert memory.rows[176]["status"] == "running"


@pytest.mark.asyncio
async def test_unique_constraint_race_is_reported_as_active_cycle():
    backend = FakeRunBackend(insert_error=RuntimeError(
        "duplicate key value violates unique constraint director_runs_one_active_project"
    ))
    adapter = object.__new__(server.ServerMemory)
    adapter.backend = backend
    adapter.memory = FakeRunMemory([])

    with pytest.raises(server.DirectorCycleAlreadyRunning) as error:
        await adapter.create_run("race-project", {"status": "requested"})

    assert isinstance(error.value.__cause__, RuntimeError)
    assert "unique constraint" in str(error.value.__cause__)
