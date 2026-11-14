import asyncio

import pytest

from director.director import Director
from memory.read_status import MemoryReadError


class PartialMemoryRead(RuntimeError):
    status = "partial"

    def __init__(self):
        self.context = {
            "decisions": [{"decision_id": "decision-from-readable-table"}],
            "recommendations": [],
            "memory_state": {
                "active_constraints": [{"constraint": "respect daily quota"}],
                "pending_recommendations": [],
                "unfinished_actions": [],
                "unresolved_decisions": [],
                "recent_results": [],
                "recent_events": [],
                "recent_chat": [],
                "recent_runs": [],
            },
            "_memory_read": {
                "status": "partial",
                "tables": {
                    "decisions": {"status": "complete", "rows": 1},
                    "chat": {"status": "error", "rows": 0},
                },
                "errors": {"chat": "connection interrupted"},
            },
        }
        self.errors = {"chat": "connection interrupted"}
        super().__init__("memory read was partial")


@pytest.mark.asyncio
async def test_director_uses_partial_memory_but_marks_it_degraded():
    class Memory:
        def get_context(self, **kwargs):
            raise PartialMemoryRead()

    director = Director(project_id="project", memory_service=Memory())
    director.context.decisions = [{"decision_id": "older-local-decision"}]

    context = await director.inspect()

    assert context.decisions == [{"decision_id": "decision-from-readable-table"}]
    assert context.metadata["memory_state"]["active_constraints_count"] if "active_constraints_count" in context.metadata["memory_state"] else context.metadata["memory_state"]["active_constraints"]
    health = context.metadata["runtime_health"]["memory"]
    assert health["status"] == "degraded"
    assert health["read_status"] == "partial"
    assert health["errors"]["chat"] == "connection interrupted"
    assert context.metadata["memory_read"]["status"] == "partial"


@pytest.mark.asyncio
async def test_confirmed_empty_memory_clears_stale_director_context():
    class Memory:
        def get_context(self, **kwargs):
            return {
                "decisions": [],
                "recommendations": [],
                "_memory_read": {
                    "status": "complete",
                    "tables": {
                        "decisions": {"status": "complete", "rows": 0},
                        "recommendations": {"status": "complete", "rows": 0},
                    },
                    "errors": {},
                },
            }

    director = Director(project_id="empty-project", memory_service=Memory())
    director.context.decisions = [{"decision_id": "stale"}]
    director.context.recommendations = [{"recommendation_id": "stale"}]

    context = await director.inspect()

    assert context.decisions == []
    assert context.recommendations == []
    assert context.metadata["runtime_health"]["memory"]["status"] == "healthy"
    assert context.metadata["memory_read"]["status"] == "complete"


@pytest.mark.asyncio
async def test_failed_memory_read_does_not_overwrite_existing_context():
    class Memory:
        def get_context(self, **kwargs):
            raise MemoryReadError("error", errors={"decisions": "database offline"})

    director = Director(project_id="offline-project", memory_service=Memory())
    director.context.decisions = [{"decision_id": "last-known-decision"}]

    context = await director.inspect()

    assert context.decisions == [{"decision_id": "last-known-decision"}]
    assert context.metadata["runtime_health"]["memory"]["status"] == "unavailable"
    assert context.metadata["memory_read"]["status"] == "error"


def test_director_surfaces_semantic_memory_to_understanding_and_ai():
    director = Director(project_id="project")
    director.context.metadata["memory_state"] = {
        "active_constraints": [{"constraint": "daily quota"}],
        "pending_recommendations": [{"recommendation_id": "r1"}],
        "unfinished_actions": [{"action_id": "a1"}],
        "unresolved_decisions": [{"decision_id": "d1"}],
        "recent_results": [],
        "recent_events": [],
        "recent_chat": [],
        "recent_runs": [],
    }
    director.context.metadata["memory_read"] = {"status": "complete"}

    understanding = director.understand()
    ai_context = director.to_ai_decision_dict()

    assert understanding["memory_state"]["active_constraints_count"] == 1
    assert understanding["memory_state"]["unfinished_actions_count"] == 1
    assert ai_context["metadata"]["memory_state"]["active_constraints"][0]["constraint"] == "daily quota"
    assert ai_context["metadata"]["memory_read"]["status"] == "complete"


@pytest.mark.asyncio
async def test_ai_decision_timeout_falls_back_to_director_owned_decision(monkeypatch):
    class SlowAI:
        async def generate_decision(self, context):
            await asyncio.sleep(2)
            return {"rationale": "late AI answer", "confidence": 0.99}

    monkeypatch.setenv("DIRECTOR_AI_DECISION_TIMEOUT_SECONDS", "1")
    director = Director(project_id="project", ai_service=SlowAI())
    from director.decision import DecisionStatus, DecisionType, DirectorDecision

    decision = DirectorDecision(
        decision_id="d-timeout",
        decision_type=DecisionType.WAIT,
        status=DecisionStatus.PROPOSED,
        objective="test",
        rationale="deterministic Director rationale",
        confidence=0.6,
    )

    result = await director._enrich_decision_with_ai(decision, {})

    assert result.rationale == "deterministic Director rationale"
    assert result.confidence == 0.6
    assert result.metadata["ai_enrichment_status"] == "failed"
    assert "TimeoutError" in result.metadata["ai_enrichment_error"]
