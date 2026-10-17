from types import SimpleNamespace

import pytest

from director.director import Director
from server import Runtime
from director.state_snapshot import (
    REQUIRED_PARAMETERS,
    STATUS_KNOWN,
    STATUS_UNKNOWN,
    build_unified_state_snapshot,
    validate_unified_state_snapshot,
)


def test_snapshot_represents_every_required_parameter():
    context = SimpleNamespace(
        project_id="test-project",
        metadata={},
        decisions=[],
        recommendations=[],
        research_history=[],
        observations=[],
        constraints=[],
        feedback=[],
        topics={},
        ai_service=None,
    )

    snapshot = build_unified_state_snapshot(context)

    assert len(REQUIRED_PARAMETERS) == 27
    assert snapshot["completeness"]["represented_count"] == 27
    assert set(snapshot["parameters"]) == {key for _, key, _ in REQUIRED_PARAMETERS}
    assert validate_unified_state_snapshot(snapshot) == []


def test_unknown_parameter_requires_explicit_reason():
    context = SimpleNamespace(
        project_id="test-project",
        metadata={},
        decisions=[],
        recommendations=[],
        research_history=[],
        observations=[],
        constraints=[],
        feedback=[],
        topics={},
        ai_service=None,
    )
    snapshot = build_unified_state_snapshot(context)
    snapshot["parameters"]["ai_availability"]["status"] = STATUS_UNKNOWN
    snapshot["parameters"]["ai_availability"].pop("reason", None)

    errors = validate_unified_state_snapshot(snapshot)

    assert "ai_availability: unknown status requires a reason" in errors


def test_missing_required_parameter_fails_validation():
    context = SimpleNamespace(
        project_id="test-project",
        metadata={},
        decisions=[],
        recommendations=[],
        research_history=[],
        observations=[],
        constraints=[],
        feedback=[],
        topics={},
        ai_service=None,
    )
    snapshot = build_unified_state_snapshot(context)
    del snapshot["parameters"]["end_of_day_plan"]

    assert "end_of_day_plan: missing required parameter" in validate_unified_state_snapshot(snapshot)


def test_configured_ai_is_not_mistaken_for_live_availability():
    context = SimpleNamespace(
        project_id="test-project",
        metadata={},
        decisions=[],
        recommendations=[],
        research_history=[],
        observations=[],
        constraints=[],
        feedback=[],
        topics={},
        ai_service=object(),
    )

    snapshot = build_unified_state_snapshot(context)

    assert snapshot["parameters"]["ai_availability"]["status"] == STATUS_UNKNOWN
    assert "фактическая проверка" in snapshot["parameters"]["ai_availability"]["reason"]


class MemoryService:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail

    async def get_context(self, **kwargs):
        if self.should_fail:
            raise ConnectionError("database unavailable")
        return {"runs": [], "events": [], "actions": [], "results": [], "recommendations": []}


class DataService:
    async def get_project_state(self, *, project_id):
        return {
            "project_id": project_id,
            "data_inventory": {
                "video_count": 3,
                "snapshot_count": 4,
                "query_count": 2,
            },
        }


@pytest.mark.asyncio
async def test_inspect_attaches_snapshot_and_records_successful_probes():
    director = Director(
        project_id="test-project",
        memory_service=MemoryService(),
        data_service=DataService(),
    )

    context = await director.inspect()
    snapshot = director.get_unified_state_snapshot()

    assert snapshot["completeness"]["represented_count"] == 27
    assert snapshot["completeness"]["valid"] is True
    assert context.metadata["runtime_health"]["memory"]["status"] == "healthy"
    assert context.metadata["runtime_health"]["project_data"]["status"] == "healthy"
    assert snapshot["parameters"]["persistence_and_memory"]["status"] == STATUS_KNOWN


@pytest.mark.asyncio
async def test_inspect_records_memory_failure_instead_of_claiming_health():
    director = Director(
        project_id="test-project",
        memory_service=MemoryService(should_fail=True),
        data_service=DataService(),
    )

    context = await director.inspect()
    snapshot = director.get_unified_state_snapshot()

    assert context.metadata["runtime_health"]["memory"]["status"] == "unavailable"
    assert snapshot["parameters"]["persistence_and_memory"]["status"] == STATUS_KNOWN
    assert snapshot["parameters"]["persistence_and_memory"]["value"]["status"] == "unavailable"



@pytest.mark.asyncio
async def test_runtime_health_uses_read_only_quota_probe_and_does_not_infer_ai_health(monkeypatch):
    class QuotaManager:
        def get_status(self):
            return {"search_remaining": 12, "other_remaining": 90}

    runtime = Runtime.__new__(Runtime)
    runtime.ai = SimpleNamespace(provider=object(), provider_error=None)
    runtime.scheduler = SimpleNamespace(enabled=True)
    runtime.quota_manager = QuotaManager()
    monkeypatch.delenv("YOUTUBE_MCP_URL", raising=False)
    monkeypatch.delenv("MCP_URL", raising=False)

    health = await runtime.collect_runtime_health("test-project")

    assert health["ai"]["status"] == "unknown"
    assert health["scheduler"]["status"] == "available"
    assert health["quota_manager"]["status"] == "healthy"
    assert health["active_cycle"]["active"] is False
    assert health["youtube_sources"]["status"] == "unknown"
    assert health["website"]["status"] == "unknown"
