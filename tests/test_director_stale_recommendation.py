"""Regression: a new autonomous wake must not reuse a prior recommendation."""
from types import SimpleNamespace

import pytest

from director.autonomy import DirectorAutonomy
from director.director import Director


@pytest.mark.asyncio
async def test_new_wake_discards_previous_result_before_cycle(monkeypatch):
    previous = SimpleNamespace(recommendation={"recommendation_id": "old"})
    director = object.__new__(Director)
    director.last_result = previous
    director.state = SimpleNamespace(metadata={"current_decision": {"decision_id": "old"}})
    director.autonomy_config = None
    director.project_id = "offline-project"
    director.context = SimpleNamespace(objective="offline")
    observed = {}

    async def fake_run(self, **kwargs):
        observed["last_result"] = director.last_result
        observed["current_decision"] = director.state.metadata.get("current_decision")
        return SimpleNamespace(state=director.state)

    monkeypatch.setattr(DirectorAutonomy, "run", fake_run)
    await director.run_autonomous_cycle()

    assert observed == {"last_result": None, "current_decision": None}
    assert director.last_result is None
