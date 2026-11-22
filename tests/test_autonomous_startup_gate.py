"""Offline regression for the autonomous worker startup gate."""
import ast

import pytest
from pathlib import Path


def test_worker_startup_is_gated_by_autonomous_enabled():
    tree = ast.parse(Path("server.py").read_text(encoding="utf-8"))
    startup = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "startup"
    )
    creates_worker = [
        node for node in ast.walk(startup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_task"
    ]
    assert len(creates_worker) == 1
    guarded = [
        node for node in ast.walk(startup)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "AUTONOMOUS_ENABLED"
        and any(call in ast.walk(node) for call in creates_worker)
    ]
    assert len(guarded) == 1


def test_autonomous_mode_defaults_off():
    tree = ast.parse(Path("server.py").read_text(encoding="utf-8"))
    definitions = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "AUTONOMOUS_ENABLED" for target in node.targets)
    ]
    assert len(definitions) == 1
    source = ast.get_source_segment(Path("server.py").read_text(encoding="utf-8"), definitions[0])
    assert 'os.getenv("AUTONOMOUS_ENABLED", "false")' in source


@pytest.mark.asyncio
async def test_shutdown_cancels_autonomous_worker_and_clears_reference(monkeypatch):
    """A live background worker must not survive application shutdown."""
    import asyncio
    import server

    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_worker():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(fake_worker())
    monkeypatch.setattr(server.runtime, "autonomous_worker", task)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(server.shutdown(), timeout=2)
        assert cancelled.is_set()
        assert task.cancelled()
        assert server.runtime.autonomous_worker is None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_shutdown_without_worker_is_safe(monkeypatch):
    import server

    monkeypatch.setattr(server.runtime, "autonomous_worker", None)
    await server.shutdown()
    assert server.runtime.autonomous_worker is None


@pytest.mark.asyncio
async def test_first_autonomous_wake_is_delayed_by_interval(monkeypatch):
    """Enabling the worker must not immediately execute a costly cycle."""
    import asyncio
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import server

    scheduled = []
    class FakeScheduler:
        def list(self, *, project_id):
            return []
        def schedule_interval(self, **kwargs):
            scheduled.append(kwargs)
    class FakeWakeup:
        def collect_due(self, scheduler):
            raise AssertionError("worker should be cancelled before polling")
    monkeypatch.setattr(server.runtime, "scheduler", FakeScheduler())
    monkeypatch.setattr(server.runtime, "wakeup", FakeWakeup())
    monkeypatch.setattr(server, "AUTONOMOUS_WAKE_INTERVAL_SECONDS", 3600)
    before = datetime.now(timezone.utc)
    task = asyncio.create_task(server._autonomous_worker_loop())
    try:
        for _ in range(100):
            if scheduled:
                break
            await asyncio.sleep(0)
        assert len(scheduled) == 1
        delay = (scheduled[0]["first_run_at"] - before).total_seconds()
        assert 3599 <= delay <= 3605
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
