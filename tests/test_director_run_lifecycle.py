from types import SimpleNamespace

import pytest

import server


class FakeMemory:
    def __init__(self, *, fail_result=False, empty_result=False):
        self.rows = {}
        self.next_id = 1
        self.fail_result = fail_result
        self.empty_result = empty_result
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
        if self.empty_result:
            return None
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
async def test_internal_director_error_persists_failed_phase_and_reason(monkeypatch):
    memory = FakeMemory()
    director = FakeDirector(status="error")
    # The autonomy layer returns errors as a cycle result rather than raising.
    async def failed_cycle(objective=None):
        return {
            "status": "error",
            "message": "cycle failed",
            "state": {
                "metadata": {
                    "failure": {
                        "phase": "research",
                        "error": "TimeoutError: MCP request timed out",
                    }
                }
            },
        }
    director.run_autonomous_cycle = failed_cycle
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: director)

    result = await server._execute_autonomous_cycle(project_id="test-project")

    row = memory.rows[result["run_id"]]
    assert row["status"] == "partial"
    assert row["current_step"] == "research"
    assert row["error_message"] == "TimeoutError: MCP request timed out"
    assert row["result"]["state"]["metadata"]["failure"]["phase"] == "research"


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


@pytest.mark.asyncio
async def test_active_run_older_than_recent_100_still_blocks_new_cycle(monkeypatch):
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "id": i,
            "project_id": "deep-history",
            "status": "succeeded",
            "created_at": stamp,
            "updated_at": stamp,
        }
        for i in range(1, 126)
    ]
    # This active row is older than the 100 most recent records.
    rows.append({
        "id": 176,
        "project_id": "deep-history",
        "status": "running",
        "started_at": stamp,
        "updated_at": stamp,
        "current_step": "director_cycle",
    })
    backend = FakeRunBackend(rows)
    memory = FakeRunMemory([row for row in rows if row.get("id") == 176])
    adapter = object.__new__(server.ServerMemory)
    adapter.backend = backend
    adapter.memory = memory
    monkeypatch.setenv("DIRECTOR_RUN_STALE_TIMEOUT_SECONDS", "1800")

    with pytest.raises(server.DirectorCycleAlreadyRunning, match="176"):
        await adapter.create_run("deep-history", {"status": "requested"})

    assert backend.inserted == 0


class DecisionFakeMemory(FakeMemory):
    def __init__(self):
        super().__init__()
        self.saved_decisions = []

    async def save_decision(self, **kwargs):
        self.saved_decisions.append(kwargs)
        return 202


class DecisionOnlyDirector(FakeDirector):
    async def run_autonomous_cycle(self, objective=None):
        return {
            "status": "partial",
            "message": "Research paused because the quota is exhausted.",
            "state": {
                "metadata": {
                    "current_decision": {
                        "decision_id": "dec_test123",
                        "decision_type": "research",
                        "objective": "Check a YouTube opportunity",
                        "rationale": "Current evidence is incomplete.",
                        "next_action": "Gather more evidence when quota is available.",
                        "metadata": {
                            "expected_outcome": "Obtain evidence to assess the opportunity."
                        },
                    }
                }
            },
        }


@pytest.mark.asyncio
async def test_decision_is_persisted_when_cycle_stops_before_recommendation(monkeypatch):
    memory = DecisionFakeMemory()
    director = DecisionOnlyDirector()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: director)

    result = await server._execute_autonomous_cycle(project_id="decision-project")

    assert len(memory.saved_decisions) == 1
    saved = memory.saved_decisions[0]
    assert saved["run_id"] == result["run_id"]
    assert saved["decision"]["decision_id"] == "dec_test123"
    assert saved["decision"]["rationale"] == "Current evidence is incomplete."
    assert saved["decision"]["metadata"]["expected_outcome"] == (
        "Obtain evidence to assess the opportunity."
    )


@pytest.mark.asyncio
async def test_cycle_is_not_reported_as_complete_when_decision_persistence_fails(monkeypatch):
    memory = FakeMemory()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: DecisionOnlyDirector())

    with pytest.raises(RuntimeError, match="decision was not persisted"):
        await server._execute_autonomous_cycle(project_id="decision-project")

    row = memory.rows[1]
    assert row["status"] == "partial"
    assert "decision was not persisted" in row["error_message"]



