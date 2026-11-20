"""Offline PostgreSQL connection identity contract; never opens a socket.

A real adapter must fetch current_database(), current_user and inet_server_addr()
from EACH independent connection before any test fixture SQL.
"""
from dataclasses import dataclass
import ipaddress


@dataclass(frozen=True)
class ConnectionIdentity:
    database: str
    role: str
    server_address: str | None


def assert_disposable_identity(
    identities: tuple[ConnectionIdentity, ConnectionIdentity],
    *,
    expected_database: str,
    expected_role: str,
) -> None:
    if len(identities) != 2:
        raise ValueError("Exactly two independent connections required")
    if not expected_database.startswith("pr_b_test_"):
        raise PermissionError("Expected database must be disposable")
    if not expected_role or expected_role.lower() in {
        "postgres", "supabase_admin", "service_role",
    }:
        raise PermissionError("Privileged or missing test role forbidden")
    for identity in identities:
        if identity.database != expected_database or identity.role != expected_role:
            raise PermissionError("Connected database/role identity mismatch")
        if identity.server_address is not None:
            address = ipaddress.ip_address(identity.server_address)
            if not address.is_loopback:
                raise PermissionError("Non-loopback PostgreSQL server forbidden")


def test_two_matching_local_test_identities_are_accepted():
    identity = ConnectionIdentity("pr_b_test_ci", "pr_b_tester", "127.0.0.1")
    assert_disposable_identity(
        (identity, identity),
        expected_database="pr_b_test_ci",
        expected_role="pr_b_tester",
    )


def test_one_mismatched_connection_blocks_both():
    good = ConnectionIdentity("pr_b_test_ci", "pr_b_tester", "127.0.0.1")
    bad = ConnectionIdentity("postgres", "pr_b_tester", "127.0.0.1")
    try:
        assert_disposable_identity(
            (good, bad), expected_database="pr_b_test_ci",
            expected_role="pr_b_tester",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("mismatched database must be blocked")


def test_privileged_role_is_rejected():
    identity = ConnectionIdentity("pr_b_test_ci", "postgres", "127.0.0.1")
    try:
        assert_disposable_identity(
            (identity, identity),
            expected_database="pr_b_test_ci", expected_role="postgres",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("privileged role must be blocked")


def test_remote_server_address_is_rejected():
    identity = ConnectionIdentity("pr_b_test_ci", "pr_b_tester", "192.0.2.10")
    try:
        assert_disposable_identity(
            (identity, identity),
            expected_database="pr_b_test_ci", expected_role="pr_b_tester",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("remote server must be blocked")
