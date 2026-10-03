"""
YouTube DATA layer for AI Director.

Responsibilities
----------------
This module is the canonical in-memory data model for YouTube research data.

It does NOT:
- call YouTube API directly;
- call MCP directly;
- make analytical conclusions;
- make Director decisions;
- persist data to Supabase/SQLite.

Those responsibilities belong to other layers.

This module provides:
- normalized YouTube query representation;
- normalized video identity and metadata;
- immutable-style research snapshots;
- metrics normalization;
- provenance/source information;
- freshness information;
- safe serialization/deserialization;
- reusable in-memory registry;
- lookup helpers required by ResearchSet and DataRelations.

Backward compatibility
----------------------
The original public classes and methods are preserved:
- YouTubeQuery
- YouTubeVideo
- YouTubeSnapshot
- YouTubeDataRegistry
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_optional_text(value: Any) -> str | None:
    text = _clean_text(value)
    return text or None


def _normalize_identifier(value: Any) -> int | str:
    """
    Preserve integer identifiers while normalizing string identifiers.

    Existing code accepts int | str, so this function deliberately does not
    force everything into strings.
    """
    if isinstance(value, bool):
        return str(value)

    if isinstance(value, int):
        return value

    text = _clean_text(value)

    if not text:
        raise ValueError("identifier must not be empty")

    return text


def _normalize_id_set(values: Iterable[Any] | None) -> list[int | str]:
    if values is None:
        return []

    result: list[int | str] = []
    seen: set[int | str] = set()

    for value in values:
        identifier = _normalize_identifier(value)

        if identifier not in seen:
            seen.add(identifier)
            result.append(identifier)

    return result


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}

    return dict(value)


def _normalize_metric_value(value: Any) -> Any:
    """
    Normalize common YouTube metric representations without destroying
    information we do not understand.

    Examples:
        "12,345" -> 12345
        "12345"  -> 12345
        12345.0  -> 12345
        None     -> None

    Unknown/non-numeric values are preserved as strings/objects.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value

    if isinstance(value, str):
        text = value.strip().replace(",", "").replace(" ", "")

        if not text:
            return None

        try:
            return int(text)
        except ValueError:
            pass

        try:
            return float(text)
        except ValueError:
            return value

    return value


