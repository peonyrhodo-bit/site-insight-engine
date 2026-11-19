"""Regression checks for bounded Supabase memory history reads.

Run with: python -m unittest discover -s tests -p 'test_memory_pagination.py'
No network, database, or Director autonomous run is required.
"""
import unittest
from types import SimpleNamespace

from memory.supabase import SupabaseMemoryBackend
from memory.read_status import MemoryTableReadError


class FakeQuery:
    def __init__(self, client):
        self.client = client
        self.start = self.stop = None

    def select(self, fields):
        self.client.fields.append(fields)
        return self

    def order(self, key, desc=False):
        return self

    def range(self, start, stop):
        self.start, self.stop = start, stop
        return self

    def execute(self):
        self.client.windows.append((self.start, self.stop))
        if self.client.fail_at is not None and self.start >= self.client.fail_at:
            raise RuntimeError("statement timeout")
        return SimpleNamespace(data=self.client.rows[self.start:self.stop + 1])


class FakeClient:
    def __init__(self, rows, fail_at=None):
        self.rows, self.fail_at = rows, fail_at
        self.windows, self.fields = [], []

    def table(self, name):
        return FakeQuery(self)


class MemoryPaginationTests(unittest.TestCase):
    def make_backend(self, rows, fail_at=None):
        client = FakeClient(rows, fail_at)
        return SupabaseMemoryBackend(client=client), client

    def test_bounded_first_page_preserves_result(self):
        rows = [
            {"id": i, "created_at": str(i), "project_id": "a", "data_json": {"large": "x" * 10000}}
            for i in range(160, 0, -1)
        ]
        backend, client = self.make_backend(rows)
        result = backend.get_recent_runs(limit=10, project_id="a")
        self.assertEqual([r["id"] for r in result], list(range(160, 150, -1)))
        self.assertEqual(client.windows, [(0, 49)])
        self.assertEqual(client.fields, ["*"])

    def test_legacy_nested_project_and_multiple_pages(self):
        rows = [{"id": i, "project_id": "other", "data_json": {}} for i in range(160, 10, -1)]
        rows += [
            {"id": 10, "project_id": None, "data_json": {"project_id": "a"}},
            {"id": 9, "project_id": "a", "data_json": {}},
        ]
        backend, client = self.make_backend(rows)
        result = backend.get_recent_runs(limit=2, project_id="a")
        self.assertEqual([r["id"] for r in result], [10, 9])
        self.assertEqual(client.windows, [(0, 49), (50, 99), (100, 149), (150, 199)])

    def test_read_failure_is_not_silent(self):
        rows = [{"id": i, "project_id": "other"} for i in range(60, 0, -1)]
        backend, _ = self.make_backend(rows, fail_at=50)
        with self.assertRaises(MemoryTableReadError):
            backend.get_recent_runs(limit=2, project_id="a")


if __name__ == "__main__":
    unittest.main()
