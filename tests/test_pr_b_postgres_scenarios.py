"""Two-connection PostgreSQL integration scenario specifications.

Collection is safe: no database connection, SQL execution or side effects.
Execution stays disabled pending owner approval and isolated DB verification.
"""
import pytest

SCENARIOS = [
    ("PG-01", "same project/key concurrent reserve", "single reservation"),
    ("PG-02", "same project/different keys", "one active run"),
    ("PG-03", "same key/different projects", "independent reservations"),
    ("PG-04", "disconnect after reservation commit", "no duplicate cycle"),
    ("PG-05", "disconnect after completion commit", "exact result replay"),
    ("PG-06", "rollback before completion commit", "no partial completion"),
    ("PG-07", "uncertain commit", "indexed reconciliation"),
    ("PG-08", "stale fencing generation", "old worker cannot finalize"),
    ("PG-09", "changed fingerprint", "typed conflict"),
    ("PG-10", "malformed completed result", "fail closed"),
    ("PG-11", "failed or stale heartbeat", "no automatic restart"),
    ("PG-12", "legacy JSON-only rows", "migration gate blocks"),
    ("PG-13", "database failure", "no Director execution"),
    ("PG-14", "concurrent terminal updates", "no lost update"),
    ("PG-15", "large fixture query plan", "indexed bounded lookup"),
]


@pytest.mark.parametrize("case_id,action,invariant", SCENARIOS)
def test_scenario_is_documented_but_not_executed(case_id, action, invariant):
    assert case_id.startswith("PG-")
    assert action and invariant


@pytest.mark.integration
@pytest.mark.parametrize("case_id,action,invariant", SCENARIOS)
def test_real_postgres_requires_separate_approval(case_id, action, invariant):
    pytest.skip(
        f"{case_id}: no approved disposable PostgreSQL fixture or two-connection runner"
    )
