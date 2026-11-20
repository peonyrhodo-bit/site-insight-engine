"""ASGI-level authorization contract; never executes a real Director cycle."""
import httpx
import pytest

import server


@pytest.mark.asyncio
async def test_manual_route_denies_missing_config_and_wrong_header(monkeypatch):
    monkeypatch.delenv("DIRECTOR_MANUAL_RUN_TOKEN", raising=False)
    async def forbidden_cycle(**kwargs):
        raise AssertionError("Unauthorized request must not start Director")
    monkeypatch.setattr(server, "_execute_autonomous_cycle", forbidden_cycle)
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://offline.test") as client:
        response = await client.post("/director/autonomous/run")
        assert response.status_code == 403
        monkeypatch.setenv("DIRECTOR_MANUAL_RUN_TOKEN", "offline-test-secret")
        response = await client.post("/director/autonomous/run", headers={"X-Director-Run-Token": "wrong"})
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_manual_route_accepts_valid_header_and_passes_parameters(monkeypatch):
    monkeypatch.setenv("DIRECTOR_MANUAL_RUN_TOKEN", "offline-test-secret")
    calls = []
    async def fake_cycle(*, project_id, objective):
        calls.append((project_id, objective))
        return {"status": "fixture"}
    monkeypatch.setattr(server, "_execute_autonomous_cycle", fake_cycle)
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://offline.test") as client:
        response = await client.post(
            "/director/autonomous/run",
            params={"project_id": "fixture-project", "objective": "fixture"},
            headers={"X-Director-Run-Token": "offline-test-secret"},
        )
    assert response.status_code == 200
    assert response.json() == {"status": "fixture"}
    assert calls == [("fixture-project", "fixture")]
