import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import server
from scheduler.scheduler import Scheduler
from scheduler import wakeup as wakeup_module
from scheduler.wakeup import WakeupManager, WakeupReason


@pytest.mark.asyncio
async def test_worker_retries_failed_wakeup_once_before_retiring_it(monkeypatch):
    scheduler = Scheduler(enabled=False, default_project_id="default")
    wakeup = WakeupManager()
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(wakeup_module, "utc_now", lambda: now[0])
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
        # Advance a fake clock so delayed retries become eligible without real waits.
        now[0] += timedelta(seconds=seconds)
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