def normalize_metrics(
    metrics: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Normalize a metrics mapping while preserving unknown metrics.

    Known numeric YouTube metrics are normalized automatically.
    Unknown fields remain available for future MCP/API fields.
    """
    if metrics is None:
        return {}

    result: dict[str, Any] = {}

    for key, value in metrics.items():
        normalized_key = _clean_text(key)

        if not normalized_key:
            continue

        result[normalized_key] = _normalize_metric_value(value)

    return result


def normalize_youtube_url(
    youtube_id: str | None,
) -> str | None:
    """
    Build the canonical YouTube watch URL from a video ID.

    Existing metadata URLs are intentionally not overwritten elsewhere.
    """
    value = _clean_optional_text(youtube_id)

    if not value:
        return None

    return f"https://www.youtube.com/watch?v={value}"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    text = value.strip()

    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def age_seconds(
    captured_at: str | None,
    now: datetime | None = None,
) -> float | None:
    """
    Return snapshot age in seconds.

    None is returned when captured_at cannot be parsed.
    """
    captured = _parse_datetime(captured_at)

    if captured is None:
        return None

    current = now or datetime.now(timezone.utc)

    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    return max(0.0, (current - captured).total_seconds())


# ---------------------------------------------------------------------------
# YouTube Query
# ---------------------------------------------------------------------------


@dataclass
class YouTubeQuery:
    """
    Represents one YouTube search query used during research.

    A query is research input, not an analytical conclusion.
    """

    query_id: int | str
    text: str = ""
    language: str | None = None
    region: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Research/provenance fields.
    created_at: str | None = None
    source: str | None = None
    status: str = "planned"

    def __post_init__(self) -> None:
        self.query_id = _normalize_identifier(self.query_id)
        self.text = _clean_text(self.text)
        self.language = _clean_optional_text(self.language)
        self.region = _clean_optional_text(self.region)
        self.metadata = _copy_mapping(self.metadata)
        self.created_at = (
            _clean_optional_text(self.created_at)
            or _utc_now()
        )
        self.source = _clean_optional_text(self.source)
        self.status = _clean_text(self.status) or "planned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "text": self.text,
            "language": self.language,
            "region": self.region,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "source": self.source,
            "status": self.status,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "YouTubeQuery":
        return cls(
            query_id=data.get("query_id"),
            text=data.get("text", ""),
            language=data.get("language"),
            region=data.get("region"),
            metadata=data.get("metadata") or {},
            created_at=data.get("created_at"),
            source=data.get("source"),
            status=data.get("status", "planned"),
        )


# ---------------------------------------------------------------------------
# YouTube Video
# ---------------------------------------------------------------------------


@dataclass
class YouTubeVideo:
    """
    Represents one canonical YouTube video reference.

    This object stores identity and relatively stable metadata.
    Time-varying metrics belong to YouTubeSnapshot.
    """

    video_id: int | str
    youtube_id: str = ""
    title: str = ""
    channel_id: str | None = None
    published_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Additional stable identity/provenance data.
    channel_title: str | None = None
    description: str | None = None
    url: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        self.video_id = _normalize_identifier(self.video_id)
        self.youtube_id = _clean_text(self.youtube_id)
        self.title = _clean_text(self.title)
        self.channel_id = _clean_optional_text(self.channel_id)
        self.channel_title = _clean_optional_text(self.channel_title)
        self.description = _clean_optional_text(self.description)
        self.published_at = _clean_optional_text(self.published_at)
        self.metadata = _copy_mapping(self.metadata)

        if self.url is None and self.youtube_id:
            self.url = normalize_youtube_url(self.youtube_id)
        else:
            self.url = _clean_optional_text(self.url)

        self.first_seen_at = _clean_optional_text(
            self.first_seen_at
        )
        self.last_seen_at = _clean_optional_text(
            self.last_seen_at
        )
        self.source = _clean_optional_text(self.source)

    @property
    def canonical_id(self) -> str:
        """
        Canonical YouTube identity.

        youtube_id is preferred because it is the external YouTube identity.
        Internal video_id is used as fallback.
        """
        if self.youtube_id:
            return self.youtube_id

        return str(self.video_id)

    def touch(self, captured_at: str | None = None) -> None:
        """
        Update first_seen/last_seen timestamps.

        This is intentionally data bookkeeping, not persistence.
        """
        timestamp = captured_at or _utc_now()

        if self.first_seen_at is None:
            self.first_seen_at = timestamp

        self.last_seen_at = timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "youtube_id": self.youtube_id,
            "title": self.title,
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "description": self.description,
            "published_at": self.published_at,
            "url": self.url,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "source": self.source,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "YouTubeVideo":
        return cls(
            video_id=data.get("video_id"),
            youtube_id=data.get("youtube_id", ""),
            title=data.get("title", ""),
            channel_id=data.get("channel_id"),
            published_at=data.get("published_at"),
            metadata=data.get("metadata") or {},
            channel_title=data.get("channel_title"),
            description=data.get("description"),
            url=data.get("url"),
            first_seen_at=data.get("first_seen_at"),
            last_seen_at=data.get("last_seen_at"),
            source=data.get("source"),
        )


# ---------------------------------------------------------------------------
# YouTube Snapshot
# ---------------------------------------------------------------------------


@dataclass
class YouTubeSnapshot:
    """
    One point-in-time observation of a YouTube video.

    Snapshots are the basis for future trend/dynamics calculations.

    A snapshot never replaces another snapshot.
    """

    snapshot_id: int | str
    video_id: int | str
    captured_at: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Provenance and research context.
    source: str | None = None
    research_id: int | str | None = None
    query_ids: list[int | str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.snapshot_id = _normalize_identifier(
            self.snapshot_id
        )
        self.video_id = _normalize_identifier(
            self.video_id
        )
        self.captured_at = (
            _clean_optional_text(self.captured_at)
            or _utc_now()
        )
        self.metrics = normalize_metrics(self.metrics)
        self.metadata = _copy_mapping(self.metadata)
        self.source = _clean_optional_text(self.source)

        if self.research_id is not None:
            self.research_id = _normalize_identifier(
                self.research_id
            )

        self.query_ids = _normalize_id_set(
            self.query_ids
        )

    def metric(
        self,
        name: str,
        default: Any = None,
    ) -> Any:
        return self.metrics.get(name, default)

    def has_metric(self, name: str) -> bool:
        return name in self.metrics

    def is_fresh(
        self,
        max_age_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        age = age_seconds(
            self.captured_at,
            now=now,
        )

        if age is None:
            return False

        return age <= max_age_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "video_id": self.video_id,
            "captured_at": self.captured_at,
            "metrics": dict(self.metrics),
            "metadata": dict(self.metadata),
            "source": self.source,
            "research_id": self.research_id,
            "query_ids": list(self.query_ids),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "YouTubeSnapshot":
        return cls(
            snapshot_id=data.get("snapshot_id"),
            video_id=data.get("video_id"),
            captured_at=data.get("captured_at"),
            metrics=data.get("metrics") or {},
            metadata=data.get("metadata") or {},
            source=data.get("source"),
            research_id=data.get("research_id"),
            query_ids=data.get("query_ids") or [],
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class YouTubeDataRegistry:
    """
    Lightweight canonical registry for the current DATA processing context.

    Persistent storage intentionally remains outside this module.

    The registry provides:
    - deduplication;
    - lookup by internal ID;
    - lookup by YouTube ID;
    - snapshot history;
    - metric history;
    - reusable data discovery;
    - safe serialization.
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

        self._videos_by_youtube_id: dict[
            str,
            int | str,
        ] = {}

        self._snapshots: dict[
            int | str,
            YouTubeSnapshot,
        ] = {}

        self._snapshots_by_video: dict[
            int | str,
            list[int | str],
        ] = {}

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def add_query(
        self,
        query: YouTubeQuery,
    ) -> YouTubeQuery:
        if not isinstance(query, YouTubeQuery):
            raise TypeError(
                "query must be YouTubeQuery"
            )

        existing = self._queries.get(
            query.query_id
        )

        if existing is not None:
            return existing

        self._queries[query.query_id] = query
        return query

    def get_query(
        self,
        query_id: int | str,
    ) -> YouTubeQuery | None:
        return self._queries.get(query_id)

    def queries(self) -> list[YouTubeQuery]:
        return list(self._queries.values())

    # ------------------------------------------------------------------
    # Videos
    # ------------------------------------------------------------------

    def add_video(
        self,
        video: YouTubeVideo,
    ) -> YouTubeVideo:
        if not isinstance(video, YouTubeVideo):
            raise TypeError(
                "video must be YouTubeVideo"
            )

        # Prefer external YouTube identity when available.
        if video.youtube_id:
            existing_id = self._videos_by_youtube_id.get(
                video.youtube_id
            )

            if existing_id is not None:
                existing = self._videos[existing_id]

                # Fill missing stable fields without replacing
                # an already known value.
                self._merge_video_metadata(
                    existing,
                    video,
                )

                return existing

        existing = self._videos.get(
            video.video_id
        )

        if existing is not None:
            self._merge_video_metadata(
                existing,
                video,
            )

            if existing.youtube_id:
                self._videos_by_youtube_id[
                    existing.youtube_id
                ] = existing.video_id

            return existing

        self._videos[video.video_id] = video

        if video.youtube_id:
            self._videos_by_youtube_id[
                video.youtube_id
            ] = video.video_id

        return video

    @staticmethod
    def _merge_video_metadata(
        target: YouTubeVideo,
        incoming: YouTubeVideo,
    ) -> None:
        """
        Merge missing data from incoming into existing video.

        Existing non-empty values are preserved.
        """
        if not target.youtube_id and incoming.youtube_id:
            target.youtube_id = incoming.youtube_id

        if not target.title and incoming.title:
            target.title = incoming.title

        if not target.channel_id and incoming.channel_id:
            target.channel_id = incoming.channel_id

        if not target.channel_title and incoming.channel_title:
            target.channel_title = incoming.channel_title

        if not target.description and incoming.description:
            target.description = incoming.description

        if not target.published_at and incoming.published_at:
            target.published_at = incoming.published_at

        if not target.url and incoming.url:
            target.url = incoming.url

        if not target.first_seen_at and incoming.first_seen_at:
            target.first_seen_at = incoming.first_seen_at

        if incoming.last_seen_at:
            target.last_seen_at = incoming.last_seen_at

        if not target.source and incoming.source:
            target.source = incoming.source

        target.metadata.update(incoming.metadata)

    def get_video(
        self,
        video_id: int | str,
    ) -> YouTubeVideo | None:
        return self._videos.get(video_id)

    def get_video_by_youtube_id(
        self,
        youtube_id: str,
    ) -> YouTubeVideo | None:
        internal_id = self._videos_by_youtube_id.get(
            _clean_text(youtube_id)
        )

        if internal_id is None:
            return None

        return self._videos.get(internal_id)

    def find_videos(
        self,
        *,
        channel_id: str | None = None,
        text: str | None = None,
    ) -> list[YouTubeVideo]:
        """
        Lightweight reusable search over already collected data.

        This does not query YouTube.
        """
        channel = _clean_optional_text(channel_id)
        needle = _clean_optional_text(text)

        result: list[YouTubeVideo] = []

        for video in self._videos.values():
            if channel and video.channel_id != channel:
                continue

            if needle:
                haystack = (
                    f"{video.title} "
                    f"{video.description or ''}"
                ).lower()

                if needle.lower() not in haystack:
                    continue

            result.append(video)

        return result

    def videos(self) -> list[YouTubeVideo]:
        return list(self._videos.values())

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def add_snapshot(
        self,
        snapshot: YouTubeSnapshot,
    ) -> YouTubeSnapshot:
        if not isinstance(snapshot, YouTubeSnapshot):
            raise TypeError(
                "snapshot must be YouTubeSnapshot"
            )

        existing = self._snapshots.get(
            snapshot.snapshot_id
        )

        if existing is not None:
            return existing

        self._snapshots[
            snapshot.snapshot_id
        ] = snapshot

        self._snapshots_by_video.setdefault(
            snapshot.video_id,
            [],
        ).append(
            snapshot.snapshot_id
        )

        return snapshot

    def get_snapshot(
        self,
        snapshot_id: int | str,
    ) -> YouTubeSnapshot | None:
        return self._snapshots.get(snapshot_id)

    def snapshots(self) -> list[YouTubeSnapshot]:
        return list(self._snapshots.values())

    def snapshots_for_video(
        self,
        video_id: int | str,
    ) -> list[YouTubeSnapshot]:
        snapshot_ids = self._snapshots_by_video.get(
            video_id,
            [],
        )

        snapshots = [
            self._snapshots[snapshot_id]
            for snapshot_id in snapshot_ids
            if snapshot_id in self._snapshots
        ]

        return sorted(
            snapshots,
            key=lambda item: item.captured_at or "",
        )

    def latest_snapshot(
        self,
        video_id: int | str,
    ) -> YouTubeSnapshot | None:
        snapshots = self.snapshots_for_video(video_id)

        if not snapshots:
            return None

        return snapshots[-1]

    def metric_history(
        self,
        video_id: int | str,
        metric_name: str,
    ) -> list[tuple[str | None, Any]]:
        """
        Return chronological metric observations for a video.
        """
        result: list[
            tuple[str | None, Any]
        ] = []

        for snapshot in self.snapshots_for_video(
            video_id
        ):
            result.append(
                (
                    snapshot.captured_at,
                    snapshot.metric(metric_name),
                )
            )

        return result

    # ------------------------------------------------------------------
    # Reuse / provenance
    # ------------------------------------------------------------------

    def find_reusable_video(
        self,
        youtube_id: str,
    ) -> YouTubeVideo | None:
        """
        Return an already-known video by external YouTube ID.

        This is the primary hook for avoiding duplicate data collection.
        """
        return self.get_video_by_youtube_id(
            youtube_id
        )

    def has_snapshot_for_video(
        self,
        video_id: int | str,
        *,
        max_age_seconds: float | None = None,
    ) -> bool:
        snapshot = self.latest_snapshot(video_id)

        if snapshot is None:
            return False

        if max_age_seconds is None:
            return True

        return snapshot.is_fresh(
            max_age_seconds
        )

    def research_snapshot_ids(
        self,
        research_id: int | str,
    ) -> list[int | str]:
        """
        Find snapshots explicitly associated with a research ID.
        """
        normalized = _normalize_identifier(
            research_id
        )

        return [
            snapshot.snapshot_id
            for snapshot in self._snapshots.values()
            if snapshot.research_id == normalized
        ]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "queries": [
                item.to_dict()
                for item in self.queries()
            ],
            "videos": [
                item.to_dict()
                for item in self.videos()
            ],
            "snapshots": [
                item.to_dict()
                for item in self.snapshots()
            ],
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "YouTubeDataRegistry":
        registry = cls()

        for item in data.get("queries", []) or []:
            registry.add_query(
                YouTubeQuery.from_dict(item)
            )

        for item in data.get("videos", []) or []:
            registry.add_video(
                YouTubeVideo.from_dict(item)
            )

        for item in data.get("snapshots", []) or []:
            registry.add_snapshot(
                YouTubeSnapshot.from_dict(item)
            )

        return registry

    # ------------------------------------------------------------------
    # Counts / inspection
    # ------------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        return {
            "queries": len(self._queries),
            "videos": len(self._videos),
            "snapshots": len(self._snapshots),
        }

    def clear(self) -> None:
        self._queries.clear()
        self._videos.clear()
        self._videos_by_youtube_id.clear()
        self._snapshots.clear()
        self._snapshots_by_video.clear()


