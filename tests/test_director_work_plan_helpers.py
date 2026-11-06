from director.director import (
    _apply_work_plan_task_to_research_plan,
    _work_plan_search_gaps,
    _select_work_plan_task,
)
from director.research import ResearchOperation, build_research_plan


def _plan_with_refresh():
    plan = build_research_plan(objective="test", queries=[])
    plan.operations.append(
        ResearchOperation(
            operation_id="refresh",
            operation="refresh_existing_video_stats",
            requirement_key="video_snapshots",
            inputs={},
            dependencies=[],
            expected_result="fresh metrics",
            completion_criterion="metrics refreshed",
        )
    )
    return plan


def test_unrelated_work_plan_task_removes_bulk_video_refresh():
    plan = _plan_with_refresh()

    result = _apply_work_plan_task_to_research_plan(
        plan,
        {"id": "validate_hypotheses", "task": "validate", "reason": "missing hypothesis"},
    )

    assert result.metadata["work_plan_task"]["id"] == "validate_hypotheses"
    assert "refresh_existing_video_stats" not in {
        operation.operation for operation in result.operations
    }


def test_refresh_evidence_task_keeps_explicit_video_refresh():
    plan = _plan_with_refresh()

    result = _apply_work_plan_task_to_research_plan(
        plan,
        {"id": "refresh_evidence", "task": "refresh", "reason": "stale metrics"},
    )

    assert "refresh_existing_video_stats" in {
        operation.operation for operation in result.operations
    }


def test_selected_task_is_read_from_assessment_work_plan():
    work_plan = {
        "execution_order": ["validate_hypotheses", "persist_and_reinspect"],
        "tasks": [
            {"id": "discover_broadly", "task": "discover"},
            {"id": "validate_hypotheses", "task": "validate", "reason": "not formulated"},
        ],
    }

    assert _select_work_plan_task(work_plan) == {
        "id": "validate_hypotheses",
        "task": "validate",
        "reason": "not formulated",
    }


def test_work_plan_task_text_and_reason_are_not_sent_as_search_queries():
    assert _work_plan_search_gaps(
        {"id": "discover_broadly", "task": "find topics", "reason": "missing evidence"}
    ) == []


def test_only_explicit_search_queries_are_used():
    assert _work_plan_search_gaps(
        {
            "id": "discover_broadly",
            "task": "find topics",
            "reason": "missing evidence",
            "search_queries": ["YouTube Shorts education trends", "gaming tutorials"],
        }
    ) == ["YouTube Shorts education trends", "gaming tutorials"]