@pytest.mark.asyncio
async def test_missing_result_id_does_not_mark_run_succeeded(monkeypatch):
    memory = FakeMemory(empty_result=True)
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: FakeDirector())

    with pytest.raises(RuntimeError, match="result was not persisted"):
        await server._execute_autonomous_cycle(project_id="test-project")

    row = memory.rows[1]
    assert row["status"] == "partial"
    assert row["current_step"] == "persisting_result"
    assert "result was not persisted" in row["error_message"]


@pytest.mark.asyncio
async def test_recommendation_without_persisted_id_does_not_mark_run_succeeded(monkeypatch):
    memory = FakeMemory()
    director = FakeDirector()
    director.last_result.recommendation = {"title": "Test recommendation", "description": "Test"}
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: director)

    with pytest.raises(RuntimeError, match="recommendation was not persisted"):
        await server._execute_autonomous_cycle(project_id="test-project")

    row = memory.rows[1]
    assert row["status"] == "partial"
    assert row["current_step"] == "persisting_result"
    assert "recommendation was not persisted" in row["error_message"]


@pytest.mark.asyncio
async def test_missing_event_id_does_not_mark_run_succeeded(monkeypatch):
    class MissingEventMemory(FakeMemory):
        async def save_event(self, **kwargs):
            return None

    memory = MissingEventMemory()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: FakeDirector())

    with pytest.raises(RuntimeError, match="run event was not persisted"):
        await server._execute_autonomous_cycle(project_id="test-project")

    row = memory.rows[1]
    assert row["status"] == "partial"
    assert row["current_step"] == "persisting_result"
    assert "run event was not persisted" in row["error_message"]

class OrdinaryCycleMemory:
    def __init__(self, *, fail_at=None, transient_result_failure=False):
        self.fail_at = fail_at
        self.transient_result_failure = transient_result_failure
        self.result_attempts = 0
        self.saved = []

    async def save_run(self, **kwargs):
        self.saved.append(("run", kwargs))
        return None if self.fail_at == "run" else 301

    async def save_decision(self, **kwargs):
        self.saved.append(("decision", kwargs))
        return None if self.fail_at == "decision" else 302

    async def save_recommendation(self, **kwargs):
        self.saved.append(("recommendation", kwargs))
        return None if self.fail_at == "recommendation" else 303

    async def save_result(self, **kwargs):
        self.saved.append(("result", kwargs))
        self.result_attempts += 1
        if self.fail_at == "result":
            return None
        if self.transient_result_failure and self.result_attempts == 1:
            return None
        return 304

    async def save_event(self, **kwargs):
        self.saved.append(("event", kwargs))
        return None if self.fail_at == "event" else 305


class OrdinaryCycleResult:
    def __init__(self, *, decision=None, recommendation=None):
        self.status = "succeeded"
        self.message = "cycle completed"
        self.decision = decision
        self.recommendation = recommendation

    def to_dict(self):
        return {
            "status": self.status,
            "message": self.message,
            "decision": self.decision,
            "recommendation": self.recommendation,
        }


class OrdinaryCycleDirector:
    def __init__(self, *, decision=None, recommendation=None):
        self.context = SimpleNamespace(objective=None)
        self.decision = decision
        self.recommendation = recommendation

    async def run_once(self):
        return OrdinaryCycleResult(
            decision=self.decision,
            recommendation=self.recommendation,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", ["run", "result", "event"])
async def test_ordinary_cycle_does_not_report_success_when_storage_returns_no_id(
    monkeypatch, fail_at
):
    memory = OrdinaryCycleMemory(fail_at=fail_at)
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(
        server.runtime, "get_director", lambda **kwargs: OrdinaryCycleDirector()
    )

    with pytest.raises(server.HTTPException) as error:
        await server._run_director(
            project_id="ordinary-project",
            language="en",
            region_code="US",
            hours_back=24,
            max_results=10,
            objective=None,
        )

    assert error.value.status_code == 500
    assert fail_at in str(error.value.__cause__).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "fail_at"),
    [("decision", "decision"), ("recommendation", "recommendation")],
)
async def test_ordinary_cycle_checks_decision_and_recommendation_persistence(
    monkeypatch, field, fail_at
):
    memory = OrdinaryCycleMemory(fail_at=fail_at)
    director_kwargs = {field: {"id": field}}
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(
        server.runtime,
        "get_director",
        lambda **kwargs: OrdinaryCycleDirector(**director_kwargs),
    )

    with pytest.raises(server.HTTPException) as error:
        await server._run_director(
            project_id="ordinary-project",
            language="en",
            region_code="US",
            hours_back=24,
            max_results=10,
            objective=None,
        )

    assert error.value.status_code == 500
    assert "not persisted" in str(error.value.__cause__)