# ---------------------------------------------------------------------------
# Normalization helpers for future MCP adapters
# ---------------------------------------------------------------------------


def video_from_mapping(
    data: Mapping[str, Any],
    *,
    video_id: int | str | None = None,
    source: str | None = None,
) -> YouTubeVideo:
    """
    Convert a raw/normalized mapping into YouTubeVideo.

    This intentionally accepts multiple common field names so the DATA layer
    is not coupled to one exact MCP response shape.
    """
    external_id = (
        data.get("youtube_id")
        or data.get("video_id")
        or data.get("id")
    )

    if external_id is None:
        raise ValueError(
            "video mapping does not contain a video identifier"
        )

    internal_id = (
        video_id
        if video_id is not None
        else data.get("internal_video_id")
        or external_id
    )

    youtube_id = str(
        data.get("youtube_id")
        or data.get("videoId")
        or data.get("video_id")
        or data.get("id")
        or ""
    )

    return YouTubeVideo(
        video_id=internal_id,
        youtube_id=youtube_id,
        title=(
            data.get("title")
            or data.get("video_title")
            or ""
        ),
        channel_id=(
            data.get("channel_id")
            or data.get("channelId")
        ),
        channel_title=(
            data.get("channel_title")
            or data.get("channelTitle")
        ),
        description=data.get("description"),
        published_at=(
            data.get("published_at")
            or data.get("publishedAt")
        ),
        url=(
            data.get("url")
            or data.get("video_url")
            or normalize_youtube_url(youtube_id)
        ),
        metadata=dict(data),
        source=source,
    )


