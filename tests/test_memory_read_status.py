from types import SimpleNamespace

import pytest

from memory.director_adapter import ServerMemory
from memory.read_status import MemoryReadError, MemoryTableReadError
from memory.supabase import SupabaseMemoryBackend


def _empty_context():
    return {
        "runs": [],
        "decisions": [],
        "recommendations": [],
        "constraints": [],
        "events": [],
        "chat": [],
        "actions": [],
        "results": [],
    }


def test_successful_empty_supabase_context_is_explicitly_complete():
    backend = object.__new__(SupabaseMemoryBackend)
    for name in (
        "runs", "decisions", "recommendations", "constraints",
        "events", "chat", "actions", "results",
    ):
        setattr(backend, f"get_recent_{'chat_messages' if name == 'chat' else name}", lambda **kwargs: [])

    context = backend.get_context(project_id="empty-project")

    assert context["_memory_read"]["status"] == "complete"
    assert all(context[name] == [] for name in _empty_context())
    assert all(
        table["status"] == "complete" and table["rows"] == 0
        for table in context["_memory_read"]["tables"].values()
    )


def test_one_failed_table_marks_context_partial_not_empty():
    backend = object.__new__(SupabaseMemoryBackend)
    for name in (
        "runs", "decisions", "recommendations", "constraints",
        "events", "chat", "actions", "results",
    ):
        method = "get_recent_chat_messages" if name == "chat" else f"get_recent_{name}"
        setattr(backend, method, lambda **kwargs: [])
    backend.get_recent_runs = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable"))

    context = backend.get_context(project_id="partial-project")

    assert context["_memory_read"]["status"] == "partial"
    assert context["_memory_read"]["tables"]["runs"]["status"] == "error"
    assert "database unavailable" in context["_memory_read"]["errors"]["runs"]


def test_all_failed_tables_mark_context_as_error():
    backend = object.__new__(SupabaseMemoryBackend)
    for name in (
        "runs", "decisions", "recommendations", "constraints",
        "events", "chat", "actions", "results",
    ):
        method = "get_recent_chat_messages" if name == "chat" else f"get_recent_{name}"
        setattr(backend, method, lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    context = backend.get_context(project_id="offline-project")

    assert context["_memory_read"]["status"] == "error"
    assert len(context["_memory_read"]["errors"]) == 8


def test_supabase_pagination_error_preserves_rows_already_read():
    class Query:
        def __init__(self):
            self.calls = 0
        def select(self, _columns): return self
        def order(self, _key, desc=False): return self
        def range(self, start, end):
            self.start = start
            return self
        def execute(self):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(data=[{"id": 2}, {"id": 1}])
            raise RuntimeError("page two failed")

    query = Query()
    backend = object.__new__(SupabaseMemoryBackend)
    backend.client = SimpleNamespace(table=lambda _name: query)

    with pytest.raises(MemoryTableReadError) as error:
        backend._recent_for_project(
            "director_runs",
            limit=None,
            project_id=None,
            page_size=2,
        )

    assert [row["id"] for row in error.value.partial_rows] == [2, 1]
    assert "page two failed" in str(error.value.cause)


@pytest.mark.asyncio
async def test_server_memory_returns_a_confirmed_empty_context():
    adapter = object.__new__(ServerMemory)
    adapter.memory = SimpleNamespace(get_context=lambda **kwargs: _empty_context())

    context = await adapter.get_context(project_id="empty-project")

    assert context["_memory_read"]["status"] == "complete"
    assert context["runs"] == []


@pytest.mark.asyncio
async def test_server_memory_raises_with_partial_context_instead_of_returning_empty():
    partial = _empty_context()
    partial["_memory_read"] = {
        "status": "partial",
        "tables": {"runs": {"status": "error", "rows": 0}},
        "errors": {"runs": "database unavailable"},
    }
    adapter = object.__new__(ServerMemory)
    adapter.memory = SimpleNamespace(get_context=lambda **kwargs: partial)

    with pytest.raises(MemoryReadError) as error:
        await adapter.get_context(project_id="partial-project")

    assert error.value.status == "partial"
    assert error.value.context["runs"] == []
    assert "database unavailable" in error.value.errors["runs"]


@pytest.mark.asyncio
async def test_server_memory_raises_error_when_backend_read_throws():
    def fail(**kwargs):
        raise RuntimeError("connection lost")

    adapter = object.__new__(ServerMemory)
    adapter.memory = SimpleNamespace(get_context=fail)

    with pytest.raises(MemoryReadError) as error:
        await adapter.get_context(project_id="failed-project")

    assert error.value.status == "error"
    assert "connection lost" in error.value.errors["context"]


@pytest.mark.asyncio
async def test_server_memory_distinguishes_unavailable_backend():
    adapter = object.__new__(ServerMemory)
    adapter.memory = None

    with pytest.raises(MemoryReadError) as error:
        await adapter.get_context(project_id="unavailable-project")

    assert error.value.status == "unavailable"
