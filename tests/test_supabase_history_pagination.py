import unittest

from memory.supabase import SupabaseMemoryBackend


class FakeResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.orders = []
        self.start = None
        self.end = None
        self.filters = []
        self.in_filters = []
        self.head = False

    def select(self, _columns, count=None, head=False):
        self.head = head
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def in_(self, key, values):
        self.in_filters.append((key, set(values)))
        return self

    def order(self, key, desc=False, **_kwargs):
        self.orders.append((key, desc))
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        rows = list(self.rows)
        for key, value in self.filters:
            if "->>" in key:
                column, json_key = key.split("->>", 1)
                rows = [
                    row for row in rows
                    if str((row.get(column) or {}).get(json_key)) == str(value)
                ]
            else:
                rows = [row for row in rows if str(row.get(key)) == str(value)]
        for key, values in self.in_filters:
            rows = [row for row in rows if str(row.get(key)) in values]
        count = len(rows)
        # Python's stable sort lets the first declared key remain primary.
        for key, desc in reversed(self.orders):
            rows.sort(key=lambda row: (row.get(key) is None, row.get(key)), reverse=desc)
        if self.head:
            return FakeResponse([], count=count)
        if self.start is not None:
            rows = rows[self.start : self.end + 1]
        return FakeResponse(rows, count=count)


class FakeClient:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeQuery(self.tables.get(name, []))


def make_rows(count, project_id="project-a"):
    return [
        {
            "id": index,
            "project_id": project_id if index % 4 else "project-b",
            "created_at": f"2026-01-{(index % 28) + 1:02d}T00:00:00Z",
            "data_json": {"project_id": project_id if index % 4 else "project-b"},
        }
        for index in range(1, count + 1)
    ]


class RecentForProjectPaginationTests(unittest.TestCase):
    def setUp(self):
        self.rows = make_rows(2305)
        self.backend = SupabaseMemoryBackend(client=FakeClient({"history": self.rows}))

    def test_reads_all_pages_filters_project_and_has_no_duplicate_or_missing_ids(self):
        result = self.backend._recent_for_project(
            "history",
            limit=None,
            project_id="project-a",
            order_key="id",
        )
        expected = [row["id"] for row in self.rows if row["project_id"] == "project-a"]
        actual = [row["id"] for row in result]

        self.assertEqual(len(actual), len(expected))
        self.assertEqual(len(actual), len(set(actual)))
        self.assertEqual(set(actual), set(expected))
        self.assertEqual(actual, sorted(expected, reverse=True))

    def test_requested_limit_above_100_is_not_clamped(self):
        result = self.backend._recent_for_project(
            "history",
            limit=250,
            project_id=None,
            order_key="id",
        )
        self.assertEqual(len(result), 250)
        self.assertEqual([row["id"] for row in result], list(range(2305, 2055, -1)))


class ResearchAndOpportunityHistoryTests(unittest.TestCase):
    def test_research_queries_sets_and_relations_load_all_pages(self):
        tables = {
            "youtube_queries": make_rows(1207),
            "research_sets": make_rows(1207),
            "data_relations": make_rows(1207),
        }
        backend = SupabaseMemoryBackend(client=FakeClient(tables))

        result = backend.load_research_data(project_id="project-a")

        for key in ("queries", "research_sets", "relations"):
            expected_ids = [r["id"] for r in tables[
                {"queries": "youtube_queries", "research_sets": "research_sets", "relations": "data_relations"}[key]
            ] if r["project_id"] == "project-a"]
            actual_ids = [r["id"] for r in result[key]]
            self.assertEqual(len(actual_ids), len(expected_ids), key)
            self.assertEqual(len(actual_ids), len(set(actual_ids)), key)
            self.assertEqual(set(actual_ids), set(expected_ids), key)

    def test_channels_and_opportunity_tables_use_bounded_working_sets(self):
        tables = {
            "channels": make_rows(1207),
            "channel_snapshots": make_rows(1207),
            "niches": make_rows(1207),
            "niche_snapshots": make_rows(1207),
        }
        backend = SupabaseMemoryBackend(client=FakeClient(tables))

        from unittest.mock import patch

        limits = {
            "DIRECTOR_CHANNELS_IN_MEMORY": "500",
            "DIRECTOR_CHANNEL_SNAPSHOTS_IN_MEMORY": "500",
            "DIRECTOR_NICHES_IN_MEMORY": "250",
            "DIRECTOR_NICHE_SNAPSHOTS_IN_MEMORY": "500",
        }
        with patch.dict("os.environ", limits):
            result = backend.load_opportunity_data(project_id="project-a")

        expected_limits = {
            "channels": 500,
            "channel_snapshots": 500,
            "niches": 250,
            "niche_snapshots": 500,
        }
        for key, source_table in (
            ("channels", "channels"),
            ("channel_snapshots", "channel_snapshots"),
            ("niches", "niches"),
            ("niche_snapshots", "niche_snapshots"),
        ):
            expected_ids = [r["id"] for r in tables[source_table] if r["project_id"] == "project-a"]
            actual_ids = [r["id"] for r in result[key]]
            self.assertEqual(len(actual_ids), min(expected_limits[key], len(expected_ids)), key)
            self.assertEqual(len(actual_ids), len(set(actual_ids)), key)
            self.assertTrue(set(actual_ids).issubset(set(expected_ids)), key)



class BoundedYouTubeAnalysisLoaderTests(unittest.TestCase):
    def test_loader_filters_and_caps_videos_before_materializing_snapshots(self):
        from unittest.mock import patch

        videos = [
            {
                "video_id": f"video-{index:04d}",
                "last_seen": f"2026-11-{(index % 28) + 1:02d}T00:00:00Z",
                "first_seen": "2026-01-01T00:00:00Z",
                "data_json": {
                    "project_id": "project-a" if index % 5 else "project-b",
                    "snippet": {"title": f"Video {index}", "channelId": "channel-1"},
                },
            }
            for index in range(260)
        ]
        snapshots = []
        for index in range(260):
            project = "project-a" if index % 5 else "project-b"
            for version in range(4):
                snapshots.append({
                    "id": index * 4 + version + 1,
                    "video_id": f"video-{index:04d}",
                    "created_at": f"2026-11-{version + 1:02d}T00:00:00Z",
                    "data_json": {
                        "project_id": project,
                        "statistics": {"viewCount": str(100 + version)},
                    },
                })

        backend = SupabaseMemoryBackend(
            client=FakeClient({"videos": videos, "video_snapshots": snapshots})
        )
        with patch.dict("os.environ", {
            "DIRECTOR_ANALYSIS_MAX_VIDEOS": "100",
            "DIRECTOR_ANALYSIS_PAGE_SIZE": "50",
            "DIRECTOR_SNAPSHOTS_PER_VIDEO": "2",
        }):
            result = backend.load_youtube_analysis_data(project_id="project-a")

        self.assertEqual(result["inventory"]["video_count"], 208)
        self.assertEqual(result["inventory"]["snapshot_count"], 832)
        self.assertEqual(len(result["videos"]), 100)
        self.assertEqual(len(result["snapshots"]), 200)
        selected_ids = {row["video_id"] for row in result["videos"]}
        self.assertEqual(
            {row["video_id"] for row in result["snapshots"]},
            selected_ids,
        )
        self.assertEqual(
            result["inventory"]["working_video_count"],
            len(result["videos"]),
        )
        self.assertEqual(
            result["inventory"]["working_snapshot_count"],
            len(result["snapshots"]),
        )

if __name__ == "__main__":
    unittest.main()
