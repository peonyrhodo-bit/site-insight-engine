"""Regression tests for bounded process-local state."""

import unittest

from data.relations import DataRelation, DataRelations
from memory.inmemory import InMemoryMemoryBackend
from scheduler.wakeup import WakeupManager, WakeupReason


class InMemoryBoundsTests(unittest.TestCase):

    def test_supabase_loader_streams_pages_and_bounds_snapshots_per_video(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from memory.supabase import SupabaseMemoryBackend

        rows = [
            {"id": 5, "video_id": "v1", "created_at": "2026-01-05", "data_json": {"project_id": "p", "statistics": {"views": 5}}},
            {"id": 4, "video_id": "v1", "created_at": "2026-01-04", "data_json": {"project_id": "p", "statistics": {"views": 4}}},
            {"id": 3, "video_id": "v1", "created_at": "2026-01-03", "data_json": {"project_id": "p", "statistics": {"views": 3}}},
            {"id": 2, "video_id": "v1", "created_at": "2026-01-02", "data_json": {"project_id": "p", "statistics": {"views": 2}}},
            {"id": 1, "video_id": "v1", "created_at": "2026-01-01", "data_json": {"project_id": "p", "statistics": {"views": 1}}},
        ]

        class Query:
            def __init__(self, table):
                self.table_name = table
                self.desc = False
                self.start = 0
                self.end = 499
            def select(self, _): return self
            def order(self, _key, desc=False):
                self.desc = desc
                return self
            def range(self, start, end):
                self.start, self.end = start, end
                return self
            def execute(self):
                table_rows = rows if self.table_name == "video_snapshots" else [
                    {"video_id": "v1", "first_seen": None, "last_seen": None,
                     "data_json": {"project_id": "p", "snippet": {"title": "Video"}}}
                ]
                ordered = sorted(table_rows, key=lambda row: row.get("id", 0), reverse=self.desc)
                return SimpleNamespace(data=ordered[self.start:self.end + 1])

        client = MagicMock()
        client.table.side_effect = lambda name: Query(name)
        backend = SupabaseMemoryBackend(client=client)

        with patch.dict("os.environ", {"DIRECTOR_SNAPSHOTS_PER_VIDEO": "2"}):
            payload = backend.load_youtube_data(project_id="p")

        self.assertEqual(len(payload["videos"]), 1)
        self.assertEqual(len(payload["snapshots"]), 2)
        self.assertEqual(
            [item["metrics"]["views"] for item in payload["snapshots"]],
            [5, 4],
        )

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
