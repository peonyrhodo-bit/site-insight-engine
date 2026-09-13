"""
YouTube data layer.

Provides a small, stable interface for representing YouTube data
inside the Director data layer.

This module does not perform YouTube API requests.
Actual collection remains in the existing research/collection code.

Its purpose is to normalize references to:
- queries
- videos
- snapshots
- metrics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class YouTubeQuery:
    """
    Represents one YouTube search query used during research.
    """

    query_id: int | str

    text: str = ""

    language: str | None = None

    region: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "query_id": self.query_id,
            "text": self.text,
            "language": self.language,
            "region": self.region,
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass
class YouTubeVideo:
    """
    Represents one YouTube video reference.

    This object stores identifying information and metadata,
    not a duplicate copy of the full video record.
    """

    video_id: int | str

    youtube_id: str = ""

    title: str = ""

    channel_id: str | None = None

    published_at: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "video_id": self.video_id,
            "youtube_id": self.youtube_id,
            "title": self.title,
            "channel_id": self.channel_id,
            "published_at": self.published_at,
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass
class YouTubeSnapshot:
    """
    Represents one snapshot of a YouTube video.
    """

    snapshot_id: int | str

    video_id: int | str

    captured_at: str | None = None

    metrics: dict[str, Any] = field(
        default_factory=dict
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "snapshot_id": self.snapshot_id,
            "video_id": self.video_id,
            "captured_at": self.captured_at,
            "metrics": dict(
                self.metrics
            ),
            "metadata": dict(
                self.metadata
            ),
        }


class YouTubeDataRegistry:
    """
    Lightweight registry for YouTube data references.

    The registry prevents duplicate references inside the
    current data-processing context.

    Persistent storage will remain outside this module.
    """

    def __init__(self) -> None:

        self._queries: dict[
            int | str,
            YouTubeQuery,
        ] = {}

        self._videos: dict[
            int | str,
            YouTubeVideo,
        ] = {}

        self._snapshots: dict[
            int | str,
            YouTubeSnapshot,
        ] = {}

    def add_query(
        self,
        query: YouTubeQuery,
    ) -> YouTubeQuery:

        if query.query_id not in self._queries:

            self._queries[
                query.query_id
            ] = query

        return self._queries[
            query.query_id
        ]

    def add_video(
        self,
        video: YouTubeVideo,
    ) -> YouTubeVideo:

        if video.video_id not in self._videos:

            self._videos[
                video.video_id
            ] = video

        return self._videos[
            video.video_id
        ]

    def add_snapshot(
        self,
        snapshot: YouTubeSnapshot,
    ) -> YouTubeSnapshot:

        if snapshot.snapshot_id not in self._snapshots:

            self._snapshots[
                snapshot.snapshot_id
            ] = snapshot

        return self._snapshots[
            snapshot.snapshot_id
        ]

    def get_query(
        self,
        query_id: int | str,
    ) -> YouTubeQuery | None:

        return self._queries.get(
            query_id
        )

    def get_video(
        self,
        video_id: int | str,
    ) -> YouTubeVideo | None:

        return self._videos.get(
            video_id
        )

    def get_snapshot(
        self,
        snapshot_id: int | str,
    ) -> YouTubeSnapshot | None:

        return self._snapshots.get(
            snapshot_id
        )

    def queries(
        self,
    ) -> list[YouTubeQuery]:

        return list(
            self._queries.values()
        )

    def videos(
        self,
    ) -> list[YouTubeVideo]:

        return list(
            self._videos.values()
        )

    def snapshots(
        self,
    ) -> list[YouTubeSnapshot]:

        return list(
            self._snapshots.values()
        )

    def clear(self) -> None:

        self._queries.clear()
        self._videos.clear()
        self._snapshots.clear()
