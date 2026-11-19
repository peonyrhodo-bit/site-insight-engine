"""Offline checks for the opt-in Memory 2.0 run list."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from memory.read_status import MemoryTableReadError
from memory.supabase import SupabaseMemoryBackend


class RunTable:
    """Model projection, stable ordering and range caps without a connection."""

    def __init__(self, rows, *, response_cap=10, fail_at=None):
        self.rows = rows
        self.response_cap = response_cap
        self.fail_at = fail_at
        self.calls = []
        self.projected_bytes = 0

    def table(self, name):
        assert name == "director_runs"
        self.ordering = []
        return self

    def select(self, columns, *, count=None):
        self.columns = columns
        self.count = count
        return self

    def order(self, key, *, desc):
        self.ordering.append((key, desc))
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        self.calls.append((self.columns, self.start, self.end, self.ordering))
        if self.start == self.fail_at:
            raise RuntimeError("simulated page failure")
        rows = self.rows[:]
        for key, desc in reversed(self.ordering):
            rows.sort(key=lambda row: row[key], reverse=desc)
        end = self.end + 1
        if self.count == "exact":
            end = min(end, self.start + self.response_cap)
        data = rows[self.start:end]
        if self.columns != "*":
            data = [{key: row[key] for key in self.columns.split(",")} for row in data]
            self.projected_bytes += len(json.dumps(data, ensure_ascii=False).encode())
        return SimpleNamespace(data=data, count=len(rows) if self.count == "exact" else None)


def run(run_id, project="a", *, payload=None):
    return {
        "id": run_id,
        "project_id": project,
        "created_at": "2026-11-19T12:00:00Z",
        "started_at": None,
        "finished_at": None,
        "updated_at": None,
        "data_json": payload if payload is not None else {},
    }


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode()


@pytest.mark.parametrize("history_size", [20, 40, 100])
def test_projected_window_ignores_recursive_history_and_preserves_full_source(history_size):
    evidence = {"raw": "x" * 2_336_825}
    nested = {"work_plan": {"basis": {"memory_state": {"recent_results": [evidence]}}}}
    rows = [run(i, payload=nested) for i in range(20)]
    rows += [run(-i - 1, payload=evidence) for i in range(history_size - 20)]
    before = hashlib.sha256(json_bytes(nested)).digest()
    table = RunTable(rows)
    backend = SupabaseMemoryBackend(client=table)

    refs = backend.get_recent_run_refs(project_id="a")
    assert [ref["source_record_id"] for ref in refs] == list(range(19, -1, -1))
    assert all(ref["details_omitted"] and "data_json" not in ref for ref in refs)
    assert len(json_bytes(refs)) == 4220
    assert table.projected_bytes == 2590
    assert table.calls == [
        (backend.RUN_REF_COLUMNS, 0, 9, [("created_at", True), ("id", True)]),
        (backend.RUN_REF_COLUMNS, 10, 19, [("created_at", True), ("id", True)]),
    ]

    full = backend.get_recent_runs(project_id="a", limit=1)[0]
    assert full["id"] == refs[0]["source_record_id"]
    assert hashlib.sha256(json_bytes(full["data_json"])).digest() == before
    assert rows[19]["data_json"] == nested


def test_mixed_projects_and_short_pages_preserve_full_reader_order():
    rows = [
        run(1), run(2, payload={"project_id": "b"}),
        run(3, "b", payload={"project_id": "a"}), run(4),
    ]
    rows[0]["created_at"] = "2026-11-20T00:00:00Z"
    table = RunTable(rows, response_cap=1)
    backend = SupabaseMemoryBackend(client=table)
    refs = backend.get_recent_run_refs(project_id="a")
    full = backend.get_recent_runs(project_id="a")
    assert [ref["id"] for ref in refs] == [row["id"] for row in full] == [1, 4, 2]
    assert [start for _, start, _, _ in table.calls[:-1]] == [0, 1, 2, 3]


def test_nested_legacy_project_stops_at_first_unknown_owner():
    legacy = run(2, None, payload={"old": [{"project_id": "a"}]})
    table = RunTable([run(3), legacy, run(1)])
    backend = SupabaseMemoryBackend(client=table)

    with pytest.raises(MemoryTableReadError) as exc:
        backend.get_recent_run_refs(project_id="a")
    assert [ref["id"] for ref in exc.value.partial_rows] == [3]
    assert "legacy project resolution" in str(exc.value.cause)
    assert "data_json" not in table.calls[0][0]
    assert [row["id"] for row in backend.get_recent_runs(project_id="a")] == [3, 2, 1]


def test_first_page_failure_is_distinct_from_a_confirmed_empty_window():
    assert SupabaseMemoryBackend(client=RunTable([])).get_recent_run_refs(project_id="a") == []
    backend = SupabaseMemoryBackend(client=RunTable([], fail_at=0))
    with pytest.raises(MemoryTableReadError) as exc:
        backend.get_recent_run_refs(project_id="a")
    assert exc.value.partial_rows == []
    assert "simulated page failure" in str(exc.value.cause)


@pytest.mark.parametrize("fail_at,reason,expected_pages", [
    (10, "simulated page failure", 2),
    (None, "page budget exceeded", 5),
])
def test_incomplete_scan_preserves_proven_prefix(fail_at, reason, expected_pages):
    rows = [run(i, "b") for i in range(60)] + [run(61)]
    table = RunTable(rows, fail_at=fail_at)
    backend = SupabaseMemoryBackend(client=table)
    with pytest.raises(MemoryTableReadError) as exc:
        backend.get_recent_run_refs(project_id="a")
    assert [ref["id"] for ref in exc.value.partial_rows] == [61]
    assert reason in str(exc.value.cause)
    assert len(table.calls) == expected_pages


def test_utf8_output_budget_never_returns_an_oversized_reference(monkeypatch):
    owner = "я" * 30
    backend = SupabaseMemoryBackend(client=RunTable([run(2, owner), run(1, owner)]))
    first = backend.get_recent_run_refs(project_id=owner, limit=1)
    monkeypatch.setattr(backend, "RUN_REF_MAX_BYTES", len(json_bytes(first)))
    with pytest.raises(MemoryTableReadError) as exc:
        backend.get_recent_run_refs(project_id=owner)
    assert exc.value.partial_rows == first
    assert "byte budget exceeded" in str(exc.value.cause)


def test_missing_count_cannot_prove_complete_read(monkeypatch):
    table = RunTable([])
    monkeypatch.setattr(table, "execute", lambda: SimpleNamespace(data=[]))
    with pytest.raises(MemoryTableReadError, match="could not be read completely"):
        SupabaseMemoryBackend(client=table).get_recent_run_refs(project_id="a")


def test_sdk_builds_projected_read_with_exact_count():
    import httpx
    from postgrest import SyncPostgrestClient

    def respond(request):
        assert request.method == "GET"
        assert request.url.path == "/director_runs"
        assert request.url.params["select"] == SupabaseMemoryBackend.RUN_REF_COLUMNS
        assert request.url.params["order"] == "created_at.desc,id.desc"
        assert request.url.params["limit"] == "10"
        assert request.headers["prefer"] == "count=exact"
        row = run(42)
        del row["data_json"]
        return httpx.Response(200, headers={"content-range": "0-0/1"}, json=[row])

    with SyncPostgrestClient("https://fixture.invalid") as client:
        with httpx.Client(transport=httpx.MockTransport(respond)) as session:
            client.session = session
            refs = SupabaseMemoryBackend(client=client).get_recent_run_refs(project_id="a")
    assert [ref["source_record_id"] for ref in refs] == [42]
