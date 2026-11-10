from director.director import Director, DirectorContext
from director.autonomy import DirectorState


def test_wake_assessment_marks_unverified_health_as_unknown():
    director = Director(project_id="test")
    director.context = DirectorContext(
        project_id="test",
        research_history=[{"research_id": "r1", "status": "running"}],
        recommendations=[
            {"recommendation_id": "rec1", "status": "awaiting_decision"},
            {"recommendation_id": "rec2", "status": "accepted"},
        ],
        metadata={"budget_mode": "unknown"},
        available_actions=["inspect"],
    )
    snapshot = {
        "inventory": {"videos": 3, "video_snapshots": 2, "search_queries": 1},
    }

    assessment = director._build_wake_assessment(
        state=DirectorState(project_id="test", cycle_count=1),
        inventory={"video_count": 3},
        project_state={
            "freshness": {"status": "unknown"},
            "quota": {"accounting": "persisted_director_mcp_calls", "remaining_units_today": 10},
        },
        capabilities={"connected_services": {"ai": True, "research": False}},
        wake_snapshot=snapshot,
    )

    assert assessment["status"] == "partial"
    blocks = assessment["blocks"]
    assert blocks["data_and_dependencies"]["live_dependency_health"] == "unknown"
    assert blocks["cycle_integrity"]["unfinished_research_count"] == 1
    assert blocks["recommendations_and_user_tasks"]["awaiting_user_decision"] == 1
    assert blocks["recommendations_and_user_tasks"]["accepted_or_rejected"] == 1
    assert blocks["recommendations_and_user_tasks"]["video_preparation_consent_required"] is True
    assert blocks["resources_and_plan"]["quota_source_authoritative"] is False


def test_wake_assessment_compares_inventory_when_prior_snapshot_exists():
    director = Director(project_id="test")
    director.context.metadata["previous_wake_snapshot"] = {
        "inventory": {"videos": 2, "video_snapshots": 1, "search_queries": 1},
    }
    snapshot = {
        "inventory": {"videos": 5, "video_snapshots": 4, "search_queries": 1},
    }

    assessment = director._build_wake_assessment(
        state=DirectorState(project_id="test", cycle_count=2),
        inventory={},
        project_state={"freshness": {"status": "fresh"}, "quota": {"accounting": "quota_manager"}},
        capabilities={"connected_services": {}},
        wake_snapshot=snapshot,
    )

    changes = assessment["blocks"]["data_changes"]["new_data_since_previous_wake"]
    assert changes == {"videos": 3, "video_snapshots": 3, "search_queries": 0}
    assert assessment["blocks"]["resources_and_plan"]["quota_source_authoritative"] is True
