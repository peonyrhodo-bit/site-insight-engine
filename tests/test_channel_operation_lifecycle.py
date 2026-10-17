from director.research import ResearchOperation, ResearchOperationStatus, ResearchPlan, ResearchStatus
from director.research_executor import YouTubeResearchExecutor


def test_collected_channel_identities_unlock_channel_snapshot_operation():
    collect_channels = ResearchOperation(
        operation_id="collect-channels",
        operation="collect_channels",
        requirement_key="channels",
        inputs={},
        dependencies=[],
        expected_result="channel identities",
        completion_criterion="channel identities persisted",
    )
    collect_snapshots = ResearchOperation(
        operation_id="collect-channel-snapshots",
        operation="collect_channel_snapshots",
        requirement_key="channel_snapshots",
        inputs={},
        dependencies=["collect-channels"],
        expected_result="channel snapshots",
        completion_criterion="channel metrics persisted",
    )
    plan = ResearchPlan(
        research_id="research-test",
        objective="test channel lifecycle",
        status=ResearchStatus.RUNNING,
        priorities=[],
        languages=["en"],
        directions=[],
        queries=[],
        gaps=[],
        reason="unit test",
        operations=[collect_channels, collect_snapshots],
    )

    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "persisted": True,
            "videos_collected": 10,
            "channels_collected": 3,
            "channel_snapshots_collected": 3,
            "channel_stats_calls": 3,
            "channel_stats_errors": [],
        },
    )

    by_name = {item["operation"]: item for item in results}
    assert by_name["collect_channels"]["status"] == ResearchOperationStatus.SUCCEEDED.value
    assert by_name["collect_channels"]["result"]["channels_collected"] == 3
    assert by_name["collect_channel_snapshots"]["status"] == ResearchOperationStatus.SUCCEEDED.value


def test_channel_collection_is_not_successful_without_channel_ids():
    operation = ResearchOperation(
        operation_id="collect-channels",
        operation="collect_channels",
        requirement_key="channels",
        inputs={},
        dependencies=[],
        expected_result="channel identities",
        completion_criterion="channel identities persisted",
    )
    plan = ResearchPlan(
        research_id="research-test",
        objective="test empty channel lifecycle",
        status=ResearchStatus.RUNNING,
        priorities=[],
        languages=["en"],
        directions=[],
        queries=[],
        gaps=[],
        reason="unit test",
        operations=[operation],
    )

    result = YouTubeResearchExecutor._finalize_operations(
        plan,
        {"persisted": True, "videos_collected": 10, "channels_collected": 0},
    )[0]

    assert result["status"] == ResearchOperationStatus.BLOCKED.value
    assert result["error"] == "no_channel_identities_collected_from_video_results"
