import unittest
from unittest.mock import patch

from analytics.streaming import StreamingYouTubeAnalytics
from memory.supabase import SupabaseMemoryBackend


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.orders = []
        self.start = 0
        self.end = None
        self.filters = []
        self.limit_count = None

    def select(self, _columns):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, value):
        self.limit_count = value
        return self

    def order(self, key, desc=False):
        self.orders.append((key, desc))
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        rows = [
            row for row in self.rows
            if all(str(row.get(key)) == str(value) for key, value in self.filters)
        ]
        for key, desc in reversed(self.orders):
            rows.sort(key=lambda row: (row.get(key) is None, row.get(key)), reverse=desc)
        if self.end is not None:
            rows = rows[self.start:self.end + 1]
        if self.limit_count is not None:
            rows = rows[:self.limit_count]
        return FakeResponse(rows)


class FakeClient:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeQuery(self.tables.get(name, []))


class StreamingAccumulatorTests(unittest.TestCase):
    def test_accumulates_complete_counts_and_numeric_statistics_with_bounded_memory(self):
        accumulator = StreamingYouTubeAnalytics(sample_limit=3)
        for index in range(1000):
            accumulator.add_video({
                "video_id": str(index),
                "title": f"video {index}",
                "channel_id": f"channel-{index % 7}",
                "metadata": {"topics": [f"topic-{index % 5}"]},
            })
            accumulator.add_snapshot({
                "created_at": f"2026-01-{(index % 28) + 1:02d}T00:00:00Z",
                "data_json": {"statistics": {"views": index + 1}},
            })

        result = accumulator.to_dict()
        self.assertEqual(result["video_count"], 1000)
        self.assertEqual(result["snapshot_count"], 1000)
        self.assertEqual(result["snapshot_metrics"]["views"]["count"], 1000)
        self.assertEqual(result["snapshot_metrics"]["views"]["sum"], 500500)
        self.assertEqual(len(result["top_videos"]), 3)
        self.assertLessEqual(len(result["top_channels"]), 100)
        self.assertLessEqual(len(result["top_topics"]), 100)


class SupabaseFullHistoryStreamingTests(unittest.TestCase):
    def test_youtube_loader_scans_all_pages_but_retains_bounded_working_sets(self):
        videos = []
        snapshots = []
        for index in range(260):
            video_id = f"video-{index:04d}"
            videos.append({
                "video_id": video_id,
                "project_id": "project-a",
                "first_seen": "2026-01-01T00:00:00Z",
                "last_seen": "2026-01-02T00:00:00Z",
                "data_json": {
                    "project_id": "project-a",
                    "snippet": {"title": f"Title {index}", "channelId": f"channel-{index % 4}"},
                    "topics": [f"topic-{index % 6}"],
                },
            })
            snapshots.append({
                "id": index + 1,
                "video_id": video_id,
                "project_id": "project-a",
                "created_at": f"2026-02-{(index % 28) + 1:02d}T00:00:00Z",
                "data_json": {"project_id": "project-a", "statistics": {"views": index + 100}},
            })

        backend = SupabaseMemoryBackend(client=FakeClient({
            "videos": videos,
            "video_snapshots": snapshots,
        }))
        with patch.dict("os.environ", {
            "DIRECTOR_ANALYSIS_PAGE_SIZE": "50",
            "DIRECTOR_ANALYSIS_WORKING_VIDEOS": "100",
            "DIRECTOR_ANALYSIS_WORKING_SNAPSHOTS": "200",
            "DIRECTOR_ANALYSIS_TOP_EVIDENCE": "20",
        }):
            result = backend.load_youtube_analysis_data(project_id="project-a")

        history = result["history_analytics"]
        self.assertEqual(history["status"], "complete")
        self.assertEqual(history["video_rows_scanned"], 260)
        self.assertEqual(history["snapshot_rows_scanned"], 260)
        self.assertEqual(history["video_count"], 260)
        self.assertEqual(history["snapshot_count"], 260)
        self.assertEqual(len(result["videos"]), 100)
        self.assertEqual(len(result["snapshots"]), 200)
        self.assertEqual(history["snapshot_metrics"]["views"]["count"], 260)

    def test_video_evidence_drilldown_yields_source_and_all_snapshot_pages(self):
        backend = SupabaseMemoryBackend(client=FakeClient({
            "videos": [{
                "video_id": "v1",
                "data_json": {"snippet": {"title": "source video"}},
            }],
            "video_snapshots": [
                {"id": index, "video_id": "v1", "created_at": f"2026-01-0{index}T00:00:00Z",
                 "data_json": {"statistics": {"views": index * 10}}}
                for index in range(1, 6)
            ] + [
                {"id": 99, "video_id": "other", "created_at": "2026-01-01T00:00:00Z",
                 "data_json": {}}
            ],
        }))
        evidence = list(backend.iter_video_evidence("v1", page_size=2))
        self.assertEqual(evidence[0]["kind"], "video")
        self.assertEqual(evidence[0]["row"]["video_id"], "v1")
        snapshots = [item["row"]["id"] for item in evidence if item["kind"] == "snapshot"]
        self.assertEqual(snapshots, [5, 4, 3, 2, 1])

    def test_project_scoped_scan_excludes_unscoped_legacy_snapshots_explicitly(self):
        backend = SupabaseMemoryBackend(client=FakeClient({
            "videos": [{
                "video_id": "v1", "project_id": "project-a",
                "data_json": {"project_id": "project-a", "snippet": {"title": "one"}},
            }],
            "video_snapshots": [
                {"id": 1, "video_id": "v1", "project_id": "project-a",
                 "created_at": "2026-01-01T00:00:00Z",
                 "data_json": {"project_id": "project-a", "statistics": {"views": 10}}},
                {"id": 2, "video_id": "legacy", "created_at": "2026-01-02T00:00:00Z",
                 "data_json": {"statistics": {"views": 999}}},
            ],
        }))
        result = backend.load_youtube_analysis_data(project_id="project-a")
        history = result["history_analytics"]
        self.assertEqual(history["snapshot_count"], 1)
        self.assertEqual(history["unscoped_snapshot_rows_excluded"], 1)

    def test_research_loader_summarizes_all_rows_beyond_working_set_limits(self):
        rows = [
            {
                "id": index,
                "project_id": "project-a",
                "status": "completed" if index % 2 else "planned",
                "language": "en",
                "region": "US",
                "data_json": {"project_id": "project-a"},
            }
            for index in range(1, 2206)
        ]
        backend = SupabaseMemoryBackend(client=FakeClient({
            "youtube_queries": rows,
            "research_sets": rows,
            "data_relations": rows,
        }))
        result = backend.load_research_data(project_id="project-a")
        self.assertEqual(len(result["queries"]), 2000)
        self.assertEqual(result["history_analytics"]["queries"]["matched_rows"], 2205)
        self.assertEqual(
            sum(item["count"] for item in result["history_analytics"]["queries"]["distributions"]["status"]),
            2205,
        )


if __name__ == "__main__":
    unittest.main()
