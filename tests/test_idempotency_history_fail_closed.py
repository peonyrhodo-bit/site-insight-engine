from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import server


class FailingHistoryBackend:
    TABLE_RUNS = "director_runs"

    def _recent_for_project(self, table_name, *, limit, project_id, order_key):
        raise RuntimeError("temporary database read failure")


@pytest.mark.asyncio
async def test_idempotent_request_fails_closed_when_history_cannot_be_read(monkeypatch):
    project_id = "test-history-outage"
    idempotency_key = "same-request-key"
    cache_key = f"{project_id}:{idempotency_key}"
    server._DIRECTOR_REQUEST_LOCKS.pop(cache_key, None)
    server._DIRECTOR_REQUEST_RESULTS.pop(cache_key, None)
    monkeypatch.setattr(
        server.runtime,
        "memory",
        SimpleNamespace(backend=FailingHistoryBackend()),
    )

    async def must_not_start_new_run(**kwargs):
        raise AssertionError("must not start work when idempotency history is unavailable")

    monkeypatch.setattr(server, "_run_director_once", must_not_start_new_run)

    with pytest.raises(HTTPException) as exc_info:
        await server._run_director(
            project_id=project_id,
            language="en",
            region_code="US",
            hours_back=72,
            max_results=25,
            objective=None,
            idempotency_key=idempotency_key,
        )

    assert exc_info.value.status_code == 503
    assert "Cannot verify idempotency history" in exc_info.value.detail
    assert cache_key not in server._DIRECTOR_REQUEST_RESULTS
