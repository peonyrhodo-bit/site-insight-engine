"""Offline contract checks for unexecuted disposable finalize SQL."""
from pathlib import Path

SQL = (Path(__file__).parent / "fixtures" / "pr_b_finalize_function.sql").read_text()


def test_finalize_function_is_invoker_and_test_namespaced():
    assert "CREATE OR REPLACE FUNCTION pr_b_test_finalize(" in SQL
    assert "SECURITY INVOKER" in SQL
    assert "SECURITY DEFINER" not in SQL
    assert "UPDATE pr_b_reservations" in SQL
    assert "UPDATE director_runs" not in SQL


def test_finalize_is_fenced_and_atomic():
    assert "fencing_generation = p_generation" in SQL
    assert "status IN ('requested', 'running')" in SQL
    assert "status = 'completed'" in SQL
    assert "result_json = p_result" in SQL
    assert "GET DIAGNOSTICS v_updated = ROW_COUNT" in SQL
    assert "RETURN v_updated = 1" in SQL


def test_finalize_rejects_missing_or_empty_results():
    assert "p_result IS NULL" in SQL
    assert "jsonb_typeof(p_result) <> 'object'" in SQL
    assert "p_result = '{}'::jsonb" in SQL
    assert "ERRCODE = '22023'" in SQL
