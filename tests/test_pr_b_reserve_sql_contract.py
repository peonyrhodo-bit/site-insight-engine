"""Offline checks for unexecuted, disposable reservation SQL."""
from pathlib import Path

SQL = (Path(__file__).parent / "fixtures" / "pr_b_reserve_function.sql").read_text()


def test_reserve_is_test_scoped_and_invoker_only():
    assert "CREATE OR REPLACE FUNCTION pr_b_test_reserve(" in SQL
    assert "SECURITY INVOKER" in SQL
    assert "SECURITY DEFINER" not in SQL
    assert "INSERT INTO pr_b_reservations" in SQL
    assert "director_runs" not in SQL


def test_reserve_uses_atomic_unique_constraint_and_indexed_reconciliation():
    assert "ON CONFLICT DO NOTHING" in SQL
    assert "RETURNING id, fencing_generation" in SQL
    assert "r.project_id = p_project_id" in SQL
    assert "r.idempotency_key = p_idempotency_key" in SQL


def test_reserve_fails_closed_for_conflict_and_invalid_completed_result():
    for outcome in (
        "reconcile_required", "fingerprint_conflict",
        "storage_error", "in_progress_conflict", "replay", "reserved",
    ):
        assert f"'{outcome}'::text" in SQL
    assert "v_fingerprint IS DISTINCT FROM p_fingerprint" in SQL
    assert "jsonb_typeof(v_result) <> 'object'" in SQL
    assert "v_result = '{}'::jsonb" in SQL
