import pytest

import server


class FakeScheduler:
    def __init__(self):
        self.list_calls = 0
        self.schedule_calls = 0

    def list(self, **kwargs):
        self.list_calls += 1
        return []

    def schedule_interval(self, **kwargs):
        self.schedule_calls += 1


class FakeWakeup:
    def __init__(self):
        self.collect_calls = 0

    def collect_due(self, scheduler):
        self.collect_calls += 1


@pytest.mark.asyncio
async def test_disabled_autonomous_mode_does_not_schedule_or_start_worker(monkeypatch):
    scheduler = FakeScheduler()
    wakeup = FakeWakeup()
    monkeypatch.setattr(server, "AUTONOMOUS_ENABLED", False)
    monkeypatch.setattr(server.runtime, "scheduler", scheduler)
    monkeypatch.setattr(server.runtime, "wakeup", wakeup)
    monkeypatch.setattr(server.runtime, "autonomous_worker", None)

    await server.startup()
    assert server.runtime.autonomous_worker is None

    # Defense in depth: directly invoking the worker must also be inert.
    await server._autonomous_worker_loop()
    assert scheduler.list_calls == 0
    assert scheduler.schedule_calls == 0
    assert wakeup.collect_calls == 0
