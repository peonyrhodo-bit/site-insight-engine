from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from director.director import Director
from server import Runtime, persist_typed_director_records
from director.state_snapshot import (
    REQUIRED_PARAMETERS,
    STATUS_KNOWN,
    STATUS_UNKNOWN,
    assess_freshness,
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


def test_snapshot_reads_typed_strategy_records_from_existing_memory_results():
    context = SimpleNamespace(
        project_id="test-project",
        metadata={
            "memory_state": {
                "recent_runs": [],
                "recent_results": [
                    {"result_type": "hypothesis", "data_json": {"title": "H1", "statement": "Test retention"}},
                    {"result_type": "forecast", "data_json": {"metric": "views", "expected": 1200}},
                    {"result_type": "repeat_measurement", "data_json": {"due_at": "2026-10-18T12:00:00Z"}},
                    {"result_type": "conclusion_revision", "data_json": {"reason": "New evidence"}},
                    {"result_type": "daily_plan", "data_json": {"tasks": ["review results"]}},
                    {"result_type": "research_set", "data_json": {"research_id": "r1", "missing_data": ["retention by source"]}},
                ],
                "unfinished_actions": [
                    {"action_type": "video_script", "status": "pending", "description": "Prepare video script"},
                    {"action_type": "user_confirmation", "status": "waiting_for_user", "description": "Approve next research batch"},
                ],
                "pending_recommendations": [{"status": "pending", "title": "Test new format"}],
                "unresolved_decisions": [{"status": "proposed", "decision": "Run experiment"}],
                "recent_events": [],
            }
        },
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
    params = snapshot["parameters"]

    assert params["hypotheses"]["status"] == STATUS_KNOWN
    assert params["forecasts"]["status"] == STATUS_KNOWN
    assert params["due_measurements"]["status"] == STATUS_KNOWN
    assert params["under_researched_directions"]["status"] == STATUS_KNOWN
    assert params["changed_conclusions"]["status"] == STATUS_KNOWN
    assert params["end_of_day_plan"]["status"] == STATUS_KNOWN
    assert params["video_preparation_tasks"]["status"] == STATUS_KNOWN
    assert params["pending_user_tasks"]["status"] == STATUS_KNOWN
    assert params["created_recommendations"]["status"] == STATUS_KNOWN
    assert params["accepted_rejected_decisions"]["status"] == STATUS_KNOWN
    assert validate_unified_state_snapshot(snapshot) == []


@pytest.mark.asyncio
async def test_runtime_health_preserves_mcp_upstream_configuration_status(monkeypatch):
    import json
    import server

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps({
                "service": "youtube-mcp",
                "status": "degraded",
                "checks": {
                    "youtube_api_key_configured": False,
                    "central_quota_authority_configured": True,
                },
                "youtube_api_live_probe": "not_performed_to_avoid_quota_consumption",
            }).encode("utf-8")

    runtime = Runtime.__new__(Runtime)
    runtime.ai = SimpleNamespace(provider=None, provider_error=None)
    runtime.scheduler = SimpleNamespace(enabled=True)
    runtime.quota_manager = SimpleNamespace(get_status=lambda: {"search_remaining": 5})
    monkeypatch.setenv("YOUTUBE_MCP_URL", "https://mcp.example")
    monkeypatch.delenv("MCP_URL", raising=False)
    monkeypatch.setattr(server.urllib.request, "urlopen", lambda *args, **kwargs: Response())

    health = await runtime.collect_runtime_health("test-project")

    assert health["youtube_sources"]["status"] == "degraded"
    assert health["youtube_sources"]["checks"]["youtube_api_key_configured"] is False
    assert health["youtube_sources"]["youtube_api_live_probe"] == "not_performed_to_avoid_quota_consumption"


@pytest.mark.asyncio
async def test_runtime_health_probes_explicit_website_endpoint_without_claiming_write_health(monkeypatch):
    import server

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b'{"status":"ok"}'

    runtime = Runtime.__new__(Runtime)
    runtime.ai = SimpleNamespace(provider=None, provider_error=None)
    runtime.scheduler = SimpleNamespace(enabled=True)
    runtime.quota_manager = SimpleNamespace(get_status=lambda: {"search_remaining": 5})
    monkeypatch.setenv("DIRECTOR_WEBSITE_HEALTH_URL", "https://website.example/health")
    monkeypatch.delenv("YOUTUBE_MCP_URL", raising=False)
    monkeypatch.delenv("MCP_URL", raising=False)
    monkeypatch.setattr(server.urllib.request, "urlopen", lambda *args, **kwargs: Response())

    health = await runtime.collect_runtime_health("test-project")

    assert health["website"]["status"] == "healthy"
    assert health["website"]["http_status"] == 200
    assert health["website"]["recommendation_persistence"] == "not_probed_by_http_health_check"


def test_snapshot_reads_measurement_due_time_from_scheduler_and_raw_action_history():
    context = SimpleNamespace(
        project_id="test-project",
        metadata={
            "actions": [
                {"action_type": "user_confirmation", "status": "waiting_for_user", "description": "Approve research batch"}
            ],
        },
        decisions=[],
        recommendations=[],
        research_history=[],
        observations=[],
        constraints=[],
        feedback=[],
        topics={},
        ai_service=None,
    )
    runtime_health = {
        "scheduler": {
            "status": "available",
            "queue_inspection": "successful",
            "scheduled_items": [
                {
                    "schedule_id": "measurement-1",
                    "reason": "repeat measurement: channel growth",
                    "run_at": "2020-01-01T00:00:00+00:00",
                    "status": "active",
                    "metadata": {"task_type": "repeat_measurement"},
                }
            ],
            "durable_across_restart": False,
        }
    }

    snapshot = build_unified_state_snapshot(context, runtime_health=runtime_health)
    params = snapshot["parameters"]

    assert params["due_measurements"]["status"] == STATUS_KNOWN
    assert params["due_measurements"]["value"]["due"][0]["schedule_id"] == "measurement-1"
    assert params["pending_user_tasks"]["status"] == STATUS_KNOWN
    assert params["pending_user_tasks"]["value"][0]["action_type"] == "user_confirmation"



def test_freshness_is_fresh_stale_or_unknown_without_inference():
    now = datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc)

    fresh = assess_freshness(
        {"checked_at": (now - timedelta(seconds=30)).isoformat()},
        max_age_seconds=60,
        now=now,
    )
    stale = assess_freshness(
        {"updated_at": (now - timedelta(seconds=120)).isoformat()},
        max_age_seconds=60,
        now=now,
    )
    unknown = assess_freshness({"value": "configured"}, max_age_seconds=60, now=now)

    assert fresh["status"] == "fresh"
    assert fresh["age_seconds"] == 30
    assert stale["status"] == "stale"
    assert stale["age_seconds"] == 120
    assert unknown["status"] == "unknown"
    assert unknown["source_observed_at"] is None


def test_snapshot_exposes_freshness_policy_for_all_27_parameters():
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

    assert len(snapshot["parameters"]) == 27
    assert all("freshness" in item for item in snapshot["parameters"].values())
    assert all(item["freshness"]["max_age_seconds"] > 0 for item in snapshot["parameters"].values())


def test_free_ai_mode_is_not_accepted_as_production_budget_mode():
    context = SimpleNamespace(
        project_id="test-project",
        metadata={"runtime_health": {"free_ai_mode": {"enabled": True, "checked_at": "2026-10-18T00:00:00+00:00"}}},
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

    assert snapshot["parameters"]["production_budget_mode"]["status"] == STATUS_UNKNOWN


def test_explicit_production_budget_mode_is_known_independently_of_free_ai_mode():
    context = SimpleNamespace(
        project_id="test-project",
        metadata={"runtime_health": {
            "production_budget_mode": {
                "status": "available",
                "mode": "minimal",
                "checked_at": "2026-10-18T00:00:00+00:00",
            },
            "free_ai_mode": {"enabled": True},
        }},
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

    assert snapshot["parameters"]["production_budget_mode"]["status"] == STATUS_KNOWN
    assert snapshot["parameters"]["production_budget_mode"]["value"]["mode"] == "minimal"



def test_last_successful_cycle_requires_terminal_run_and_persisted_result():
    context = SimpleNamespace(
        project_id="test-project",
        metadata={
            "memory_state": {
                "recent_runs": [
                    {"id": 7, "status": "completed", "completed_at": "2026-10-17T10:00:00+00:00"},
                    {"id": 8, "status": "completed", "completed_at": "2026-10-18T10:00:00+00:00"},
                ],
                "recent_results": [
                    {"id": 21, "run_id": 7, "result_type": "autonomous_cycle", "created_at": "2026-10-17T10:00:00+00:00"}
                ],
            }
        },
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

    assert snapshot["parameters"]["last_successful_cycle"]["status"] == STATUS_KNOWN
    assert snapshot["parameters"]["last_successful_cycle"]["value"]["id"] == 7


@pytest.mark.asyncio
async def test_typed_director_records_are_persisted_with_run_provenance():
    class FakeMemory:
        def __init__(self):
            self.rows = []

        async def save_result(self, *, project_id, result, run_id=None):
            self.rows.append({"project_id": project_id, "result": result, "run_id": run_id})
            return len(self.rows)

    memory = FakeMemory()
    ids = await persist_typed_director_records(
        memory,
        "test-project",
        44,
        {
            "data": {
                "hypotheses": [{"title": "Retention improves", "statement": "Shorter intros improve retention"}],
                "forecasts": {"metric": "views", "expected_value": 1200},
                "due_measurements": [{"measurement_id": "m1", "run_at": "2026-10-18T00:00:00+00:00"}],
                "changed_conclusions": [{"conclusion_id": "c1", "reason": "new evidence"}],
                "end_of_day_plan": {"tasks": [{"title": "compare forecast"}]},
            }
        },
    )

    assert len(ids) == 5
    assert {row["result"]["type"] for row in memory.rows} == {
        "hypothesis", "forecast", "due_measurement", "changed_conclusion", "end_of_day_plan"
    }
    assert all(row["run_id"] == 44 for row in memory.rows)
    assert all(row["result"]["project_id"] == "test-project" for row in memory.rows)
    assert all(row["result"]["source_run_id"] == 44 for row in memory.rows)
