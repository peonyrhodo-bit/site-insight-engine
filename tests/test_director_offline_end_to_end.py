"""Offline end-to-end smoke: real autonomy state machine -> server persistence.

No YouTube, AI, Supabase or external network calls are made.
"""
from types import SimpleNamespace

import pytest

import server
from director.autonomy import AutonomyConfig, DirectorAutonomy


class MemoryLedger:
    def __init__(self):
        self.runs = {}
        self.calls = []

    async def create_run(self, project_id, run):
        self.runs[1] = {**run, "project_id": project_id}
        self.calls.append(("create_run", 1))
        return 1

    async def update_run(self, run_id, *, project_id, fields):
        self.runs[run_id].update(fields)
        self.calls.append(("update_run", run_id))
        return True

    async def save_decision(self, **kwargs):
        self.calls.append(("decision", kwargs))
        return 11

    async def save_recommendation(self, **kwargs):
        self.calls.append(("recommendation", kwargs))
        return 12

    async def save_result(self, **kwargs):
        self.calls.append(("result", kwargs))
        return 13

    async def save_event(self, **kwargs):
        self.calls.append(("event", kwargs))
        return 14


class OfflineDirector:
    def __init__(self):
        self.context = SimpleNamespace(objective=None)
        self.last_result = SimpleNamespace(decision=None, recommendation=None)
        self.trace = []
        self.researched = False

    async def run_autonomous_cycle(self, objective=None):
        def step(name, value):
            self.trace.append(name)
            return value

        def research(state, payload):
            self.researched = True
            return step("research", {"research_execution": {"status": "completed", "queries_collected": 1}})

        def assess(state, payload):
            return step("assess", {"evidence_sufficient": self.researched})

        def decide(state, payload):
            return step("decide", {"decision_type": "recommend", "decision_id": "decision-1"})

        def recommend(state, payload):
            self.last_result = SimpleNamespace(
                decision={"decision_type": "recommend", "decision_id": "decision-1"},
                recommendation={"recommendation_id": "recommendation-1", "summary": "offline"},
            )
            return step("recommend", self.last_result.recommendation)

        autonomy = DirectorAutonomy(
            config=AutonomyConfig(max_steps_per_cycle=8, max_research_steps=1),
            capabilities=lambda state, payload: step("capabilities", {}),
            inspect=lambda state, payload: step("inspect", {"evidence_available": False}),
            understand=lambda state, payload: step("understand", {}),
            assess=assess,
            research=research,
            analyze=lambda state, payload: step("analyze", {"evidence": "offline"}),
            decide=decide,
            recommend=recommend,
        )
        return await autonomy.run(project_id="offline-project", objective=objective)


@pytest.mark.asyncio
async def test_autonomy_research_decision_recommendation_persisted_end_to_end(monkeypatch):
    memory = MemoryLedger()
    director = OfflineDirector()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: director)
    server._DIRECTOR_CYCLE_LOCKS.pop("offline-project", None)

    result = await server._execute_autonomous_cycle(project_id="offline-project")

    assert director.trace[:4] == ["capabilities", "inspect", "understand", "assess"]
    assert "research" in director.trace
    assert director.trace.index("research") < director.trace.index("analyze")
    assert director.trace.index("analyze") < director.trace.index("decide")
    assert director.trace.index("decide") < director.trace.index("recommend")
    assert result["run_id"] == 1
    assert memory.runs[1]["status"] == "succeeded"
    assert [name for name, _ in memory.calls if name in {"decision", "recommendation", "result", "event"}] == [
        "decision", "recommendation", "result", "event"
    ]
    calls = dict((name, value) for name, value in memory.calls if name in {"decision", "recommendation", "result", "event"})
    assert calls["decision"]["run_id"] == 1
    assert calls["recommendation"]["run_id"] == 1
    assert calls["recommendation"]["decision_db_id"] == 11
    assert calls["result"]["recommendation_db_id"] == 12
    assert calls["event"]["data"]["result_id"] == 13


@pytest.mark.asyncio
async def test_second_wake_without_decision_does_not_persist_previous_recommendation(monkeypatch):
    """The same Director instance may be reused; a new wake must stand alone."""
    memory = MemoryLedger()
    director = OfflineDirector()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: director)
    server._DIRECTOR_CYCLE_LOCKS.pop("offline-project", None)

    first = await server._execute_autonomous_cycle(project_id="offline-project")
    assert first["run_id"] == 1
    assert any(name == "recommendation" for name, _ in memory.calls)

    memory.calls.clear()
    memory.runs.clear()

    async def sleeping_cycle(objective=None):
        # This models a subsequent wake with no new recommendation.
        director.last_result = None
        return {"status": "sleeping", "message": "no new evidence"}

    director.run_autonomous_cycle = sleeping_cycle
    await server._execute_autonomous_cycle(project_id="offline-project")

    names = [name for name, _ in memory.calls]
    assert "recommendation" not in names
    assert "decision" not in names
    assert "result" in names
    assert "event" in names
    assert memory.runs[1]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_disabled_worker_and_authorized_manual_http_run_share_safe_offline_cycle(monkeypatch):
    """Startup stays passive; token-gated HTTP can still run the real persistence path."""
    import httpx

    memory = MemoryLedger()
    director = OfflineDirector()
    monkeypatch.setattr(server.runtime, "memory", memory)
    monkeypatch.setattr(server.runtime, "get_director", lambda **kwargs: director)
    monkeypatch.setattr(server, "AUTONOMOUS_ENABLED", False)
    monkeypatch.setattr(server.runtime, "autonomous_worker", None)
    monkeypatch.setenv("DIRECTOR_MANUAL_RUN_TOKEN", "offline-only-secret")
    server._DIRECTOR_CYCLE_LOCKS.pop("offline-project", None)

    await server.startup()
    assert server.runtime.autonomous_worker is None

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://offline.test") as client:
        denied = await client.post(
            "/director/autonomous/run", params={"project_id": "offline-project"}
        )
        assert denied.status_code == 403
        assert memory.calls == []

        allowed = await client.post(
            "/director/autonomous/run",
            params={"project_id": "offline-project"},
            headers={"X-Director-Run-Token": "offline-only-secret"},
        )

    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["run_id"] == 1
    assert memory.runs[1]["status"] == "succeeded"
    assert director.trace.index("research") < director.trace.index("recommend")
    assert [name for name, _ in memory.calls if name in {"decision", "recommendation", "result", "event"}] == [
        "decision", "recommendation", "result", "event"
    ]
