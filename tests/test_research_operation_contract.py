from types import SimpleNamespace

from director.research import (
    ResearchOperation,
    ResearchOperationStatus,
    build_query,
    build_research_plan,
    plan_from_requirements,
)
from director.research_executor import YouTubeResearchExecutor


def test_plan_from_requirements_creates_explicit_operations_and_dependencies():
    plan = plan_from_requirements(
        objective="Find useful YouTube evidence",
        requirements=[
            {
                "key": "videos",
                "description": "Collect relevant videos",
                "priority": "critical",
                "count": 0,
                "needed_now": True,
            },
            {
                "key": "video_snapshots",
                "description": "Collect video metric history",
                "priority": "high",
                "count": 0,
                "needed_now": True,
            },
        ],
        preferred_languages=["en"],
    )

    assert plan.operations
    assert all(operation.operation_id for operation in plan.operations)
    assert all(operation.expected_result for operation in plan.operations)
    assert all(operation.completion_criterion for operation in plan.operations)
    search = next(op for op in plan.operations if op.operation == "search_videos")
    snapshots = next(op for op in plan.operations if op.operation == "collect_video_snapshots")
    assert search.operation_id in snapshots.dependencies
    assert search.quota_requirements["bucket"] == "search"


def test_sync_plan_operations_tracks_queries_added_after_planning():
    plan = build_research_plan(
        objective="discover",
        queries=[
            build_query(
                query="new YouTube topics",
                language="en",
                purpose="discovery",
            )
        ],
    )

    YouTubeResearchExecutor.sync_plan_operations(plan)

    search_operations = [op for op in plan.operations if op.operation == "search_videos"]
    assert len(search_operations) == 1
    assert search_operations[0].inputs["query"] == "new YouTube topics"
    assert {
        "register_queries",
        "register_research_set",
        "collect_video_snapshots",
        "link_research_data",
    }.issubset({op.operation for op in plan.operations})
    assert plan.metadata["operation_contract_version"] == 1


def test_empty_search_is_partial_not_successful_collection():
    operation = ResearchOperation(
        operation_id="search-1",
        operation="search_videos",
        requirement_key="videos",
        inputs={"query": "example", "language": "en"},
        dependencies=[],
        expected_result="videos",
        completion_criterion="valid response and recorded outcome",
    )
    plan = SimpleNamespace(operations=[operation])

    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "queries_collected": 1,
            "queries_failed": 0,
            "videos_collected": 0,
            "snapshots_collected": 0,
            "persisted": True,
            "relations_created": 0,
            "errors": [],
        },
    )

    assert results[0]["status"] == ResearchOperationStatus.PARTIAL.value
    assert results[0]["error"] == "search_completed_without_relevant_video_results"


def test_operation_is_blocked_when_dependency_did_not_succeed():
    search = ResearchOperation(
        operation_id="search-1",
        operation="search_videos",
        requirement_key="videos",
        inputs={"query": "example", "language": "en"},
        dependencies=[],
        expected_result="videos",
        completion_criterion="at least one relevant video",
    )
    snapshots = ResearchOperation(
        operation_id="snapshot-1",
        operation="collect_video_snapshots",
        requirement_key="video_snapshots",
        inputs={},
        dependencies=["search-1"],
        expected_result="snapshots",
        completion_criterion="usable metric history",
    )
    plan = SimpleNamespace(operations=[search, snapshots])

    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "queries_collected": 1,
            "queries_failed": 0,
            "videos_collected": 0,
            "snapshots_collected": 0,
            "persisted": True,
            "relations_created": 0,
            "errors": [],
        },
    )

    assert results[0]["status"] == ResearchOperationStatus.PARTIAL.value
    assert results[1]["status"] == ResearchOperationStatus.BLOCKED.value
    assert "search-1" in results[1]["error"]
