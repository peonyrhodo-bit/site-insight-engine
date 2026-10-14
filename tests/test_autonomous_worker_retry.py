import asyncio

import pytest

import server
from scheduler.scheduler import Scheduler
from scheduler.wakeup import WakeupManager, WakeupReason


@pytest.mark.asyncio
async def test_worker_retries_failed_wakeup_once_before_retiring_it(monkeypatch):
    scheduler = Scheduler(default_project_id="default")
    wakeup = WakeupManager()
    original = wakeup.create(
        project_id="default",
        reason=WakeupReason.MANUAL,
        payload={"objective": "test objective"},
    )
    monkeypatch.setattr(server.runtime, "scheduler", scheduler)
    monkeypatch.setattr(server.runtime, "wakeup", wakeup)

    calls = []

    async def execute(*, project_id, objective=None):
        calls.append((project_id, objective))
        if len(calls) == 1:
            raise RuntimeError("temporary dependency failure")
        return {"status": "succeeded"}

    monkeypatch.setattr(server, "_execute_autonomous_cycle", execute)

    async def controlled_sleep(seconds):
        # Let the retry backoff pass, then stop the worker after retry succeeds.
        if len(calls) >= 2 and not wakeup.pending():
            raise asyncio.CancelledError

    monkeypatch.setattr(server.asyncio, "sleep", controlled_sleep)

    with pytest.raises(asyncio.CancelledError):
        await server._autonomous_worker_loop()

    assert calls == [
        ("default", "test objective"),
        ("default", "test objective"),
    ]
    assert original.consumed is True
    assert wakeup.pending() == []
