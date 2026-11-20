"""Offline manual Director route authorization regression tests."""
import inspect

import pytest
from fastapi import HTTPException

import server


@pytest.mark.asyncio
async def test_manual_run_denied_when_operator_token_unconfigured(monkeypatch):
    monkeypatch.delenv("DIRECTOR_MANUAL_RUN_TOKEN", raising=False)
    with pytest.raises(HTTPException) as error:
        await server.director_autonomous_run(x_director_run_token="any")
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_manual_run_denied_when_header_missing_or_wrong(monkeypatch):
    monkeypatch.setenv("DIRECTOR_MANUAL_RUN_TOKEN", "offline-secret")
    for token in (None, "", "wrong"):
        with pytest.raises(HTTPException) as error:
            await server.director_autonomous_run(x_director_run_token=token)
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_authorized_manual_run_delegates_to_existing_cycle(monkeypatch):
    monkeypatch.setenv("DIRECTOR_MANUAL_RUN_TOKEN", "offline-secret")
    calls = []

    async def fake_cycle(*, project_id, objective):
        calls.append((project_id, objective))
        return {"status": "offline"}

    monkeypatch.setattr(server, "_execute_autonomous_cycle", fake_cycle)
    result = await server.director_autonomous_run(
        project_id="fixture-project", objective="fixture-objective",
        x_director_run_token="offline-secret",
    )
    assert result == {"status": "offline"}
    assert calls == [("fixture-project", "fixture-objective")]
