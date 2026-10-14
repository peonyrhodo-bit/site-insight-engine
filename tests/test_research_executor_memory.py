from director.research_executor import _research_objects_for_persistence


class FakeObject:
    def __init__(self, object_id):
        self.object_id = object_id

    def to_dict(self):
        return {"id": self.object_id}


class FakeRegistry:
    def __init__(self):
        self.video_objects = {
            "v1": FakeObject("v1"),
            "v2": FakeObject("v2"),
            "old-video": FakeObject("old-video"),
        }
        self.snapshot_objects = {
            "s1": FakeObject("s1"),
            "s2": FakeObject("s2"),
            "old-snapshot": FakeObject("old-snapshot"),
        }

    def get_video(self, object_id):
        return self.video_objects.get(object_id)

    def get_snapshot(self, object_id):
        return self.snapshot_objects.get(object_id)

    def videos(self):
        raise AssertionError("persistence must not scan the full video registry")

    def snapshots(self):
        raise AssertionError("persistence must not scan the full snapshot registry")


def test_persistence_resolves_only_current_research_ids_without_full_registry_scan():
    registry = FakeRegistry()
    research = type(
        "Research",
        (),
        {
            "video_ids": ["v1", "v2", "v1", "missing-video"],
            "snapshot_ids": ["s2", "s1", "s2", "missing-snapshot"],
        },
    )()

    videos, snapshots = _research_objects_for_persistence(registry, research)

    assert [item.to_dict()["id"] for item in videos] == ["v1", "v2"]
    assert [item.to_dict()["id"] for item in snapshots] == ["s2", "s1"]