@pytest.mark.asyncio
async def test_director_result_endpoint_does_not_return_success_for_missing_saved_id(
    monkeypatch,
):
    memory = OrdinaryCycleMemory(fail_at="result")
    monkeypatch.setattr(server.runtime, "memory", memory)

    with pytest.raises(server.HTTPException) as error:
        await server.director_result(
            {"project_id": "ordinary-project", "result": {"value": "test"}}
        )

    assert error.value.status_code == 500
    assert "сохранить результат" in error.value.detail


@pytest.mark.asyncio
async def test_ordinary_cycle_recovers_after_transient_result_persistence_failure(
    monkeypatch,
):
    memory = OrdinaryCycleMemory(transient_result_failure=True)
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(
        server.runtime, "get_director", lambda **kwargs: OrdinaryCycleDirector()
    )
    args = {
        "project_id": "ordinary-project",
        "language": "en",
        "region_code": "US",
        "hours_back": 24,
        "max_results": 10,
        "objective": None,
    }

    with pytest.raises(server.HTTPException):
        await server._run_director(**args)

    result = await server._run_director(**args)

    assert result["status"] == "succeeded"
    assert memory.result_attempts == 2




@pytest.mark.asyncio
async def test_same_idempotency_key_reuses_result_without_running_director_twice(monkeypatch):
    import asyncio

    calls = []
    key = "test-idempotency-replay-116"
    server._DIRECTOR_REQUEST_RESULTS.pop(f"test-project:{key}", None)
    server._DIRECTOR_REQUEST_LOCKS.pop(f"test-project:{key}", None)

    async def fake_find(**kwargs):
        return None

    async def fake_run_once(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(0)
        return {"status": "succeeded", "run_id": "run-116", "message": "ok"}

    monkeypatch.setattr(server, "_find_completed_idempotent_run", fake_find)
    monkeypatch.setattr(server, "_run_director_once", fake_run_once)

    args = dict(
        project_id="test-project", language="en", region_code="US",
        hours_back=72, max_results=25, objective=None,
        idempotency_key=key,
    )
    first, second = await asyncio.gather(
        server._run_director(**args),
        server._run_director(**args),
    )

    assert first == second
    assert first["run_id"] == "run-116"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_completed_persisted_idempotency_key_returns_saved_result(monkeypatch):
    class ContextMemory:
        async def get_context(self, *, project_id, limit_runs):
            assert project_id == "persisted-project"
            assert limit_runs == 100
            return {
                "runs": [{
                    "data_json": {
                        "idempotency_key": "request-abc",
                        "status": "succeeded",
                        "result": {"status": "succeeded", "run_id": "old-run"},
                    }
                }]
            }

    monkeypatch.setattr(server.runtime, "memory", ContextMemory())

    result = await server._find_completed_idempotent_run(
        project_id="persisted-project",
        idempotency_key="request-abc",
    )

    assert result == {"status": "succeeded", "run_id": "old-run"}


@pytest.mark.asyncio
async def test_idempotency_lookup_ignores_different_key_and_incomplete_run(monkeypatch):
    class ContextMemory:
        async def get_context(self, *, project_id, limit_runs):
            return {
                "runs": [
                    {"data_json": {"idempotency_key": "other", "status": "succeeded", "result": {"run_id": "wrong"}}},
                    {"data_json": {"idempotency_key": "same", "status": "running", "result": {"run_id": "incomplete"}}},
                ]
            }

    monkeypatch.setattr(server.runtime, "memory", ContextMemory())

    result = await server._find_completed_idempotent_run(
        project_id="persisted-project",
        idempotency_key="same",
    )

    assert result is None
