import unittest

from director.autonomy import (
    AutonomyConfig,
    CycleStatus,
    DirectorAutonomy,
    DirectorPhase,
    DirectorState,
)


class DirectorAutonomyLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_checks_for_another_task_after_recommendation(self):
        decisions = []
        recommendations = []

        async def assess(state, payload):
            return {"evidence_sufficient": True}

        async def analyze(state, payload):
            return {"opportunities": []}

        async def decide(state, payload):
            decisions.append(len(decisions) + 1)
            if len(decisions) == 1:
                return {
                    "decision_id": "decision-1",
                    "decision_type": "test",
                    "metadata": {"task_key": "opportunity:alpha"},
                }
            return {
                "decision_id": "decision-2",
                "decision_type": "wait",
                "metadata": {},
            }

        async def recommend(state, decision):
            recommendations.append(decision)
            return {"recommendation_id": "recommendation-1"}

        autonomy = DirectorAutonomy(
            config=AutonomyConfig(max_steps_per_cycle=16),
            assess=assess,
            analyze=analyze,
            decide=decide,
            recommend=recommend,
        )

        cycle = await autonomy.run(initial_state=DirectorState())

        self.assertEqual(len(recommendations), 1)
        self.assertEqual(len(decisions), 2)
        self.assertIn(
            "opportunity:alpha",
            cycle.state.metadata["completed_task_keys"],
        )
        self.assertEqual(cycle.status, CycleStatus.SLEEPING)
        self.assertEqual(cycle.state.phase, DirectorPhase.SLEEP)

    async def test_duplicate_research_does_not_spin_forever(self):
        research_calls = []
        analyze_calls = []

        async def assess(state, payload):
            return {"evidence_sufficient": False, "missing_data": ["same gap"]}

        async def research(state, payload):
            research_calls.append(1)
            if len(research_calls) == 1:
                return {"status": "completed", "task_key": "research:same"}
            return {
                "status": "skipped",
                "duplicate_task": True,
                "task_key": "research:same",
            }

        async def analyze(state, payload):
            analyze_calls.append(1)
            return {"opportunities": []}

        async def decide(state, payload):
            return {
                "decision_id": "decision-wait",
                "decision_type": "wait",
                "metadata": {},
            }

        autonomy = DirectorAutonomy(
            config=AutonomyConfig(
                max_steps_per_cycle=16,
                max_research_steps=3,
            ),
            assess=assess,
            research=research,
            analyze=analyze,
            decide=decide,
        )

        cycle = await autonomy.run(initial_state=DirectorState())

        self.assertEqual(len(research_calls), 2)
        self.assertEqual(len(analyze_calls), 1)
        self.assertTrue(cycle.state.metadata["research_task_exhausted"])
        self.assertEqual(cycle.status, CycleStatus.SLEEPING)

    async def test_task_ledger_is_reset_for_each_wake(self):
        autonomy = DirectorAutonomy(
            config=AutonomyConfig(max_steps_per_cycle=4),
        )
        state = DirectorState(metadata={
            "completed_task_keys": ["opportunity:old"],
            "research_task_exhausted": True,
        })

        cycle = await autonomy.run(initial_state=state)

        self.assertEqual(cycle.state.metadata["completed_task_keys"], [])
        self.assertNotIn("research_task_exhausted", cycle.state.metadata)


if __name__ == "__main__":
    unittest.main()
