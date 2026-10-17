from director.research import ResearchOperation, ResearchOperationStatus, ResearchPlan, ResearchStatus
from director.research_executor import YouTubeResearchExecutor


def _plan():
    return ResearchPlan(
        research_id="niche-test",
        objective="validate niche lifecycle",
        status=ResearchStatus.RUNNING,
        priorities=[],
        languages=["en"],
        directions=[],
        queries=[],
        gaps=[],
        reason="unit test",
        operations=[
            ResearchOperation(
                operation_id="niches",
                operation="collect_niche_evidence",
                requirement_key="niches",
                inputs={},
                dependencies=[],
                expected_result="candidate niche evidence",
                completion_criterion="candidate niche evidence persisted",
            ),
            ResearchOperation(
                operation_id="niche-snapshots",
                operation="build_niche_snapshots",
                requirement_key="niche_snapshots",
                inputs={},
                dependencies=["niches"],
                expected_result="niche snapshots",
                completion_criterion="niche snapshots persisted",
            ),
        ],
    )


def test_niche_operations_succeed_only_when_evidence_and_snapshots_are_persisted():
    plan = _plan()
    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "persisted": True,
            "niches_collected": 2,
            "niche_evidence_video_count": 24,
            "niche_snapshots_collected": 2,
            "niche_data_persisted": True,
        },
    )
    by_name = {item["operation"]: item for item in results}
    assert by_name["collect_niche_evidence"]["status"] == ResearchOperationStatus.SUCCEEDED.value
    assert by_name["collect_niche_evidence"]["result"]["evidence_video_count"] == 24
    assert by_name["build_niche_snapshots"]["status"] == ResearchOperationStatus.SUCCEEDED.value


def test_niche_snapshot_operation_is_blocked_when_evidence_is_not_persisted():
    plan = _plan()
    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "persisted": True,
            "niches_collected": 1,
            "niche_evidence_video_count": 8,
            "niche_snapshots_collected": 1,
            "niche_data_persisted": False,
        },
    )
    by_name = {item["operation"]: item for item in results}
    assert by_name["collect_niche_evidence"]["status"] == ResearchOperationStatus.PARTIAL.value
    assert by_name["build_niche_snapshots"]["status"] == ResearchOperationStatus.BLOCKED.value
    assert "blocked_by_dependencies" in by_name["build_niche_snapshots"]["error"]


def test_niche_operations_do_not_claim_success_without_evidence():
    plan = _plan()
    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {"persisted": True, "niches_collected": 0, "niche_snapshots_collected": 0},
    )
    by_name = {item["operation"]: item for item in results}
    assert by_name["collect_niche_evidence"]["status"] == ResearchOperationStatus.BLOCKED.value
    assert by_name["build_niche_snapshots"]["status"] == ResearchOperationStatus.BLOCKED.value
