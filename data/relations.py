"""
Data relations layer.

Keeps relationships between already collected data entities.

The goal is to let Director understand:
research -> queries -> videos -> snapshots -> metrics

This module does not collect YouTube data and does not perform analytics.
It only describes and works with relationships between existing data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResearchRelation:
    """
    Describes the relationship between a research run
    and the data collected during that research.
    """

    research_id: int | str

    query_ids: list[int | str] = field(
        default_factory=list
    )

    video_ids: list[int | str] = field(
        default_factory=list
    )

    snapshot_ids: list[int | str] = field(
        default_factory=list
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

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "research_id": self.research_id,
            "query_ids": list(
                self.query_ids
            ),
            "video_ids": list(
                self.video_ids
            ),
            "snapshot_ids": list(
                self.snapshot_ids
            ),
            "metadata": dict(
                self.metadata
            ),
        }


class DataRelations:
    """
    In-memory relationship registry.

    This is the first foundation of the data relations layer.
    Persistence and database integration will be connected later.
    """

    def __init__(self) -> None:

        self._research: dict[
            int | str,
            ResearchRelation,
        ] = {}

        self._video_to_research: dict[
            int | str,
            int | str,
        ] = {}

        self._snapshot_to_video: dict[
            int | str,
            int | str,
        ] = {}

    def get_research(
        self,
        research_id: int | str,
    ) -> ResearchRelation | None:

        return self._research.get(
            research_id
        )

    def create_research(
        self,
        research_id: int | str,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchRelation:

        if research_id not in self._research:

            self._research[
                research_id
            ] = ResearchRelation(
                research_id=research_id,
                metadata=metadata or {},
            )

        return self._research[
            research_id
        ]

    def link_query(
        self,
        research_id: int | str,
        query_id: int | str,
    ) -> ResearchRelation:

        research = self.create_research(
            research_id
        )

        research.add_query(
            query_id
        )

        return research

    def link_video(
        self,
        research_id: int | str,
        video_id: int | str,
    ) -> ResearchRelation:

        research = self.create_research(
            research_id
        )

        research.add_video(
            video_id
        )

        self._video_to_research[
            video_id
        ] = research_id

        return research

    def link_snapshot(
        self,
        research_id: int | str,
        video_id: int | str,
        snapshot_id: int | str,
    ) -> ResearchRelation:

        research = self.create_research(
            research_id
        )

        research.add_video(
            video_id
        )

        research.add_snapshot(
            snapshot_id
        )

        self._video_to_research[
            video_id
        ] = research_id

        self._snapshot_to_video[
            snapshot_id
        ] = video_id

        return research

    def research_for_video(
        self,
        video_id: int | str,
    ) -> int | str | None:

        return self._video_to_research.get(
            video_id
        )

    def video_for_snapshot(
        self,
        snapshot_id: int | str,
    ) -> int | str | None:

        return self._snapshot_to_video.get(
            snapshot_id
        )

    def get_research_data(
        self,
        research_id: int | str,
    ) -> dict[str, Any] | None:

        research = self.get_research(
            research_id
        )

        if research is None:
            return None

        return research.to_dict()

    def clear(self) -> None:

        self._research.clear()
        self._video_to_research.clear()
        self._snapshot_to_video.clear()
