from director.research import ResearchOperation, ResearchOperationStatus, ResearchPlan, ResearchStatus
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
