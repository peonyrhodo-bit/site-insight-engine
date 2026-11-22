"""Offline tests for experimental JSON idempotency candidate lookup."""
from types import SimpleNamespace

import pytest

from memory.supabase import SupabaseMemoryBackend


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.columns = None

    def select(self, columns):
        self.columns = columns
        return self

    def contains(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, desc=False):
        return self

    def execute(self):
        assert self.filters == [("data_json", {"idempotency_key": "request-7"})]
        return SimpleNamespace(data=self.rows)


class Client:
    def __init__(self, rows):
        self.query = Query(rows)

    def table(self, name):
        assert name == "director_runs"
        return self.query


def test_candidate_lookup_accepts_legacy_nested_project_id():
    rows = [
        {"id": 1, "data_json": {"project_id": "alpha", "idempotency_key": "request-7"}},
        {"id": 2, "project_id": "beta", "data_json": {"idempotency_key": "request-7"}},
        {"id": 3, "project_id": "alpha", "data_json": {"idempotency_key": "different"}},
    ]
    client = Client(rows)
    backend = SupabaseMemoryBackend(client=client)
    assert [row["id"] for row in backend.get_idempotency_run_candidates(
        project_id="alpha", idempotency_key="request-7"
    )] == [1]
    assert client.query.columns == "*"


@pytest.mark.parametrize("project_id,key", [("", "request-7"), ("alpha", ""), (" ", "request-7")])
def test_candidate_lookup_rejects_empty_identifiers(project_id, key):
    backend = SupabaseMemoryBackend(client=Client([]))
    with pytest.raises(ValueError):
        backend.get_idempotency_run_candidates(project_id=project_id, idempotency_key=key)


def test_candidate_lookup_does_not_claim_completeness_for_legacy_top_level_key():
    backend = SupabaseMemoryBackend(client=Client([]))
    assert backend.get_idempotency_run_candidates(project_id="alpha", idempotency_key="request-7") == []
    # A missing JSON candidate cannot authorize starting a new Director cycle.
    # The production deduplication path must remain unchanged until migration review.
