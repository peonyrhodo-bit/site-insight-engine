import os
import unittest
from unittest.mock import patch

from memory.supabase import SupabaseMemoryBackend


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.operation = None
        self.payload = None

    def upsert(self, payload, **kwargs):
        self.operation = "upsert"
        self.payload = payload
        return self

    def insert(self, payload, **kwargs):
        self.operation = "insert"
        self.payload = payload
        return self

    def select(self, fields):
        self.fields = fields
        return self

    def execute(self):
        batch = list(self.payload)
        self.client.calls.append((self.table_name, self.operation, batch))
        if self.table_name == "videos":
            return FakeResponse([{"video_id": row["video_id"]} for row in batch])

        rows = []
        for row in batch:
            self.client.next_snapshot_id += 1
            rows.append({
                "id": self.client.next_snapshot_id,
                "video_id": row["video_id"],
                "data_json": row["data_json"],
            })
        return FakeResponse(rows)


class FakeSupabaseClient:
    def __init__(self):
        self.calls = []
        self.next_snapshot_id = 0

    def table(self, name):
        return FakeQuery(self, name)


class SupabaseBatchPersistenceTests(unittest.TestCase):
    def test_youtube_videos_and_snapshots_are_saved_in_bounded_batches(self):
        client = FakeSupabaseClient()
        backend = SupabaseMemoryBackend(client=client)
        videos = [
            {
                "video_id": f"video-{index}",
                "metadata": {"title": f"Video {index}"},
            }
            for index in range(205)
        ]
        snapshots = [
            {
                "snapshot_id": f"snapshot-{index}",
                "video_id": f"video-{index}",
                "research_id": "research-test",
                "query_ids": [f"query-{index % 4}"],
                "metrics": {"view_count": index},
                "metadata": {},
            }
            for index in range(205)
        ]

        with patch.dict(os.environ, {"SUPABASE_DATA_WRITE_BATCH_SIZE": "100"}):
            result = backend.save_youtube_data(
                project_id="default",
                videos=videos,
                snapshots=snapshots,
            )

        video_calls = [call for call in client.calls if call[0] == "videos"]
        snapshot_calls = [call for call in client.calls if call[0] == "video_snapshots"]
        self.assertEqual([len(call[2]) for call in video_calls], [100, 100, 5])
        self.assertEqual([len(call[2]) for call in snapshot_calls], [100, 100, 5])
        self.assertTrue(all(call[1] == "upsert" for call in video_calls))
        self.assertTrue(all(call[1] == "insert" for call in snapshot_calls))
        self.assertEqual(result["videos"], 205)
        self.assertEqual(result["snapshots"], 205)
        self.assertEqual(len(result["snapshot_ids"]), 205)
        self.assertEqual(result["snapshot_video_ids"][0], "video-0")
        self.assertEqual(result["snapshot_query_ids"][0], ["query-0"])
        self.assertEqual(result["snapshot_video_ids"][-1], "video-204")
        self.assertEqual(result["snapshot_query_ids"][-1], ["query-0"])

    def test_youtube_video_payloads_are_deduplicated_before_bulk_upsert(self):
        client = FakeSupabaseClient()
        backend = SupabaseMemoryBackend(client=client)

        result = backend.save_youtube_data(
            project_id="default",
            videos=[
                {"video_id": "same-video", "metadata": {"title": "old"}},
                {"video_id": "same-video", "metadata": {"title": "latest"}},
            ],
            snapshots=[],
        )

        video_calls = [call for call in client.calls if call[0] == "videos"]
        self.assertEqual(len(video_calls), 1)
        self.assertEqual(len(video_calls[0][2]), 1)
        self.assertEqual(video_calls[0][2][0]["data_json"]["title"], "latest")
        self.assertEqual(result["videos"], 1)
        self.assertEqual(result["snapshots"], 0)


if __name__ == "__main__":
    unittest.main()
