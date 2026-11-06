from types import SimpleNamespace

from memory.supabase import SupabaseMemoryBackend


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.columns = "*"
        self.start = 0
        self.end = 999

    def select(self, columns):
        self.columns = columns
        self.client.selected_columns[self.table_name] = columns
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        rows = self.client.rows.get(self.table_name, [])
        return SimpleNamespace(data=rows[self.start:self.end + 1])


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.selected_columns = {}

    def table(self, name):
        return FakeQuery(self, name)


def test_compact_analysis_loader_keeps_signals_and_drops_long_payloads():
    tags = [f"tag-{index}" for index in range(80)]
    client = FakeClient(
        {
            "videos": [
                {
                    "video_id": "video-1",
                    "first_seen": "2026-01-01T00:00:00Z",
                    "last_seen": "2026-01-02T00:00:00Z",
                    "data_json": {
                        "project_id": "project-a",
                        "snippet": {
                            "title": "A useful title",
                            "channelId": "channel-1",
                            "channelTitle": "Channel One",
                            "publishedAt": "2026-01-01T00:00:00Z",
                            "tags": tags,
                            "description": "x" * 10000,
                        },
                        "topics": ["science", "education"],
                        "description": "x" * 10000,
                    },
                }
            ],
            "video_snapshots": [
                {
                    "id": 10,
                    "video_id": "video-1",
                    "created_at": "2026-01-02T00:00:00Z",
                    "data_json": {
                        "project_id": "project-a",
                        "statistics": {
                            "viewCount": "1200",
                            "likeCount": "80",
                            "commentCount": "12",
                        },
                    },
                },
                {
                    "id": 9,
                    "video_id": "video-1",
                    "created_at": "2026-01-01T12:00:00Z",
                    "data_json": {
                        "project_id": "project-a",
                        "statistics": {
                            "viewCount": "900",
                            "likeCount": "60",
                            "commentCount": "8",
                        },
                    },
                }
            ],
        }
    )
    backend = SupabaseMemoryBackend(client=client)

    result = backend.load_youtube_analysis_data(project_id="project-a")

    assert len(result["videos"]) == 1
    video = result["videos"][0]
    assert video["title"] == "A useful title"
    assert video["channel_id"] == "channel-1"
    assert video["metadata"]["topics"] == ["science", "education"]
    assert len(video["metadata"]["tags"]) == 30
    assert "description" not in video["metadata"]
    assert len(result["snapshots"]) == 2
    assert result["snapshots"][0]["metrics"]["viewCount"] == 1200
    assert result["snapshots"][1]["metrics"]["viewCount"] == 900
    assert result["snapshots"][0]["metadata"] == {}
    assert client.selected_columns["videos"] == "video_id,data_json,first_seen,last_seen"
    assert client.selected_columns["video_snapshots"] == "id,video_id,created_at,data_json"


def test_analysis_metadata_bounds_keyword_payloads():
    metadata = SupabaseMemoryBackend._analysis_metadata(
        {
            "keywords": ["k" * 500 for _ in range(100)],
            "description": "large description",
        }
    )

    assert len(metadata["keywords"]) == 30
    assert all(len(keyword) == 120 for keyword in metadata["keywords"])
    assert "description" not in metadata
