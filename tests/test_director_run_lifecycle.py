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
    def __init__(self, fail=False):
        self.context = SimpleNamespace(objective=None)
        self.last_result = SimpleNamespace(decision=None, recommendation=None)
        self.fail = fail

    async def run_autonomous_cycle(self, objective=None):
        if self.fail:
            raise ValueError("cycle failed")
        return {"status": "succeeded", "message": "ok"}


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
