"""Offline fail-closed reconciliation contract; no DB connections or SQL."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ReservationState:
    status: str
    fingerprint: str
    result: dict | None = None


def reconcile_after_ambiguous_insert(read_by_project_and_key, project, key, fingerprint):
    """Model caller behavior; a NEW indexed read is mandatory.

    No automatic retry, reservation, or Director execution is performed.
    """
    row = read_by_project_and_key(project, key)
    if row is None:
        return ("conflict", None)
    if row.fingerprint != fingerprint:
        return ("fingerprint_conflict", None)
    if row.status == "completed":
        if not isinstance(row.result, dict) or not row.result:
            return ("storage_error", None)
        return ("replay", row.result)
    return ("conflict", None)


def test_ambiguous_insert_requires_new_keyed_read_and_never_starts_cycle():
    calls = []

    def read(project, key):
        calls.append((project, key))
        return ReservationState("requested", "fp")

    assert reconcile_after_ambiguous_insert(read, "project", "key", "fp") == (
        "conflict", None
    )
    assert calls == [("project", "key")]


def test_invisible_or_different_active_key_fails_closed():
    assert reconcile_after_ambiguous_insert(
        lambda project, key: None, "project", "key", "fp"
    ) == ("conflict", None)


def test_reconciliation_replays_only_matching_completed_result():
    payload = {"run_id": 7, "status": "completed"}
    result = reconcile_after_ambiguous_insert(
        lambda project, key: ReservationState("completed", "fp", payload),
        "project", "key", "fp",
    )
    assert result == ("replay", payload)
    assert reconcile_after_ambiguous_insert(
        lambda project, key: ReservationState("completed", "different", payload),
        "project", "key", "fp",
    ) == ("fingerprint_conflict", None)


def test_reconciliation_rejects_corrupt_completed_result():
    assert reconcile_after_ambiguous_insert(
        lambda project, key: ReservationState("completed", "fp", {}),
        "project", "key", "fp",
    ) == ("storage_error", None)


def test_reconciliation_propagates_storage_failure_without_retry():
    def unavailable(project, key):
        raise ConnectionError("test storage unavailable")

    try:
        reconcile_after_ambiguous_insert(unavailable, "project", "key", "fp")
    except ConnectionError:
        pass
    else:
        raise AssertionError("storage error must not become a new reservation")
