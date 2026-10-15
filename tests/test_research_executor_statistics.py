from director.research import ResearchOperation, ResearchOperationStatus, ResearchPlan, ResearchStatus, mark_completed
from director.research_executor import YouTubeResearchExecutor


def _plan():
    operation = ResearchOperation(
        operation_id="channel-snapshots-1",
        operation="collect_channel_snapshots",
        requirement_key="channel_snapshots",
        inputs={},
        dependencies=[],
        expected_result="channel snapshots",
        completion_criterion="channel stats persisted",
    )
    return ResearchPlan(
        research_id="research-1",
        objective="test",
        status=ResearchStatus.RUNNING,
        priorities=[],
        languages=["en"],
        directions=[],
        queries=[],
        gaps=[],
        reason="test",
        operations=[operation],
    )


def test_channel_snapshot_operation_succeeds_only_when_snapshots_are_persisted():
    plan = _plan()

    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "persisted": True,
            "channel_snapshots_collected": 2,
            "channel_stats_calls": 2,
            "channel_stats_errors": [],
        },
    )

    assert results[0]["status"] == ResearchOperationStatus.SUCCEEDED.value
    assert results[0]["result"]["channel_snapshots_collected"] == 2
    assert results[0]["result"]["persisted"] is True


def test_channel_snapshot_operation_is_blocked_when_no_snapshot_was_collected():
    plan = _plan()

    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "persisted": True,
            "channel_snapshots_collected": 0,
            "channel_stats_calls": 0,
            "channel_stats_errors": ["MCP tool not available: get_channel_stats"],
        },
    )

    assert results[0]["status"] == ResearchOperationStatus.BLOCKED.value
    assert "get_channel_stats" in results[0]["error"]



def test_empty_search_is_not_successful_collection_and_does_not_satisfy_snapshots():
    search = ResearchOperation(
        operation_id="search-1",
        operation="search_videos",
        requirement_key="videos",
        inputs={"query": "topic", "language": "en"},
        dependencies=[],
        expected_result="videos",
        completion_criterion="videos received and saved",
    )
    snapshots = ResearchOperation(
        operation_id="snapshots-1",
        operation="collect_video_snapshots",
        requirement_key="video_snapshots",
        inputs={},
        dependencies=["search-1"],
        expected_result="video snapshots",
        completion_criterion="snapshots received and saved",
    )
    plan = ResearchPlan(
        research_id="research-empty",
        objective="empty search test",
        status=ResearchStatus.RUNNING,
        priorities=[],
        languages=["en"],
        directions=[],
        queries=[],
        gaps=[],
        reason="test",
        operations=[search, snapshots],
    )

    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "persisted": True,
            "queries_collected": 1,
            "queries_failed": 0,
            "queries_empty": 1,
            "videos_collected": 0,
            "snapshots_collected": 0,
            "expected_volume_reached": False,
            "query_results": [{
                "query": "topic",
                "language": "en",
                "status": "empty",
                "request_status": "succeeded",
                "results_status": "empty",
                "persistence_status": "saved",
                "result_count": 0,
                "received_video_count": 0,
                "saved_video_count": 0,
                "expected_result_count": 25,
                "expected_volume_reached": False,
                "error": None,
            }],
        },
    )

    assert results[0]["status"] == ResearchOperationStatus.EMPTY.value
    assert results[0]["result"]["queries_empty"] == 1
    assert results[1]["status"] == ResearchOperationStatus.BLOCKED.value
    assert results[1]["status"] != ResearchOperationStatus.SUCCEEDED.value


def test_mark_completed_refuses_plan_with_missing_mandatory_results():
    plan = _plan()
    plan.operations[0].status = ResearchOperationStatus.EMPTY

    mark_completed(plan)

    assert plan.status == ResearchStatus.PARTIAL
    assert plan.metadata["completion_blocked_by_operations"] == ["empty"]
