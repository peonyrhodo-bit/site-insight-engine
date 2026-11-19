"""Offline regression tests for protected-memory read and research safety."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from memory.read_status import MemoryTableReadError
from memory.supabase import SupabaseMemoryBackend
from director.director import Director


def _backend():
    backend = object.__new__(SupabaseMemoryBackend)
    backend.client = object()
    return backend


def test_protected_read_failures_are_not_empty_successes():
    for method in ("get_recent_recommendations", "get_recent_constraints"):
        backend = _backend()
        backend._recent_for_project = Mock(side_effect=MemoryTableReadError(method, cause=RuntimeError("offline failure")))
        try:
            getattr(backend, method)(project_id="p")
        except MemoryTableReadError:
            pass
        else:
            raise AssertionError(f"{method} swallowed read failure")


def test_context_reports_protected_read_failure_and_real_empty_table():
    backend = _backend()
    for name in ("runs", "decisions", "events", "chat_messages", "actions", "results", "recommendations", "constraints"):
        setattr(backend, "get_recent_" + name, Mock(return_value=[]))
    backend.get_recent_constraints.side_effect = MemoryTableReadError("constraints", cause=RuntimeError("offline failure"))
    context = backend.get_context(project_id="p")
    assert context["_memory_read"]["tables"]["constraints"]["status"] == "error"
    assert context["_memory_read"]["tables"]["recommendations"]["status"] == "complete"
    assert context["_memory_read"]["status"] == "partial"


def test_incomplete_protected_memory_blocks_real_research_executor():
    executor = Mock(return_value={"status": "completed", "queries_collected": 1})
    director = Director(project_id="p", memory_service=object(), research_service=SimpleNamespace(execute=executor))
    plan = SimpleNamespace(research_id="offline", objective="offline", queries=[], metadata={"operations": []}, to_dict=lambda: {})
    director.plan_research = Mock(return_value=plan)
    director.inspect = AsyncMock(return_value=SimpleNamespace(metadata={}))
    director.context.metadata["memory_read"] = {
        "status": "partial",
        "tables": {"constraints": {"status": "error"}, "recommendations": {"status": "complete"}, "decisions": {"status": "complete"}},
    }
    state = SimpleNamespace(metadata={}, cycle_count=1, current_research_id=None)
    result = asyncio.run(director._autonomy_research(state, None))
    executor.assert_not_called()
    assert result["research_execution"]["status"] == "blocked"
    assert result["research_execution"]["reason"] == "memory_incomplete_protected_state"


def test_complete_protected_memory_keeps_executor_available():
    executor = Mock(return_value={"status": "blocked", "reason": "offline_stub"})
    director = Director(project_id="p", memory_service=object(), research_service=SimpleNamespace(execute=executor))
    plan = SimpleNamespace(research_id="offline", objective="offline", queries=[], metadata={"operations": []}, to_dict=lambda: {})
    director.plan_research = Mock(return_value=plan)
    director.inspect = AsyncMock(return_value=SimpleNamespace(metadata={}))
    director.context.metadata["memory_read"] = {
        "status": "complete",
        "tables": {key: {"status": "complete"} for key in ("constraints", "recommendations", "decisions")},
    }
    state = SimpleNamespace(metadata={}, cycle_count=1, current_research_id=None)
    result = asyncio.run(director._autonomy_research(state, None))
    executor.assert_called_once_with(plan)
    assert result["research_execution"]["reason"] == "offline_stub"


def test_partial_protected_rows_preserved_in_context():
    backend = _backend()
    for name in ("runs", "decisions", "events", "chat_messages", "actions", "results", "recommendations", "constraints"):
        setattr(backend, "get_recent_" + name, Mock(return_value=[]))
    partial = [{"id": 1, "status": "active"}]
    backend.get_recent_constraints.side_effect = MemoryTableReadError(
        "constraints", partial_rows=partial, cause=RuntimeError("next page failed")
    )
    context = backend.get_context(project_id="p")
    assert context["constraints"] == partial
    assert context["_memory_read"]["tables"]["constraints"] == {"status": "partial", "rows": 1}
    assert context["_memory_read"]["status"] == "partial"


def test_missing_protected_read_metadata_blocks_executor():
    executor = Mock(return_value={"status": "completed"})
    director = Director(project_id="p", memory_service=object(), research_service=SimpleNamespace(execute=executor))
    plan = SimpleNamespace(research_id="offline", objective="offline", queries=[], metadata={"operations": []}, to_dict=lambda: {})
    director.plan_research = Mock(return_value=plan)
    director.inspect = AsyncMock(return_value=SimpleNamespace(metadata={}))
    director.context.metadata.pop("memory_read", None)
    state = SimpleNamespace(metadata={}, cycle_count=1, current_research_id=None)
    result = asyncio.run(director._autonomy_research(state, None))
    executor.assert_not_called()
    assert result["research_execution"]["reason"] == "memory_incomplete_protected_state"


def test_complete_atomic_memory_without_per_table_status_allows_research():
    # ServerMemory.get_context normalizes a complete atomic backend to tables={}.
    executor = Mock(return_value={"status": "blocked", "reason": "offline_stub"})
    director = Director(project_id="p", memory_service=object(), research_service=SimpleNamespace(execute=executor))
    plan = SimpleNamespace(research_id="offline", objective="offline", queries=[], metadata={"operations": []}, to_dict=lambda: {})
    director.plan_research = Mock(return_value=plan)
    director.inspect = AsyncMock(return_value=SimpleNamespace(metadata={}))
    director.context.metadata["memory_read"] = {"status": "complete", "tables": {}, "errors": {}}
    state = SimpleNamespace(metadata={}, cycle_count=1, current_research_id=None)
    result = asyncio.run(director._autonomy_research(state, None))
    executor.assert_called_once_with(plan)
    assert result["research_execution"]["reason"] == "offline_stub"


def test_missing_protected_table_in_partial_diagnostics_blocks_research():
    executor = Mock(return_value={"status": "completed"})
    director = Director(project_id="p", memory_service=object(), research_service=SimpleNamespace(execute=executor))
    plan = SimpleNamespace(research_id="offline", objective="offline", queries=[], metadata={"operations": []}, to_dict=lambda: {})
    director.plan_research = Mock(return_value=plan)
    director.inspect = AsyncMock(return_value=SimpleNamespace(metadata={}))
    director.context.metadata["memory_read"] = {"status": "complete", "tables": {"decisions": {"status": "complete"}}, "errors": {}}
    state = SimpleNamespace(metadata={}, cycle_count=1, current_research_id=None)
    result = asyncio.run(director._autonomy_research(state, None))
    executor.assert_not_called()
    assert result["research_execution"]["reason"] == "memory_incomplete_protected_state"


def test_inspection_clears_stale_complete_read_after_nondict_response():
    # A previous complete read must not authorize a later failed inspection.
    memory = SimpleNamespace(get_context=Mock(return_value=None))
    director = Director(project_id="p", memory_service=memory)
    director.context.metadata["memory_read"] = {
        "status": "complete",
        "tables": {name: {"status": "complete"} for name in ("decisions", "recommendations", "constraints")},
    }
    asyncio.run(director.inspect())
    assert director.context.metadata.get("memory_read") is None
    assert director.context.metadata["runtime_health"]["memory"]["status"] == "degraded"
