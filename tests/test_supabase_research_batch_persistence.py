from __future__ import annotations

from typing import Any

from memory.supabase import SupabaseMemoryBackend


class FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class FakeTable:
    def __init__(self, client: "FakeClient", name: str) -> None:
        self.client = client
        self.name = name
        self.payload: Any = None
        self.conflict: str | None = None

    def upsert(self, payload: Any, *, on_conflict: str) -> "FakeTable":
        self.payload = payload
        self.conflict = on_conflict
        return self

    def select(self, _columns: str) -> "FakeTable":
        return self

    def execute(self) -> FakeResponse:
        self.client.calls.append({
            "table": self.name,
            "payload": self.payload,
            "on_conflict": self.conflict,
        })
        return FakeResponse([{"id": index + 1} for index, _ in enumerate(self.payload)])


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)


def test_save_research_data_batches_and_deduplicates_relations() -> None:
    client = FakeClient()
    backend = SupabaseMemoryBackend(client=client)
    relations = [
        {
            "source_type": "video",
            "source_id": "video-a",
            "relation": "discovered_with",
            "target_type": "research",
            "target_id": "research-1",
            "metadata": {"query": "one"},
        },
        {
            "source_type": "video",
            "source_id": "video-b",
            "relation": "discovered_with",
            "target_type": "research",
            "target_id": "research-1",
        },
        {
            "source_type": "video",
            "source_id": "video-a",
            "relation": "discovered_with",
            "target_type": "research",
            "target_id": "research-1",
            "metadata": {"query": "latest"},
        },
    ]

    saved = backend.save_research_data(
        project_id="project-1",
        relations=relations,
    )

    assert saved["relations"] == 2
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["table"] == "data_relations"
    assert isinstance(call["payload"], list)
    assert len(call["payload"]) == 2
    assert call["on_conflict"] == (
        "project_id,source_type,source_id,relation,target_type,target_id"
    )
