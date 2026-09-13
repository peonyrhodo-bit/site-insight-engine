"""
Research sets layer.

A research set represents one coherent research dataset.

Example:

research_set
    ├── queries
    ├── videos
    ├── snapshots
    └── metadata

The purpose is to identify data that belongs to the same research
and make it possible to reuse existing data instead of collecting
the same information again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ResearchSet:
    """
    Represents one research dataset.
    """

    research_id: int | str

    title: str = ""

    status: str = "active"

    query_ids: list[int | str] = field(
        default_factory=list
    )

    video_ids: list[int | str] = field(
        default_factory=list
    )

    snapshot_ids: list[int | str] = field(
        default_factory=list
    )

    language: str | None = None

    region: str | None = None

    created_at: str = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def add_query(
        self,
        query_id: int | str,
    ) -> None:

        if query_id not in self.query_ids:
            self.query_ids.append(
                query_id
            )

    def add_video(
        self,
        video_id: int | str,
    ) -> None:

        if video_id not in self.video_ids:
            self.video_ids.append(
                video_id
            )

    def add_snapshot(
        self,
        snapshot_id: int | str,
    ) -> None:

        if snapshot_id not in self.snapshot_ids:
            self.snapshot_ids.append(
                snapshot_id
            )

    def has_video(
        self,
        video_id: int | str,
    ) -> bool:

        return video_id in self.video_ids

    def has_query(
        self,
        query_id: int | str,
    ) -> bool:

        return query_id in self.query_ids

    def has_snapshot(
        self,
        snapshot_id: int | str,
    ) -> bool:

        return snapshot_id in self.snapshot_ids

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "research_id": self.research_id,
            "title": self.title,
            "status": self.status,
            "query_ids": list(
                self.query_ids
            ),
            "video_ids": list(
                self.video_ids
            ),
            "snapshot_ids": list(
                self.snapshot_ids
            ),
            "language": self.language,
            "region": self.region,
            "created_at": self.created_at,
            "metadata": dict(
                self.metadata
            ),
        }


class ResearchSetManager:
    """
    Manages research sets in memory.

    Persistence will be connected later.
    """

    def __init__(self) -> None:

        self._sets: dict[
            int | str,
            ResearchSet,
        ] = {}

    def create(
        self,
        research_id: int | str,
        title: str = "",
        language: str | None = None,
        region: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchSet:

        if research_id in self._sets:

            return self._sets[
                research_id
            ]

        research_set = ResearchSet(
            research_id=research_id,
            title=title,
            language=language,
            region=region,
            metadata=metadata or {},
        )

        self._sets[
            research_id
        ] = research_set

        return research_set

    def get(
        self,
        research_id: int | str,
    ) -> ResearchSet | None:

        return self._sets.get(
            research_id
        )

    def add_query(
        self,
        research_id: int | str,
        query_id: int | str,
    ) -> ResearchSet:

        research_set = self.create(
            research_id
        )

        research_set.add_query(
            query_id
        )

        return research_set

    def add_video(
        self,
        research_id: int | str,
        video_id: int | str,
    ) -> ResearchSet:

        research_set = self.create(
            research_id
        )

        research_set.add_video(
            video_id
        )

        return research_set

    def add_snapshot(
        self,
        research_id: int | str,
        snapshot_id: int | str,
    ) -> ResearchSet:

        research_set = self.create(
            research_id
        )

        research_set.add_snapshot(
            snapshot_id
        )

        return research_set

    def find_by_video(
        self,
        video_id: int | str,
    ) -> ResearchSet | None:

        for research_set in self._sets.values():

            if research_set.has_video(
                video_id
            ):
                return research_set

        return None

    def find_by_query(
        self,
        query_id: int | str,
    ) -> ResearchSet | None:

        for research_set in self._sets.values():

            if research_set.has_query(
                query_id
            ):
                return research_set

        return None

    def find_by_snapshot(
        self,
        snapshot_id: int | str,
    ) -> ResearchSet | None:

        for research_set in self._sets.values():

            if research_set.has_snapshot(
                snapshot_id
            ):
                return research_set

        return None

    def all(
        self,
    ) -> list[ResearchSet]:

        return list(
            self._sets.values()
        )

    def clear(self) -> None:

        self._sets.clear()
