import logging

import pytest

import server
from ai.provider import AIProviderResponseError
from director.decision import DecisionStatus, DecisionType, DirectorDecision
from director.director import Director


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    async def generate_json(self, **kwargs):
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_ai_timeout_is_logged_and_propagated(monkeypatch, caplog):
    monkeypatch.setattr(server, "FREE_MODE", False)
    monkeypatch.setattr(
        server,
        "create_ai_provider",
        lambda: FakeProvider(error=TimeoutError("model request timed out")),
    )
    caplog.set_level(logging.ERROR, logger="site-insight-engine")

    adapter = server.AIAdapter()

    with pytest.raises(TimeoutError, match="timed out"):
        await adapter.generate_decision({})

    assert "AI decision generation failed" in caplog.text
    assert "model request timed out" in caplog.text


@pytest.mark.asyncio
async def test_malformed_ai_response_is_not_silently_converted_to_empty_dict(
    monkeypatch,
):
    monkeypatch.setattr(server, "FREE_MODE", False)
    monkeypatch.setattr(
        server,
        "create_ai_provider",
        lambda: FakeProvider(result=["not", "an", "object"]),
    )
    adapter = server.AIAdapter()

    with pytest.raises(AIProviderResponseError, match="JSON object"):
        await adapter.generate_decision({})


@pytest.mark.asyncio
async def test_unavailable_provider_reports_reason(monkeypatch):
    monkeypatch.setattr(server, "FREE_MODE", False)

    def fail_provider_creation():
        raise RuntimeError("provider startup failed")

    monkeypatch.setattr(server, "create_ai_provider", fail_provider_creation)
    adapter = server.AIAdapter()

    with pytest.raises(RuntimeError, match="provider startup failed"):
        await adapter.generate_decision({})


@pytest.mark.asyncio
async def test_director_logs_ai_failure_and_keeps_deterministic_decision(caplog):
    class FailingAI:
        async def generate_decision(self, context):
            raise TimeoutError("model request timed out")

    director = Director(project_id="test-project", ai_service=FailingAI())
    decision = DirectorDecision(
        decision_id="decision-test",
        decision_type=DecisionType.WAIT,
        status=DecisionStatus.PROPOSED,
        objective="Test objective",
        rationale="Deterministic rationale",
        confidence=0.5,
    )
    caplog.set_level(logging.WARNING, logger="director.director")

    enriched = await director._enrich_decision_with_ai(decision, {})

    assert enriched is decision
    assert enriched.rationale == "Deterministic rationale"
    assert enriched.metadata["ai_enrichment_status"] == "failed"
    assert "TimeoutError: model request timed out" in (
        enriched.metadata["ai_enrichment_error"]
    )
    assert "continuing with deterministic Director decision" in caplog.text
