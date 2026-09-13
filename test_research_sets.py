from data.research_sets import ResearchSetManager


manager = ResearchSetManager()


research = manager.create(
    research_id=1,
    title="YouTube test research",
    language="ru",
    region="RU",
)


manager.add_query(
    research_id=1,
    query_id=101,
)

manager.add_query(
    research_id=1,
    query_id=102,
)

manager.add_video(
    research_id=1,
    video_id=5001,
)

manager.add_video(
    research_id=1,
    video_id=5002,
)

manager.add_snapshot(
    research_id=1,
    snapshot_id=8001,
)


print(
    "research:",
    research.to_dict()
)

print(
    "find_by_video:",
    manager.find_by_video(
        video_id=5001
    ).to_dict()
)

print(
    "find_by_query:",
    manager.find_by_query(
        query_id=101
    ).to_dict()
)

print(
    "find_by_snapshot:",
    manager.find_by_snapshot(
        snapshot_id=8001
    ).to_dict()
)

print(
    "has_video:",
    research.has_video(
        video_id=5001
    )
)

print(
    "all:",
    [
        item.to_dict()
        for item in manager.all()
    ]
)
