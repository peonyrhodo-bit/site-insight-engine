from memory.inmemory import InMemoryMemoryBackend
from memory.memory import Memory


def test_update_run_merges_lifecycle_fields_without_losing_original_payload():
    backend = InMemoryMemoryBackend()
    memory = Memory(backend=backend)
    run_id = memory.save_run(data={
        "project_id": "test-project",
        "type": "autonomous_cycle",
        "status": "requested",
        "custom_context": {"kept": True},
    })
    assert run_id is not None

    assert memory.update_run(run_id=run_id, data={
        "project_id": "test-project",
        "status": "running",
        "current_step": "director_cycle",
        "started_at": "2026-10-11T20:00:00+00:00",
        "updated_at": "2026-10-11T20:00:01+00:00",
    })

    row = backend.get_recent_runs(limit=1)[0]
    assert row["data_json"]["status"] == "running"
    assert row["data_json"]["current_step"] == "director_cycle"
    assert row["data_json"]["custom_context"] == {"kept": True}
    assert row["status"] == "running"
    assert row["project_id"] == "test-project"


def test_update_run_returns_false_for_missing_id():
    memory = Memory(backend=InMemoryMemoryBackend())
    assert memory.update_run(run_id=999, data={"status": "failed"}) is False
