from scheduler.wakeup import WakeupManager, WakeupReason


def test_next_prunes_consumed_signals_without_dropping_pending_work():
    manager = WakeupManager()
    first = manager.create(
        project_id="default",
        reason=WakeupReason.MANUAL,
    )
    second = manager.create(
        project_id="default",
        reason=WakeupReason.NEW_DATA,
    )

    consumed = manager.consume(first.wakeup_id)
    assert consumed is first
    assert first.consumed is True

    # Advancing the queue removes old completed entries, but keeps pending work.
    assert manager.next() is second
    assert first not in manager._queue
    assert second in manager._queue


def test_consumed_queue_does_not_grow_across_many_wakeups():
    manager = WakeupManager()

    for _ in range(200):
        signal = manager.create(
            project_id="default",
            reason=WakeupReason.MANUAL,
        )
        manager.consume(signal.wakeup_id)
        assert manager.next() is None

    assert manager._queue == []


def test_delayed_wakeup_is_not_pending_until_its_available_time(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from scheduler import wakeup as wakeup_module

    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(wakeup_module, "utc_now", lambda: now[0])
    manager = WakeupManager()
    delayed = manager.create(
        project_id="default",
        reason=WakeupReason.RETRY,
        delay_seconds=30,
    )

    assert manager.next() is None
    now[0] += timedelta(seconds=29)
    assert manager.next() is None
    now[0] += timedelta(seconds=1)
    assert manager.next() is delayed
