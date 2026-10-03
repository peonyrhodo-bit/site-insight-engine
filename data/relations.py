"""
DATA relations for AI Director.

This module defines explicit relationships between:
    research -> queries -> videos -> snapshots -> metrics

The module is intentionally DATA-only.

It does NOT:
- make strategic decisions;
- score opportunities;
- call YouTube/MCP;
- call AI providers;
- decide what to research next;
- persist data to Supabase.

Its responsibility is to make relationships between collected data
explicit, queryable and reusable by Analytics and Director.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from data.youtube import (
    YouTubeDataRegistry,
    YouTubeQuery,
    YouTubeSnapshot,
    YouTubeVideo,
)
from data.research_sets import (
    ResearchSet,
    ResearchSetManager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_id(value: Any) -> int | str:
    if isinstance(value, bool):
        return str(value)

    if isinstance(value, int):
        return value

    text = str(value).strip()

    if not text:
        raise ValueError("identifier must not be empty")

    return text


def _normalize_ids(
    values: Iterable[Any] | None,
) -> list[int | str]:
    if values is None:
        return []

    result: list[int | str] = []
    seen: set[int | str] = set()

    for value in values:
        identifier = _normalize_id(value)

        if identifier not in seen:
            seen.add(identifier)
            result.append(identifier)

    return result


# ---------------------------------------------------------------------------
# Relation types
# ---------------------------------------------------------------------------


RELATION_TYPES = {
    "research_query",
    "research_video",
    "research_snapshot",
    "query_video",
    "video_snapshot",
    "snapshot_video",
    "snapshot_research",
}


# ---------------------------------------------------------------------------
# Generic relation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataRelation:
    """
    Explicit relationship between two DATA objects.

    Example:

        research 123
            -> video abc

    becomes:

        source_type="research"
        source_id=123
        relation="contains"
        target_type="video"
        target_id="abc"
    """

    source_type: str
    source_id: int | str

    relation: str

    target_type: str
    target_id: int | str

    created_at: str = field(
        default_factory=_utc_now
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_type",
            str(self.source_type).strip().lower(),
        )

        object.__setattr__(
            self,
            "target_type",
            str(self.target_type).strip().lower(),
        )

        object.__setattr__(
            self,
            "relation",
            str(self.relation).strip().lower(),
        )

        object.__setattr__(
            self,
            "source_id",
            _normalize_id(self.source_id),
        )

        object.__setattr__(
            self,
            "target_id",
            _normalize_id(self.target_id),
        )

        object.__setattr__(
            self,
            "metadata",
            dict(self.metadata or {}),
        )

    def key(
        self,
    ) -> tuple[
        str,
        int | str,
        str,
        str,
        int | str,
    ]:
        return (
            self.source_type,
            self.source_id,
            self.relation,
            self.target_type,
            self.target_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "relation": self.relation,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "DataRelation":
        return cls(
            source_type=data["source_type"],
            source_id=data["source_id"],
            relation=data["relation"],
            target_type=data["target_type"],
            target_id=data["target_id"],
            created_at=data.get(
                "created_at",
                _utc_now(),
            ),
            metadata=data.get(
                "metadata",
                {},
            ),
        )


# ---------------------------------------------------------------------------
# Research relation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchRelation:
    """
    Compact representation of a research data graph.

    This is useful when Analytics or Director needs to understand
    everything collected during one research operation.
    """

    research_id: int | str

    query_ids: tuple[
        int | str,
        ...,
    ] = ()

    video_ids: tuple[
        int | str,
        ...,
    ] = ()

    snapshot_ids: tuple[
        int | str,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "research_id",
            _normalize_id(self.research_id),
        )

        object.__setattr__(
            self,
            "query_ids",
            tuple(
                _normalize_ids(
                    self.query_ids
                )
            ),
        )

        object.__setattr__(
            self,
            "video_ids",
            tuple(
                _normalize_ids(
                    self.video_ids
                )
            ),
        )

        object.__setattr__(
            self,
            "snapshot_ids",
            tuple(
                _normalize_ids(
                    self.snapshot_ids
                )
            ),
        )

    @property
    def query_count(self) -> int:
        return len(self.query_ids)

    @property
    def video_count(self) -> int:
        return len(self.video_ids)

    @property
    def snapshot_count(self) -> int:
        return len(self.snapshot_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_id": self.research_id,
            "query_ids": list(self.query_ids),
            "video_ids": list(self.video_ids),
            "snapshot_ids": list(self.snapshot_ids),
        }


# ---------------------------------------------------------------------------
# Relations manager
# ---------------------------------------------------------------------------


class DataRelations:
    """
    Central in-memory relationship registry.

    It connects DATA objects without taking ownership of their storage.

    Typical flow:

        YouTubeQuery
             |
             v
        ResearchSet
             |
             v
        YouTubeVideo
             |
             v
        YouTubeSnapshot
    """

    def __init__(
        self,
        *,
        youtube_registry: YouTubeDataRegistry | None = None,
        research_manager: ResearchSetManager | None = None,
    ) -> None:
        self.youtube_registry = (
            youtube_registry
            or YouTubeDataRegistry()
        )

        self.research_manager = (
            research_manager
            or ResearchSetManager(
                registry=self.youtube_registry
            )
        )

        self._relations: dict[
            tuple[
                str,
                int | str,
                str,
                str,
                int | str,
            ],
            DataRelation,
        ] = {}

    # ------------------------------------------------------------------
    # Generic relation management
    # ------------------------------------------------------------------

    def add_relation(
        self,
        relation: DataRelation,
    ) -> DataRelation:
        if not isinstance(
            relation,
            DataRelation,
        ):
            raise TypeError(
                "relation must be DataRelation"
            )

        self._relations[
            relation.key()
        ] = relation

        return relation

    def remove_relation(
        self,
        relation: DataRelation,
    ) -> bool:
        return (
            self._relations.pop(
                relation.key(),
                None,
            )
            is not None
        )

    def has_relation(
        self,
        *,
        source_type: str,
        source_id: int | str,
        relation: str,
        target_type: str,
        target_id: int | str,
    ) -> bool:
        key = (
            str(source_type).lower(),
            _normalize_id(source_id),
            str(relation).lower(),
            str(target_type).lower(),
            _normalize_id(target_id),
        )

        return key in self._relations

    def all_relations(
        self,
    ) -> list[DataRelation]:
        return list(
            self._relations.values()
        )

    def relation_count(self) -> int:
        return len(self._relations)

    # ------------------------------------------------------------------
    # Research -> Query
    # ------------------------------------------------------------------

    def link_research_query(
        self,
        research: ResearchSet | int | str,
        query: YouTubeQuery | int | str,
    ) -> DataRelation:
        research_id = (
            research.research_id
            if isinstance(
                research,
                ResearchSet,
            )
            else _normalize_id(research)
        )

        query_id = (
            query.query_id
            if isinstance(
                query,
                YouTubeQuery,
            )
            else _normalize_id(query)
        )

        relation = DataRelation(
            source_type="research",
            source_id=research_id,
            relation="contains_query",
            target_type="query",
            target_id=query_id,
        )

        self.add_relation(
            relation
        )

        research_object = (
            self.research_manager.get(
                research_id
            )
        )

        if research_object is not None:
            research_object.add_query(
                query_id
            )

        return relation

    # ------------------------------------------------------------------
    # Research -> Video
    # ------------------------------------------------------------------

    def link_research_video(
        self,
        research: ResearchSet | int | str,
        video: YouTubeVideo | int | str,
        *,
        reusable: bool = False,
        reused: bool = False,
    ) -> DataRelation:
        research_id = (
            research.research_id
            if isinstance(
                research,
                ResearchSet,
            )
            else _normalize_id(research)
        )

        video_id = (
            video.video_id
            if isinstance(
                video,
                YouTubeVideo,
            )
            else _normalize_id(video)
        )

        relation = DataRelation(
            source_type="research",
            source_id=research_id,
            relation="contains_video",
            target_type="video",
            target_id=video_id,
            metadata={
                "reusable": reusable,
                "reused": reused,
            },
        )

        self.add_relation(
            relation
        )

        research_object = (
            self.research_manager.get(
                research_id
            )
        )

        if research_object is not None:
            research_object.add_video(
                video_id,
                reusable=reusable,
                reused=reused,
            )

        return relation

    # ------------------------------------------------------------------
    # Research -> Snapshot
    # ------------------------------------------------------------------

    def link_research_snapshot(
        self,
        research: ResearchSet | int | str,
        snapshot: YouTubeSnapshot | int | str,
    ) -> DataRelation:
        research_id = (
            research.research_id
            if isinstance(
                research,
                ResearchSet,
            )
            else _normalize_id(research)
        )

        snapshot_id = (
            snapshot.snapshot_id
            if isinstance(
                snapshot,
                YouTubeSnapshot,
            )
            else _normalize_id(snapshot)
        )

        relation = DataRelation(
            source_type="research",
            source_id=research_id,
            relation="contains_snapshot",
            target_type="snapshot",
            target_id=snapshot_id,
        )

        self.add_relation(
            relation
        )

        research_object = (
            self.research_manager.get(
                research_id
            )
        )

        if research_object is not None:
            research_object.add_snapshot(
                snapshot_id
            )

        return relation

    # ------------------------------------------------------------------
    # Query -> Video
    # ------------------------------------------------------------------

    def link_query_video(
        self,
        query: YouTubeQuery | int | str,
        video: YouTubeVideo | int | str,
    ) -> DataRelation:
        query_id = (
            query.query_id
            if isinstance(
                query,
                YouTubeQuery,
            )
            else _normalize_id(query)
        )

        video_id = (
            video.video_id
            if isinstance(
                video,
                YouTubeVideo,
            )
            else _normalize_id(video)
        )

        relation = DataRelation(
            source_type="query",
            source_id=query_id,
            relation="returned_video",
            target_type="video",
            target_id=video_id,
        )

        self.add_relation(
            relation
        )

        return relation

    # ------------------------------------------------------------------
    # Video -> Snapshot
    # ------------------------------------------------------------------

    def link_video_snapshot(
        self,
        video: YouTubeVideo | int | str,
        snapshot: YouTubeSnapshot | int | str,
    ) -> DataRelation:
        video_id = (
            video.video_id
            if isinstance(
                video,
                YouTubeVideo,
            )
            else _normalize_id(video)
        )

        snapshot_id = (
            snapshot.snapshot_id
            if isinstance(
                snapshot,
                YouTubeSnapshot,
            )
            else _normalize_id(snapshot)
        )

        relation = DataRelation(
            source_type="video",
            source_id=video_id,
            relation="has_snapshot",
            target_type="snapshot",
            target_id=snapshot_id,
        )

        self.add_relation(
            relation
        )

        return relation

    # ------------------------------------------------------------------
    # Reverse links
    # ------------------------------------------------------------------

    def link_snapshot_video(
        self,
        snapshot: YouTubeSnapshot | int | str,
        video: YouTubeVideo | int | str,
    ) -> DataRelation:
        snapshot_id = (
            snapshot.snapshot_id
            if isinstance(
                snapshot,
                YouTubeSnapshot,
            )
            else _normalize_id(snapshot)
        )

        video_id = (
            video.video_id
            if isinstance(
                video,
                YouTubeVideo,
            )
            else _normalize_id(video)
        )

        relation = DataRelation(
            source_type="snapshot",
            source_id=snapshot_id,
            relation="belongs_to_video",
            target_type="video",
            target_id=video_id,
        )

        self.add_relation(
            relation
        )

        return relation

    # ------------------------------------------------------------------
    # Query relations
    # ------------------------------------------------------------------

    def relations_from(
        self,
        *,
        source_type: str,
        source_id: int | str,
        relation: str | None = None,
    ) -> list[DataRelation]:
        source_type = str(
            source_type
        ).lower()

        source_id = _normalize_id(
            source_id
        )

        relation = (
            str(relation).lower()
            if relation
            else None
        )

        return [
            item
            for item in self._relations.values()
            if item.source_type
            == source_type
            and item.source_id
            == source_id
            and (
                relation is None
                or item.relation == relation
            )
        ]

    def relations_to(
        self,
        *,
        target_type: str,
        target_id: int | str,
        relation: str | None = None,
    ) -> list[DataRelation]:
        target_type = str(
            target_type
        ).lower()

        target_id = _normalize_id(
            target_id
        )

        relation = (
            str(relation).lower()
            if relation
            else None
        )

        return [
            item
            for item in self._relations.values()
            if item.target_type
            == target_type
            and item.target_id
            == target_id
            and (
                relation is None
                or item.relation == relation
            )
        ]

    # ------------------------------------------------------------------
    # Research graph
    # ------------------------------------------------------------------

    def research_graph(
        self,
        research_id: int | str,
    ) -> ResearchRelation:
        normalized = _normalize_id(
            research_id
        )

        query_ids: list[int | str] = []
        video_ids: list[int | str] = []
        snapshot_ids: list[int | str] = []

        for relation in self.relations_from(
            source_type="research",
            source_id=normalized,
        ):
            if relation.target_type == "query":
                query_ids.append(
                    relation.target_id
                )

            elif relation.target_type == "video":
                video_ids.append(
                    relation.target_id
                )

            elif relation.target_type == "snapshot":
                snapshot_ids.append(
                    relation.target_id
                )

        return ResearchRelation(
            research_id=normalized,
            query_ids=tuple(query_ids),
            video_ids=tuple(video_ids),
            snapshot_ids=tuple(snapshot_ids),
        )

    # ------------------------------------------------------------------
    # Research lookup through graph
    # ------------------------------------------------------------------

    def research_for_video(
        self,
        video_id: int | str,
    ) -> list[int | str]:
        normalized = _normalize_id(
            video_id
        )

        return [
            relation.source_id
            for relation in self.relations_to(
                target_type="video",
                target_id=normalized,
            )
            if relation.source_type
            == "research"
        ]

    def research_for_snapshot(
        self,
        snapshot_id: int | str,
    ) -> list[int | str]:
        normalized = _normalize_id(
            snapshot_id
        )

        return [
            relation.source_id
            for relation in self.relations_to(
                target_type="snapshot",
                target_id=normalized,
            )
            if relation.source_type
            == "research"
        ]

    def queries_for_video(
        self,
        video_id: int | str,
    ) -> list[int | str]:
        normalized = _normalize_id(
            video_id
        )

        return [
            relation.source_id
            for relation in self.relations_to(
                target_type="video",
                target_id=normalized,
            )
            if relation.source_type
            == "query"
        ]

    def snapshots_for_video(
        self,
        video_id: int | str,
    ) -> list[int | str]:
        normalized = _normalize_id(
            video_id
        )

        return [
            relation.target_id
            for relation in self.relations_from(
                source_type="video",
                source_id=normalized,
                relation="has_snapshot",
            )
        ]

    def videos_for_query(
        self,
        query_id: int | str,
    ) -> list[int | str]:
        normalized = _normalize_id(
            query_id
        )

        return [
            relation.target_id
            for relation in self.relations_from(
                source_type="query",
                source_id=normalized,
                relation="returned_video",
            )
        ]

    # ------------------------------------------------------------------
    # Complete data chain
    # ------------------------------------------------------------------

    def data_chain_for_video(
        self,
        video_id: int | str,
    ) -> dict[str, Any]:
        """
        Return the complete known lineage for one video.
        """

        normalized = _normalize_id(
            video_id
        )

        query_ids = self.queries_for_video(
            normalized
        )

        research_ids = self.research_for_video(
            normalized
        )

        snapshot_ids = self.snapshots_for_video(
            normalized
        )

        return {
            "video_id": normalized,
            "query_ids": query_ids,
            "research_ids": research_ids,
            "snapshot_ids": snapshot_ids,
        }

    def data_chain_for_snapshot(
        self,
        snapshot_id: int | str,
    ) -> dict[str, Any]:
        """
        Return the complete known lineage for one snapshot.
        """

        normalized = _normalize_id(
            snapshot_id
        )

        video_relations = self.relations_to(
            target_type="snapshot",
            target_id=normalized,
        )

        video_ids = [
            relation.source_id
            for relation in video_relations
            if relation.source_type
            == "video"
        ]

        research_ids = (
            self.research_for_snapshot(
                normalized
            )
        )

        query_ids: list[int | str] = []

        for video_id in video_ids:
            query_ids.extend(
                self.queries_for_video(
                    video_id
                )
            )

        return {
            "snapshot_id": normalized,
            "video_ids": list(
                dict.fromkeys(video_ids)
            ),
            "query_ids": list(
                dict.fromkeys(query_ids)
            ),
            "research_ids": list(
                dict.fromkeys(research_ids)
            ),
        }

    # ------------------------------------------------------------------
    # Synchronization with ResearchSet
    # ------------------------------------------------------------------

    def sync_research_set(
        self,
        research_id: int | str,
    ) -> ResearchRelation:
        """
        Synchronize graph relationships from an existing ResearchSet.

        This is useful during migration from the old implicit data model.
        """

        research = (
            self.research_manager.require(
                research_id
            )
        )

        for query_id in research.query_ids:
            self.link_research_query(
                research,
                query_id,
            )

        for video_id in research.video_ids:
            self.link_research_video(
                research,
                video_id,
                reusable=(
                    video_id
                    in research.reusable_video_ids
                ),
                reused=(
                    video_id
                    in research.reused_video_ids
                ),
            )

        for snapshot_id in research.snapshot_ids:
            self.link_research_snapshot(
                research,
                snapshot_id,
            )

        return self.research_graph(
            research.research_id
        )

    def sync_all_research_sets(
        self,
    ) -> list[ResearchRelation]:
        return [
            self.sync_research_set(
                research.research_id
            )
            for research
            in self.research_manager.all()
        ]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_research(
        self,
        research_id: int | str,
    ) -> dict[str, Any]:
        """
        Check whether the explicit relation graph matches the
        ResearchSet's own ID lists.
        """

        research = (
            self.research_manager.require(
                research_id
            )
        )

        graph = self.research_graph(
            research.research_id
        )

        expected_queries = set(
            research.query_ids
        )

        expected_videos = set(
            research.video_ids
        )

        expected_snapshots = set(
            research.snapshot_ids
        )

        graph_queries = set(
            graph.query_ids
        )

        graph_videos = set(
            graph.video_ids
        )

        graph_snapshots = set(
            graph.snapshot_ids
        )

        return {
            "research_id": research.research_id,
            "valid": (
                expected_queries
                == graph_queries
                and expected_videos
                == graph_videos
                and expected_snapshots
                == graph_snapshots
            ),
            "missing_query_relations": list(
                expected_queries
                - graph_queries
            ),
            "missing_video_relations": list(
                expected_videos
                - graph_videos
            ),
            "missing_snapshot_relations": list(
                expected_snapshots
                - graph_snapshots
            ),
            "orphan_query_relations": list(
                graph_queries
                - expected_queries
            ),
            "orphan_video_relations": list(
                graph_videos
                - expected_videos
            ),
            "orphan_snapshot_relations": list(
                graph_snapshots
                - expected_snapshots
            ),
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "relations": [
                relation.to_dict()
                for relation
                in self._relations.values()
            ]
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        youtube_registry: YouTubeDataRegistry | None = None,
        research_manager: ResearchSetManager | None = None,
    ) -> "DataRelations":
        manager = cls(
            youtube_registry=youtube_registry,
            research_manager=research_manager,
        )

        for item in (
            data.get(
                "relations",
                [],
            )
            or []
        ):
            manager.add_relation(
                DataRelation.from_dict(
                    item
                )
            )

        return manager

    def clear(self) -> None:
        self._relations.clear()


__all__ = [
    "RELATION_TYPES",
    "DataRelation",
    "ResearchRelation",
    "DataRelations",
]
