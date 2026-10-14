"""Regression tests for bounded process-local state."""

import unittest

from data.relations import DataRelation, DataRelations
from memory.inmemory import InMemoryMemoryBackend
from scheduler.wakeup import WakeupManager, WakeupReason


class InMemoryBoundsTests(unittest.TestCase):
    def test_memory_backend_evicts_oldest_rows_at_limit(self):
        memory = InMemoryMemoryBackend(max_rows_per_table=2)
        memory.save_event(event_type="one")
        memory.save_event(event_type="two")
        memory.save_event(event_type="three")

        rows = memory.get_recent_events(limit=10)
        self.assertEqual([row["event_type"] for row in rows], ["three", "two"])
        self.assertEqual(len(memory._events), 2)

    def test_relations_registry_is_bounded_and_keeps_newest(self):
        relations = DataRelations(max_relations=2)
        created = []
        for index in range(3):
            relation = DataRelation(
                source_type="research",
                source_id=index,
                relation="contains_video",
                target_type="video",
                target_id=index,
            )
            relations.add_relation(relation)
            created.append(relation)

        self.assertEqual(relations.relation_count(), 2)
        self.assertFalse(relations.has_relation(
            source_type="research", source_id=0, relation="contains_video",
            target_type="video", target_id=0,
        ))
        self.assertTrue(relations.has_relation(
            source_type="research", source_id=2, relation="contains_video",
            target_type="video", target_id=2,
        ))

    def test_wakeup_queue_is_bounded_and_counts_dropped_signals(self):
        manager = WakeupManager(max_queue_size=2)
        first = manager.create(project_id="p", reason=WakeupReason.MANUAL)
        manager.create(project_id="p", reason=WakeupReason.MANUAL)
        manager.create(project_id="p", reason=WakeupReason.MANUAL)

        self.assertEqual(len(manager._queue), 2)
        self.assertEqual(manager.dropped_signals, 1)
        self.assertNotIn(first.wakeup_id, [signal.wakeup_id for signal in manager._queue])
        self.assertEqual(manager.snapshot()["dropped_signals"], 1)


if __name__ == "__main__":
    unittest.main()
