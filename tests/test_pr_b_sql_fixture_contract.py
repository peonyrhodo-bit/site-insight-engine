"""Static safety contract for the disposable PR-B PostgreSQL schema.

No database connections or SQL execution.
"""
from pathlib import Path
import re

SCHEMA = Path(__file__).parent / "fixtures" / "pr_b_isolated_schema.sql"


def test_fixture_is_explicitly_disposable_and_transaction_wrapped():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "DO NOT APPLY TO PRODUCTION" in sql
    assert re.search(r"(?im)^BEGIN;\s*$", sql)
    assert re.search(r"(?im)^COMMIT;\s*$", sql)


def test_fixture_has_unique_key_and_active_project_guards():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "UNIQUE (project_id, idempotency_key)" in sql
    assert re.search(
        r"CREATE UNIQUE INDEX pr_b_one_active_per_project\s+"
        r"ON pr_b_reservations \(project_id\)\s+"
        r"WHERE status IN \('requested', 'running'\)",
        sql,
    )


def test_fixture_rejects_completed_rows_without_valid_result():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "status <> 'completed'" in sql
    assert "result_json IS NOT NULL" in sql
    assert "jsonb_typeof(result_json) = 'object'" in sql
    assert "result_json <> '{}'::jsonb" in sql


def test_fixture_does_not_target_real_tables_or_enable_privileged_code():
    sql = SCHEMA.read_text(encoding="utf-8")
    statements = re.sub(r"(?m)^\s*--.*$", "", sql)
    assert not re.search(r"\bdirector_runs\b", statements, re.I)
    assert not re.search(
        r"\b(SECURITY\s+DEFINER|GRANT|ALTER\s+TABLE|DROP\s+TABLE|"
        r"CREATE\s+EXTENSION|DO\s+\$\$)\b",
        statements,
        re.I,
    )
