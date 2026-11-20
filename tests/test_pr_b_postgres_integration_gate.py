"""Isolated PostgreSQL integration gate. Never points at production by default.

This module is intentionally skipped until a separately approved disposable
database and reservation SQL implementation are available.
"""
import os
from urllib.parse import urlsplit

import pytest


def validate_test_database_url(url: str) -> None:
    """Fail closed unless the DSN is explicitly local and test-named."""
    if not url:
        raise ValueError("PR_B_TEST_DATABASE_URL is required")
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("PostgreSQL URL required")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Only loopback PostgreSQL is permitted")
    if not parsed.path.lstrip("/").startswith("pr_b_test_"):
        raise ValueError("Database name must start with pr_b_test_")
    if not parsed.username or not parsed.password:
        raise ValueError("Explicit test credentials required")


@pytest.mark.parametrize("url", [
    "",
    "postgresql://user:secret@production.example.com/pr_b_test_db",
    "postgresql://user:secret@localhost/postgres",
    "postgresql://user:secret@localhost/pr_b_test_db",
    "https://localhost/pr_b_test_db",
])
def test_rejects_unsafe_database_urls(url):
    if url == "postgresql://user:secret@localhost/pr_b_test_db":
        validate_test_database_url(url)
    else:
        with pytest.raises(ValueError):
            validate_test_database_url(url)


@pytest.mark.integration
def test_reservation_transaction_requires_approved_local_fixture():
    """Placeholder: no connection or SQL execution before explicit approval."""
    url = os.getenv("PR_B_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("No disposable local test PostgreSQL configured")
    validate_test_database_url(url)
    pytest.skip("Transactional SQL fixture not approved or implemented")
