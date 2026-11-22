"""Read-only identity probe for externally supplied PostgreSQL connections.

No connection creation, credentials, DDL, DML or production integration.
The caller must first approve and independently establish disposable connections.
"""
from dataclasses import dataclass
import ipaddress


@dataclass(frozen=True)
class DatabaseIdentity:
    database: str
    role: str
    server_address: str | None


IDENTITY_QUERY = (
    "SELECT current_database(), current_user, "
    "host(inet_server_addr())"
)


def read_identity(connection) -> DatabaseIdentity:
    """Execute only a fixed, read-only identity SELECT on supplied connection."""
    with connection.cursor() as cursor:
        cursor.execute(IDENTITY_QUERY)
        row = cursor.fetchone()
    if row is None or len(row) != 3:
        raise RuntimeError("Missing PostgreSQL connection identity")
    return DatabaseIdentity(*row)


def verify_pair(conn_a, conn_b, *, database: str, role: str) -> None:
    """Fail closed before any caller-provided fixture SQL is allowed."""
    if not database.startswith("pr_b_test_"):
        raise PermissionError("Non-disposable database")
    if not role or role.lower() in {"postgres", "supabase_admin", "service_role"}:
        raise PermissionError("Privileged role forbidden")
    if conn_a is conn_b:
        raise PermissionError("Two distinct connections required")
    for connection in (conn_a, conn_b):
        identity = read_identity(connection)
        if identity.database != database or identity.role != role:
            raise PermissionError("PostgreSQL identity mismatch")
        if identity.server_address is not None:
            if not ipaddress.ip_address(identity.server_address).is_loopback:
                raise PermissionError("Non-loopback PostgreSQL server")


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        self.queries.append(sql)

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self._cursor = FakeCursor(row)

    def cursor(self):
        return self._cursor


def test_identity_probe_uses_one_fixed_select():
    connection = FakeConnection(("pr_b_test_ci", "pr_b_tester", "127.0.0.1"))
    assert read_identity(connection).database == "pr_b_test_ci"
    assert connection._cursor.queries == [IDENTITY_QUERY]


def test_two_distinct_matching_connections_are_verified():
    a = FakeConnection(("pr_b_test_ci", "pr_b_tester", "127.0.0.1"))
    b = FakeConnection(("pr_b_test_ci", "pr_b_tester", "127.0.0.1"))
    verify_pair(a, b, database="pr_b_test_ci", role="pr_b_tester")


def test_same_connection_cannot_masquerade_as_two():
    a = FakeConnection(("pr_b_test_ci", "pr_b_tester", "127.0.0.1"))
    try:
        verify_pair(a, a, database="pr_b_test_ci", role="pr_b_tester")
    except PermissionError:
        pass
    else:
        raise AssertionError("same connection must be rejected")


def test_identity_mismatch_blocks_fixture_execution():
    a = FakeConnection(("pr_b_test_ci", "pr_b_tester", "127.0.0.1"))
    b = FakeConnection(("postgres", "pr_b_tester", "127.0.0.1"))
    try:
        verify_pair(a, b, database="pr_b_test_ci", role="pr_b_tester")
    except PermissionError:
        pass
    else:
        raise AssertionError("wrong database must be rejected")
