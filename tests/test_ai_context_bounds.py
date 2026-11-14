import json

import pytest

from ai.prompts import _serialize_context
from director.director import Director


def test_ai_decision_context_is_bounded_and_reports_omissions():
    director = Director(project_id="project")
    director.context.observations = [
        {"video_id": f"v{i}", "title": "x" * 5000} for i in range(50)
    ]
    director.context.opportunities = [
        {"title": f"opportunity-{i}", "evidence": [{"text": "e"}] * 50}
        for i in range(50)
    ]

    payload = director.to_ai_decision_dict()

    assert payload["observation_count"] == 50
    assert len(payload["observations"]) == 8
    assert len(payload["opportunities"]) == 20
    assert payload["ai_context_limits"]["full_evidence_retained_in_director"] is True
    assert payload["ai_context_limits"]["omitted_top_level_records"]["observations"] == 42
    assert len(payload["observations"][0]["title"]) <= 4001


def test_ai_prompt_serializer_uses_compact_json():
    value = _serialize_context({"items": [1, 2], "text": "ok"})
    assert value == '{"items":[1,2],"text":"ok"}'
    assert json.loads(value) == {"items": [1, 2], "text": "ok"}


def test_ai_prompt_serializer_rejects_oversized_context(monkeypatch):
    monkeypatch.setenv("DIRECTOR_AI_CONTEXT_MAX_BYTES", "64000")
    with pytest.raises(ValueError, match="exceeds the configured safe limit"):
        _serialize_context({"payload": "x" * 65000})


@pytest.mark.asyncio
async def test_decision_enrichment_receives_bounded_context():
    captured = {}

    class AI:
        async def generate_decision(self, context):
            captured.update(context)
            return {"rationale": "bounded", "confidence": 0.7}

    director = Director(project_id="project", ai_service=AI())
    director.context.observations = [{"video_id": str(i)} for i in range(40)]
    director.context.opportunities = [{"title": str(i)} for i in range(40)]
    from director.decision import DecisionStatus, DecisionType, DirectorDecision

    decision = DirectorDecision(
        decision_id="d", decision_type=DecisionType.WAIT,
        status=DecisionStatus.PROPOSED, objective="test",
        rationale="original", confidence=0.5,
    )
    result = await director._enrich_decision_with_ai(decision, {})

    assert result.rationale == "bounded"
    assert len(captured["director_context"]["observations"]) == 8
    assert captured["director_context"]["observation_count"] == 40
    assert "omitted_opportunities" in captured["analysis"]