def snapshot_from_mapping(
    data: Mapping[str, Any],
    *,
    snapshot_id: int | str,
    video_id: int | str,
    research_id: int | str | None = None,
    query_ids: Iterable[int | str] | None = None,
    source: str | None = None,
) -> YouTubeSnapshot:
    """
    Convert a raw/normalized metrics mapping into a snapshot.

    Common YouTube metrics are accepted directly. If a nested "metrics"
    mapping exists it is preferred.
    """
    raw_metrics = data.get("metrics")

    if isinstance(raw_metrics, Mapping):
        metrics = dict(raw_metrics)
    else:
        excluded = {
            "snapshot_id",
            "video_id",
            "captured_at",
            "created_at",
            "updated_at",
            "research_id",
            "query_ids",
            "metadata",
            "source",
        }

        metrics = {
            key: value
            for key, value in data.items()
            if key not in excluded
        }

    return YouTubeSnapshot(
        snapshot_id=snapshot_id,
        video_id=video_id,
        captured_at=(
            data.get("captured_at")
            or data.get("collected_at")
            or data.get("created_at")
        ),
        metrics=metrics,
        metadata=data.get("metadata") or {},
        source=source or data.get("source"),
        research_id=research_id,
        query_ids=query_ids or data.get("query_ids") or [],
    )


__all__ = [
    "YouTubeQuery",
    "YouTubeVideo",
    "YouTubeSnapshot",
    "YouTubeDataRegistry",
    "normalize_metrics",
    "normalize_youtube_url",
    "age_seconds",
    "video_from_mapping",
    "snapshot_from_mapping",
]
