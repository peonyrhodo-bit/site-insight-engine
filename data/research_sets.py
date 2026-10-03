"""
Research DATA layer for AI Director.

This module describes a research set as a first-class DATA object.

A research set answers:
- what was researched;
- why it was researched;
- which queries were used;
- which languages/regions were involved;
- which videos were found;
- which snapshots were collected;
- what data is already available;
- what data is missing;
- what can be reused;
- how complete/fresh the research currently is.

This module does NOT:
- decide strategy;
- score opportunities;
- call YouTube/MCP;
- call an AI provider;
- persist data to Supabase/SQLite.

Those responsibilities belong to other layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from data.youtube import (
    YouTubeQuery,
    YouTubeSnapshot,
    YouTubeVideo,
    YouTubeDataRegistry,
    age_seconds,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_text(value: Any) -> str | None:
    text = _clean_text(value)
    return text or None


def _normalize_id(value: Any) -> int | str:
    if isinstance(value, bool):
        return str(value)

    if isinstance(value, int):
        return value

    text = _clean_text(value)

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


def _normalize_strings(
    values: Iterable[Any] | None,
) -> list[str]:
    if values is None:
        return []

    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = _clean_text(value)

        if text and text not in seen:
            seen.add(text)
            result.append(text)

    return result


# ---------------------------------------------------------------------------
# Research status
# ---------------------------------------------------------------------------


RESEARCH_STATUSES = {
    "planned",
    "active",
    "collecting",
    "partial",
    "complete",
    "stale",
    "cancelled",
    "archived",
}


def _normalize_status(value: str | None) -> str:
    status = _clean_text(value).lower() or "planned"

    if status not in RESEARCH_STATUSES:
        raise ValueError(
            f"unsupported research status: {status}"
        )

    return status


# ---------------------------------------------------------------------------
# Research Set
# ---------------------------------------------------------------------------


@dataclass
class ResearchSet:
    """
    First-class representation of one Director research operation.

    A ResearchSet is DATA, not a decision.

    It records the evidence collection context that later Analytics and
    Director layers can interpret.
    """

    research_id: int | str

    # Human-readable purpose.
    name: str = ""
    objective: str = ""

    # Collection scope.
    language: str | None = None
    region: str | None = None
    languages: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)

    # Research inputs and outputs.
    query_ids: list[int | str] = field(default_factory=list)
    video_ids: list[int | str] = field(default_factory=list)
    snapshot_ids: list[int | str] = field(default_factory=list)

    # Explicit data state.
    gathered_data: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)

    # Reuse / provenance.
    reusable_video_ids: list[int | str] = field(
        default_factory=list
    )
    reused_video_ids: list[int | str] = field(
        default_factory=list
    )
    source: str | None = None

    # Lifecycle.
    status: str = "planned"
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None

    # Optional research configuration/context.
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    # Optional expected fields for completeness tracking.
    expected_data: list[str] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        self.research_id = _normalize_id(
            self.research_id
        )

        self.name = _clean_text(self.name)
        self.objective = _clean_text(self.objective)

        self.language = _optional_text(self.language)
        self.region = _optional_text(self.region)

        self.languages = _normalize_strings(
            self.languages
        )
        self.regions = _normalize_strings(
            self.regions
        )

        if self.language and self.language not in self.languages:
            self.languages.insert(0, self.language)

        if self.region and self.region not in self.regions:
            self.regions.insert(0, self.region)

        self.query_ids = _normalize_ids(
            self.query_ids
        )
        self.video_ids = _normalize_ids(
            self.video_ids
        )
        self.snapshot_ids = _normalize_ids(
            self.snapshot_ids
        )

        self.gathered_data = _normalize_strings(
            self.gathered_data
        )
        self.missing_data = _normalize_strings(
            self.missing_data
        )

        self.reusable_video_ids = _normalize_ids(
            self.reusable_video_ids
        )
        self.reused_video_ids = _normalize_ids(
            self.reused_video_ids
        )

        self.source = _optional_text(self.source)

        self.status = _normalize_status(
            self.status
        )

        self.created_at = (
            _optional_text(self.created_at)
            or _utc_now()
        )

        self.updated_at = (
            _optional_text(self.updated_at)
            or self.created_at
        )

        self.completed_at = _optional_text(
            self.completed_at
        )

        self.metadata = dict(self.metadata or {})

        self.expected_data = _normalize_strings(
            self.expected_data
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def touch(self) -> None:
        self.updated_at = _utc_now()

    def activate(self) -> None:
        self.status = "active"
        self.touch()

    def start_collection(self) -> None:
        self.status = "collecting"
        self.touch()

    def mark_partial(self) -> None:
        self.status = "partial"
        self.touch()

    def mark_complete(self) -> None:
        self.status = "complete"
        self.completed_at = _utc_now()
        self.touch()

    def mark_stale(self) -> None:
        self.status = "stale"
        self.touch()

    def cancel(self) -> None:
        self.status = "cancelled"
        self.touch()

    def archive(self) -> None:
        self.status = "archived"
        self.touch()

    # ------------------------------------------------------------------
    # Query management
    # ------------------------------------------------------------------

    def add_query(
        self,
        query: YouTubeQuery | int | str,
    ) -> int | str:
        query_id = (
            query.query_id
            if isinstance(query, YouTubeQuery)
            else _normalize_id(query)
        )

        if query_id not in self.query_ids:
            self.query_ids.append(query_id)
            self.touch()

        return query_id

    def add_queries(
        self,
        queries: Iterable[
            YouTubeQuery | int | str
        ],
    ) -> list[int | str]:
        added: list[int | str] = []

        for query in queries:
            added.append(
                self.add_query(query)
            )

        return added

    def has_query(
        self,
        query_id: int | str,
    ) -> bool:
        return _normalize_id(query_id) in self.query_ids

    # ------------------------------------------------------------------
    # Video management
    # ------------------------------------------------------------------

    def add_video(
        self,
        video: YouTubeVideo | int | str,
        *,
        reusable: bool = False,
        reused: bool = False,
    ) -> int | str:
        video_id = (
            video.video_id
            if isinstance(video, YouTubeVideo)
            else _normalize_id(video)
        )

        if video_id not in self.video_ids:
            self.video_ids.append(video_id)

        if reusable and video_id not in self.reusable_video_ids:
            self.reusable_video_ids.append(video_id)

        if reused and video_id not in self.reused_video_ids:
            self.reused_video_ids.append(video_id)

        self.touch()

        return video_id

    def add_videos(
        self,
        videos: Iterable[
            YouTubeVideo | int | str
        ],
        *,
        reusable: bool = False,
        reused: bool = False,
    ) -> list[int | str]:
        added: list[int | str] = []

        for video in videos:
            added.append(
                self.add_video(
                    video,
                    reusable=reusable,
                    reused=reused,
                )
            )

        return added

    def has_video(
        self,
        video_id: int | str,
    ) -> bool:
        return _normalize_id(video_id) in self.video_ids

    # ------------------------------------------------------------------
    # Snapshot management
    # ------------------------------------------------------------------

    def add_snapshot(
        self,
        snapshot: YouTubeSnapshot | int | str,
    ) -> int | str:
        snapshot_id = (
            snapshot.snapshot_id
            if isinstance(snapshot, YouTubeSnapshot)
            else _normalize_id(snapshot)
        )

        if snapshot_id not in self.snapshot_ids:
            self.snapshot_ids.append(
                snapshot_id
            )
            self.touch()

        return snapshot_id

    def add_snapshots(
        self,
        snapshots: Iterable[
            YouTubeSnapshot | int | str
        ],
    ) -> list[int | str]:
        added: list[int | str] = []

        for snapshot in snapshots:
            added.append(
                self.add_snapshot(snapshot)
            )

        return added

    def has_snapshot(
        self,
        snapshot_id: int | str,
    ) -> bool:
        return (
            _normalize_id(snapshot_id)
            in self.snapshot_ids
        )

    # ------------------------------------------------------------------
    # Data completeness
    # ------------------------------------------------------------------

    def expect_data(
        self,
        *fields: str,
    ) -> None:
        for field_name in fields:
            value = _clean_text(field_name)

            if value and value not in self.expected_data:
                self.expected_data.append(value)

        self.touch()

    def mark_data_gathered(
        self,
        *fields: str,
    ) -> None:
        changed = False

        for field_name in fields:
            value = _clean_text(field_name)

            if not value:
                continue

            if value not in self.gathered_data:
                self.gathered_data.append(value)
                changed = True

            if value in self.missing_data:
                self.missing_data.remove(value)
                changed = True

        if changed:
            self.touch()

    def mark_data_missing(
        self,
        *fields: str,
    ) -> None:
        changed = False

        for field_name in fields:
            value = _clean_text(field_name)

            if not value:
                continue

            if value not in self.missing_data:
                self.missing_data.append(value)
                changed = True

        if changed:
            self.touch()

    def has_data(
        self,
        field_name: str,
    ) -> bool:
        return (
            _clean_text(field_name)
            in self.gathered_data
        )

    def is_missing(
        self,
        field_name: str,
    ) -> bool:
        return (
            _clean_text(field_name)
            in self.missing_data
        )

    def missing_expected_data(self) -> list[str]:
        """
        Return expected fields that have not been gathered.
        """
        return [
            field_name
            for field_name in self.expected_data
            if field_name not in self.gathered_data
        ]

    @property
    def completeness(self) -> float:
        """
        Return a simple DATA completeness ratio.

        If no expected fields are defined:
        - 1.0 when some useful data exists;
        - 0.0 when the research is empty.
        """
        expected = set(self.expected_data)

        if expected:
            gathered = set(self.gathered_data)
            return len(
                expected & gathered
            ) / len(expected)

        useful_data = (
            bool(self.query_ids)
            or bool(self.video_ids)
            or bool(self.snapshot_ids)
        )

        return 1.0 if useful_data else 0.0

    # ------------------------------------------------------------------
    # Freshness
    # ------------------------------------------------------------------

    def latest_snapshot_age_seconds(
        self,
        registry: YouTubeDataRegistry,
    ) -> float | None:
        """
        Return age of the newest research snapshot.
        """
        latest: YouTubeSnapshot | None = None

        for snapshot_id in self.snapshot_ids:
            snapshot = registry.get_snapshot(
                snapshot_id
            )

            if snapshot is None:
                continue

            if latest is None:
                latest = snapshot
                continue

            if (
                snapshot.captured_at
                and latest.captured_at
                and snapshot.captured_at > latest.captured_at
            ):
                latest = snapshot

        if latest is None:
            return None

        return age_seconds(
            latest.captured_at
        )

    def is_fresh(
        self,
        registry: YouTubeDataRegistry,
        *,
        max_age_seconds: float,
    ) -> bool:
        age = self.latest_snapshot_age_seconds(
            registry
        )

        if age is None:
            return False

        return age <= max_age_seconds

    # ------------------------------------------------------------------
    # Reuse
    # ------------------------------------------------------------------

    def mark_reusable(
        self,
        video_id: int | str,
    ) -> None:
        normalized = _normalize_id(video_id)

        if normalized not in self.video_ids:
            self.video_ids.append(normalized)

        if normalized not in self.reusable_video_ids:
            self.reusable_video_ids.append(
                normalized
            )

        self.touch()

    def mark_reused(
        self,
        video_id: int | str,
    ) -> None:
        normalized = _normalize_id(video_id)

        if normalized not in self.video_ids:
            self.video_ids.append(normalized)

        if normalized not in self.reused_video_ids:
            self.reused_video_ids.append(
                normalized
            )

        self.touch()

    def can_reuse_video(
        self,
        video_id: int | str,
    ) -> bool:
        normalized = _normalize_id(video_id)

        return normalized in (
            self.reusable_video_ids
        )

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def video_count(self) -> int:
        return len(self.video_ids)

    @property
    def query_count(self) -> int:
        return len(self.query_ids)

    @property
    def snapshot_count(self) -> int:
        return len(self.snapshot_ids)

    def summary(self) -> dict[str, Any]:
        return {
            "research_id": self.research_id,
            "name": self.name,
            "objective": self.objective,
            "status": self.status,
            "query_count": self.query_count,
            "video_count": self.video_count,
            "snapshot_count": self.snapshot_count,
            "gathered_data": list(self.gathered_data),
            "missing_data": list(self.missing_data),
            "expected_data": list(self.expected_data),
            "missing_expected_data": (
                self.missing_expected_data()
            ),
            "completeness": self.completeness,
            "reusable_video_count": len(
                self.reusable_video_ids
            ),
            "reused_video_count": len(
                self.reused_video_ids
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_id": self.research_id,
            "name": self.name,
            "objective": self.objective,
            "language": self.language,
            "region": self.region,
            "languages": list(self.languages),
            "regions": list(self.regions),
            "query_ids": list(self.query_ids),
            "video_ids": list(self.video_ids),
            "snapshot_ids": list(self.snapshot_ids),
            "gathered_data": list(self.gathered_data),
            "missing_data": list(self.missing_data),
            "reusable_video_ids": list(
                self.reusable_video_ids
            ),
            "reused_video_ids": list(
                self.reused_video_ids
            ),
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "metadata": dict(self.metadata),
            "expected_data": list(
                self.expected_data
            ),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "ResearchSet":
        return cls(
            research_id=data.get("research_id"),
            name=data.get("name", ""),
            objective=data.get("objective", ""),
            language=data.get("language"),
            region=data.get("region"),
            languages=data.get("languages") or [],
            regions=data.get("regions") or [],
            query_ids=data.get("query_ids") or [],
            video_ids=data.get("video_ids") or [],
            snapshot_ids=data.get("snapshot_ids") or [],
            gathered_data=data.get(
                "gathered_data"
            ) or [],
            missing_data=data.get(
                "missing_data"
            ) or [],
            reusable_video_ids=data.get(
                "reusable_video_ids"
            ) or [],
            reused_video_ids=data.get(
                "reused_video_ids"
            ) or [],
            source=data.get("source"),
            status=data.get(
                "status",
                "planned",
            ),
            created_at=data.get(
                "created_at"
            ),
            updated_at=data.get(
                "updated_at"
            ),
            completed_at=data.get(
                "completed_at"
            ),
            metadata=data.get(
                "metadata"
            ) or {},
            expected_data=data.get(
                "expected_data"
            ) or [],
        )


# ---------------------------------------------------------------------------
# Research Set Manager
# ---------------------------------------------------------------------------


class ResearchSetManager:
    """
    Registry/manager for ResearchSet objects.

    Persistence is intentionally outside this class.
    """

    def __init__(
        self,
        registry: YouTubeDataRegistry | None = None,
    ) -> None:
        self._sets: dict[
            int | str,
            ResearchSet,
        ] = {}

        self.registry = registry

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        research_id: int | str,
        *,
        name: str = "",
        objective: str = "",
        language: str | None = None,
        region: str | None = None,
        languages: Iterable[str] | None = None,
        regions: Iterable[str] | None = None,
        source: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        expected_data: Iterable[str] | None = None,
        status: str = "planned",
    ) -> ResearchSet:
        normalized = _normalize_id(
            research_id
        )

        existing = self._sets.get(normalized)

        if existing is not None:
            return existing

        research = ResearchSet(
            research_id=normalized,
            name=name,
            objective=objective,
            language=language,
            region=region,
            languages=list(languages or []),
            regions=list(regions or []),
            source=source,
            metadata=dict(metadata or {}),
            expected_data=list(
                expected_data or []
            ),
            status=status,
        )

        self._sets[normalized] = research

        return research

    def add(
        self,
        research: ResearchSet,
    ) -> ResearchSet:
        if not isinstance(
            research,
            ResearchSet,
        ):
            raise TypeError(
                "research must be ResearchSet"
            )

        existing = self._sets.get(
            research.research_id
        )

        if existing is not None:
            return existing

        self._sets[
            research.research_id
        ] = research

        return research

    def upsert(
        self,
        research: ResearchSet,
    ) -> ResearchSet:
        if not isinstance(
            research,
            ResearchSet,
        ):
            raise TypeError(
                "research must be ResearchSet"
            )

        self._sets[
            research.research_id
        ] = research

        return research

    def get(
        self,
        research_id: int | str,
    ) -> ResearchSet | None:
        return self._sets.get(
            _normalize_id(research_id)
        )

    def require(
        self,
        research_id: int | str,
    ) -> ResearchSet:
        research = self.get(
            research_id
        )

        if research is None:
            raise KeyError(
                f"research set not found: {research_id}"
            )

        return research

    def remove(
        self,
        research_id: int | str,
    ) -> ResearchSet | None:
        return self._sets.pop(
            _normalize_id(research_id),
            None,
        )

    def all(self) -> list[ResearchSet]:
        return list(
            self._sets.values()
        )

    def count(self) -> int:
        return len(self._sets)

    # ------------------------------------------------------------------
    # Research lookup
    # ------------------------------------------------------------------

    def find_by_video(
        self,
        video_id: int | str,
    ) -> list[ResearchSet]:
        normalized = _normalize_id(video_id)

        return [
            research
            for research in self._sets.values()
            if normalized in research.video_ids
        ]

    def find_by_query(
        self,
        query_id: int | str,
    ) -> list[ResearchSet]:
        normalized = _normalize_id(query_id)

        return [
            research
            for research in self._sets.values()
            if normalized in research.query_ids
        ]

    def find_by_status(
        self,
        status: str,
    ) -> list[ResearchSet]:
        normalized = _normalize_status(
            status
        )

        return [
            research
            for research in self._sets.values()
            if research.status == normalized
        ]

    def find_by_language(
        self,
        language: str,
    ) -> list[ResearchSet]:
        normalized = _clean_text(
            language
        ).lower()

        return [
            research
            for research in self._sets.values()
            if normalized in {
                value.lower()
                for value in research.languages
            }
        ]

    def find_reusable_video(
        self,
        video_id: int | str,
    ) -> list[ResearchSet]:
        normalized = _normalize_id(
            video_id
        )

        return [
            research
            for research in self._sets.values()
            if normalized
            in research.reusable_video_ids
        ]

    # ------------------------------------------------------------------
    # Research/data operations
    # ------------------------------------------------------------------

    def attach_query(
        self,
        research_id: int | str,
        query: YouTubeQuery | int | str,
    ) -> int | str:
        research = self.require(
            research_id
        )

        return research.add_query(
            query
        )

    def attach_video(
        self,
        research_id: int | str,
        video: YouTubeVideo | int | str,
        *,
        reusable: bool = False,
        reused: bool = False,
    ) -> int | str:
        research = self.require(
            research_id
        )

        return research.add_video(
            video,
            reusable=reusable,
            reused=reused,
        )

    def attach_snapshot(
        self,
        research_id: int | str,
        snapshot: YouTubeSnapshot | int | str,
    ) -> int | str:
        research = self.require(
            research_id
        )

        return research.add_snapshot(
            snapshot
        )

    def mark_gathered(
        self,
        research_id: int | str,
        *fields: str,
    ) -> ResearchSet:
        research = self.require(
            research_id
        )

        research.mark_data_gathered(
            *fields
        )

        return research

    def mark_missing(
        self,
        research_id: int | str,
        *fields: str,
    ) -> ResearchSet:
        research = self.require(
            research_id
        )

        research.mark_data_missing(
            *fields
        )

        return research

    def mark_reusable(
        self,
        research_id: int | str,
        video_id: int | str,
    ) -> ResearchSet:
        research = self.require(
            research_id
        )

        research.mark_reusable(
            video_id
        )

        return research

    def mark_reused(
        self,
        research_id: int | str,
        video_id: int | str,
    ) -> ResearchSet:
        research = self.require(
            research_id
        )

        research.mark_reused(
            video_id
        )

        return research

    # ------------------------------------------------------------------
    # Completeness / freshness
    # ------------------------------------------------------------------

    def completeness(
        self,
        research_id: int | str,
    ) -> float:
        return self.require(
            research_id
        ).completeness

    def is_complete(
        self,
        research_id: int | str,
    ) -> bool:
        research = self.require(
            research_id
        )

        return (
            research.completeness >= 1.0
            and research.status
            in {
                "complete",
                "partial",
            }
        )

    def is_fresh(
        self,
        research_id: int | str,
        *,
        max_age_seconds: float,
    ) -> bool:
        research = self.require(
            research_id
        )

        if self.registry is None:
            return False

        return research.is_fresh(
            self.registry,
            max_age_seconds=max_age_seconds,
        )

    def stale_research(
        self,
        *,
        max_age_seconds: float,
    ) -> list[ResearchSet]:
        if self.registry is None:
            return []

        return [
            research
            for research in self._sets.values()
            if not research.is_fresh(
                self.registry,
                max_age_seconds=max_age_seconds,
            )
        ]

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def summary(
        self,
        research_id: int | str,
    ) -> dict[str, Any]:
        return self.require(
            research_id
        ).summary()

    def summaries(self) -> list[dict[str, Any]]:
        return [
            research.summary()
            for research in self._sets.values()
        ]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_sets": [
                research.to_dict()
                for research in self._sets.values()
            ]
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        registry: YouTubeDataRegistry | None = None,
    ) -> "ResearchSetManager":
        manager = cls(
            registry=registry
        )

        for item in (
            data.get(
                "research_sets",
                [],
            )
            or []
        ):
            manager.add(
                ResearchSet.from_dict(item)
            )

        return manager

    def clear(self) -> None:
        self._sets.clear()


__all__ = [
    "ResearchSet",
    "ResearchSetManager",
    "RESEARCH_STATUSES",
]
