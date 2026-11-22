"""Regression: an autonomous wake must not reuse a previous recommendation.

No network, Supabase, or YouTube API is accessed.
"""
from unittest.mock import patch

import pytest

from director.director import Director, DirectorResult, DirectorStatus
from director.autonomy import DirectorCycle, DirectorPhase, CycleStatus


@pytest.mark.asyncio
async def test_second_wake_wait_does_not_reuse_previous_recommendation():
    director = Director(project_id="offline-regression")
    invocations = []

    class OfflineAutonomy:
        def __init__(self, **kwargs):
            pass

        async def run(self, *, project_id, objective, initial_state):
            invocations.append(1)
            if len(invocations) == 1:
                director.last_result = DirectorResult(
                    status=DirectorStatus.WAITING,
                    phase=DirectorPhase.RECOMMEND,
                    message="First wake only",
                    recommendation=object(),
                )
                initial_state.current_recommendation_id = "rec-first"
            else:
                # The next wake is unable to create a recommendation.
                assert director.last_result is None
                assert initial_state.current_recommendation_id is None
            return DirectorCycle(
                cycle_id=f"offline-{len(invocations)}",
                status=CycleStatus.WAITING,
                state=initial_state,
            )

    with patch("director.director.DirectorAutonomy", OfflineAutonomy):
        await director.run_autonomous_cycle()
        assert director.last_result is not None
        await director.run_autonomous_cycle()

    assert len(invocations) == 2
    assert director.last_result is None
    assert director.state.current_recommendation_id is None
