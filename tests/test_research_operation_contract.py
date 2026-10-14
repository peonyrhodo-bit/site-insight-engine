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


def test_executor_selects_queries_from_pending_operations_only():
    plan = build_research_plan(
        objective="discover",
        queries=[
            build_query(query="topic one", language="en", purpose="first"),
            build_query(query="topic two", language="en", purpose="second"),
        ],
    )
    YouTubeResearchExecutor.sync_plan_operations(plan)
    first = next(op for op in plan.operations if op.operation == "search_videos" and op.inputs["query"] == "topic one")
    first.status = ResearchOperationStatus.SUCCEEDED
    first.result = {
        "queries": [
            {"query": "topic one", "language": "en", "status": "completed", "result_count": 3}
        ]
    }

    selected = YouTubeResearchExecutor._queries_for_operations(plan)

    assert [query.query for query in selected] == ["topic two"]


def test_query_is_not_dispatched_when_dependency_is_not_succeeded():
    plan = build_research_plan(
        objective="dependent search",
        queries=[build_query(query="topic", language="en", purpose="test")],
        operations=[
            ResearchOperation(
                operation_id="prerequisite",
                operation="register_queries",
                requirement_key="queries",
                inputs={},
                dependencies=[],
                expected_result="query record",
                completion_criterion="query record exists",
                status=ResearchOperationStatus.PLANNED,
            ),
            ResearchOperation(
                operation_id="search",
                operation="search_videos",
                requirement_key="videos",
                inputs={"query": "topic", "language": "en"},
                dependencies=["prerequisite"],
                expected_result="video evidence",
                completion_criterion="at least one relevant video",
            ),
        ],
    )

    assert YouTubeResearchExecutor._queries_for_operations(plan) == []


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



def test_plan_round_trip_preserves_operation_ids_statuses_and_retry_state():
    plan = build_research_plan(
        objective="recover after worker restart",
        queries=[
            build_query(query="completed topic", language="en", purpose="first"),
            build_query(query="retry topic", language="ru", purpose="second"),
        ],
    )
    YouTubeResearchExecutor.sync_plan_operations(plan)
    operations = [op for op in plan.operations if op.operation == "search_videos"]
    operations[0].status = ResearchOperationStatus.SUCCEEDED
    operations[0].result = {
        "queries": [
            {"query": "completed topic", "language": "en", "status": "completed", "result_count": 2}
        ],
        "videos_collected": 2,
    }
    operations[0].started_at = "2026-10-14T10:00:00+00:00"
    operations[0].completed_at = "2026-10-14T10:00:01+00:00"
    operations[1].status = ResearchOperationStatus.PARTIAL
    operations[1].result = {
        "queries": [
            {"query": "retry topic", "language": "ru", "status": "failed", "result_count": 0}
        ]
    }
    operations[1].error = "temporary transport failure"

    restored = type(plan).from_dict(plan.to_dict())

    restored_searches = [op for op in restored.operations if op.operation == "search_videos"]
    assert [op.operation_id for op in restored_searches] == [op.operation_id for op in operations]
    assert restored_searches[0].status == ResearchOperationStatus.SUCCEEDED
    assert restored_searches[0].result == operations[0].result
    assert restored_searches[0].started_at == operations[0].started_at
    assert restored_searches[1].status == ResearchOperationStatus.PARTIAL
    assert restored_searches[1].error == "temporary transport failure"
    assert [q.query for q in YouTubeResearchExecutor._queries_for_operations(restored)] == ["retry topic"]


def test_channel_and_niche_requirements_are_explicit_not_fake_video_queries():
    plan = plan_from_requirements(
        objective="inspect channels and niches",
        requirements=[
            {"key": "channels", "description": "Collect channels", "priority": "high", "needed_now": True},
            {"key": "channel_snapshots", "description": "Collect channel history", "priority": "medium", "needed_now": True},
            {"key": "niches", "description": "Collect niche evidence", "priority": "medium", "needed_now": True},
            {"key": "niche_snapshots", "description": "Build niche history", "priority": "low", "needed_now": True},
        ],
        preferred_languages=["en"],
    )
    assert not plan.queries
    assert {op.operation for op in plan.operations} == {
        "collect_channels", "collect_channel_snapshots", "collect_niche_evidence", "build_niche_snapshots"
    }


def test_unimplemented_channel_and_niche_operations_are_never_reported_successful():
    operations = [
        ResearchOperation(
            operation_id="channels", operation="collect_channels", requirement_key="channels",
            inputs={}, dependencies=[], expected_result="channel records",
            completion_criterion="channel records are collected",
        ),
        ResearchOperation(
            operation_id="channel-snapshots", operation="collect_channel_snapshots", requirement_key="channel_snapshots",
            inputs={}, dependencies=[], expected_result="channel history",
            completion_criterion="channel history is collected",
        ),
        ResearchOperation(
            operation_id="niches", operation="collect_niche_evidence", requirement_key="niches",
            inputs={}, dependencies=[], expected_result="niche evidence",
            completion_criterion="niche evidence is collected",
        ),
        ResearchOperation(
            operation_id="niche-snapshots", operation="build_niche_snapshots", requirement_key="niche_snapshots",
            inputs={}, dependencies=[], expected_result="niche history",
            completion_criterion="niche history is built",
        ),
    ]
    plan = SimpleNamespace(operations=operations)
    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "queries_collected": 0, "queries_failed": 0, "videos_collected": 0,
            "snapshots_collected": 0, "persisted": True, "relations_created": 0, "errors": [],
        },
    )
    by_name = {item["operation"]: item for item in results}
    assert by_name["collect_channels"]["status"] == "blocked"
    assert by_name["collect_channel_snapshots"]["status"] == "blocked"
    assert by_name["collect_niche_evidence"]["status"] == "blocked"
    assert by_name["build_niche_snapshots"]["status"] == "blocked"
    assert all(item["error"] for item in results)
