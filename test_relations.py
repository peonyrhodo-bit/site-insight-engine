from data.relations import DataRelations


relations = DataRelations()


relations.link_query(
    research_id=1,
    query_id=101,
)

relations.link_query(
    research_id=1,
    query_id=102,
)

relations.link_video(
    research_id=1,
    video_id=5001,
)

relations.link_snapshot(
    research_id=1,
    video_id=5001,
    snapshot_id=8001,
)


result = relations.get_research_data(
    research_id=1
)

print(result)

print(
    "research_for_video:",
    relations.research_for_video(5001)
)

print(
    "video_for_snapshot:",
    relations.video_for_snapshot(8001)
)
