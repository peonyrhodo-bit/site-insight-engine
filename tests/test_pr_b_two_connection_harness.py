"""Fail-closed two-connection PostgreSQL integration harness scaffold.

Importing this module never connects or executes SQL. Real database execution
requires a separately approved local disposable PostgreSQL and explicit opt-in.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class TestDatabaseTarget:
    url: str
    database: str


def validate_target(url: str) -> TestDatabaseTarget:
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("PostgreSQL URL required")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Loopback-only test database")
    database = parsed.path.lstrip("/")
    if not database.startswith("pr_b_test_") or "/" in database:
        raise ValueError("Disposable pr_b_test_* database required")
    if not parsed.username or not parsed.password:
        raise ValueError("Dedicated test credentials required")
    return TestDatabaseTarget(url, database)


@contextmanager
def two_connections(target: TestDatabaseTarget, *, approved: bool = False):
    """Disabled by default. Do not silently provision or connect.

    A future implementation must check current_database() and current_user
    on BOTH connections before any fixture DDL or test transaction.
    """
    if not approved:
        raise PermissionError("Explicit isolated-database approval required")
    validate_target(target.url)
    raise NotImplementedError(
        "Two-connection adapter requires separately approved implementation"
    )
    yield  # pragma: no cover


def test_scaffold_is_import_safe_and_refuses_unapproved_connections():
    target = validate_target("postgresql://tester:secret@localhost/pr_b_test_ci")
    try:
        with two_connections(target):
            raise AssertionError("unreachable")
    except PermissionError:
        pass
    else:
        raise AssertionError("connection gate must fail closed")


def test_scaffold_rejects_remote_and_nontest_targets():
    for url in (
        "postgresql://tester:secret@db.example.com/pr_b_test_ci",
        "postgresql://tester:secret@localhost/postgres",
    ):
        try:
            validate_target(url)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe target accepted")
