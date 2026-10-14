from datetime import datetime, timezone

from director.research import (
    ResearchOperation,
    ResearchOperationStatus,
    ResearchPlan,
    ResearchStatus,
)
from director.research_executor import YouTubeResearchExecutor


def test_known_video_freshness_is_evaluated_per_video_not_per_research_set():
    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    payload = {
        "videos": [
            {"video_id": "fresh"},
            {"video_id": "stale"},
            {"video_id": "never-snapshotted"},
        ],
        "snapshots": [
            {"video_id": "fresh", "captured_at": "2026-10-14T11:30:00+00:00"},
            {"video_id": "stale", "captured_at": "2026-10-12T11:30:00+00:00"},
        ],
    }

    stale, latest = YouTubeResearchExecutor._known_videos_needing_refresh(
        payload,
        max_age_seconds=24 * 60 * 60,
        now=now,
    )

    assert [item["video_id"] for item in stale] == ["stale", "never-snapshotted"]
    assert latest["fresh"] == "2026-10-14T11:30:00+00:00"
    assert latest["stale"] == "2026-10-12T11:30:00+00:00"
    assert latest["never-snapshotted"] is None


def test_latest_successful_snapshot_is_used_for_each_video():
    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    payload = {
        "videos": [{"video_id": "v1"}],
        "snapshots": [
            {"video_id": "v1", "captured_at": "2026-10-10T00:00:00Z"},
            {"video_id": "v1", "captured_at": "2026-10-14T11:00:00Z"},
        ],
    }

    stale, latest = YouTubeResearchExecutor._known_videos_needing_refresh(
        payload,
        max_age_seconds=24 * 60 * 60,
        now=now,
    )

    assert stale == []
    assert latest["v1"] == "2026-10-14T11:00:00Z"


def test_refresh_operation_finalizes_from_its_own_result():
    plan = ResearchPlan(
        research_id="refresh-test",
        objective="refresh known videos",
        status=ResearchStatus.RUNNING,
        priorities=[],
        languages=["en"],
        directions=[],
        queries=[],
        gaps=[],
        reason="test",
        operations=[
            ResearchOperation(
                operation_id="refresh-1",
                operation="refresh_existing_video_stats",
                requirement_key="video_snapshots",
                inputs={},
                dependencies=[],
                expected_result="fresh snapshots",
                completion_criterion="persisted snapshots for stale known IDs",
            )
        ],
    )

    results = YouTubeResearchExecutor._finalize_operations(
        plan,
        {
            "refresh_existing_video_stats_status": "partial",
            "refresh_existing_video_stats_candidates": 3,
            "refresh_existing_video_stats_refreshed": 2,
            "refresh_existing_video_stats_api_batches": 1,
            "refresh_existing_video_stats_unavailable": ["gone"],
            "refresh_existing_video_stats_errors": [],
            "refresh_existing_video_stats_persisted": True,
        },
    )

    assert results[0]["status"] == ResearchOperationStatus.PARTIAL.value
    assert results[0]["result"]["refreshed"] == 2
    assert results[0]["result"]["unavailable_video_ids"] == ["gone"]
