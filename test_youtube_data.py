from data.youtube import (
    YouTubeDataRegistry,
    YouTubeQuery,
    YouTubeVideo,
    YouTubeSnapshot,
)


registry = YouTubeDataRegistry()


query = registry.add_query(
    YouTubeQuery(
        query_id=101,
        text="история Китая",
        language="ru",
        region="RU",
    )
)

video = registry.add_video(
    YouTubeVideo(
        video_id=5001,
        youtube_id="youtube-test-5001",
        title="История Китая",
        channel_id="channel-1",
    )
)

snapshot = registry.add_snapshot(
    YouTubeSnapshot(
        snapshot_id=8001,
        video_id=5001,
        metrics={
            "views": 10000,
            "likes": 500,
        },
    )
)


duplicate_video = registry.add_video(
    YouTubeVideo(
        video_id=5001,
        youtube_id="duplicate-test",
        title="Duplicate video",
    )
)


print(
    "query:",
    query.to_dict()
)

print(
    "video:",
    video.to_dict()
)

print(
    "snapshot:",
    snapshot.to_dict()
)

print(
    "duplicate_video:",
    duplicate_video.to_dict()
)

print(
    "counts:",
    {
        "queries": len(
            registry.queries()
        ),
        "videos": len(
            registry.videos()
        ),
        "snapshots": len(
            registry.snapshots()
        ),
    }
)
