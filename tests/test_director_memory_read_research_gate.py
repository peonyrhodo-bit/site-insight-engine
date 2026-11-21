"""Offline guard: unavailable Supabase reads must not trigger external research."""
from types import SimpleNamespace

import pytest

from director.director import Director


@pytest.mark.asyncio
@pytest.mark.parametrize("read_status", ["error", "unavailable"])
async def test_unavailable_memory_blocks_research_executor(read_status):
    director = object.__new__(Director)
    director.context = SimpleNamespace(
        metadata={"memory_read": {"status": read_status}},
        missing_data=["history"],
    )
    director.state = SimpleNamespace(metadata={})
    director.research_service = SimpleNamespace(
        execute=lambda plan: pytest.fail("external research must not run")
    )
    director.plan_research = lambda **kwargs: SimpleNamespace(
        queries=[],
        objective="offline",
        metadata={"operations": []},
        research_id="offline-id",
        to_dict=lambda: {"research_id": "offline-id"},
    )
    result = await director._autonomy_research(director.state, None)
    assert result["status"] == "blocked"
    assert result["reason"] == "memory_read_unavailable"
