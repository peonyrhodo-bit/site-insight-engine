"""Canonical DATA entities for channels, niches, and their historical snapshots.

This module is deliberately storage-agnostic. It defines the durable
identities and time-varying observations that the Director will need to
evaluate YouTube niche growth and competition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple, set)) else []


@dataclass
class YouTubeChannel:
    channel_id: str
    title: str = ""
    description: str | None = None
    custom_url: str | None = None
    country: str | None = None
    published_at: str | None = None
    video_count: int | None = None
    subscriber_count: int | None = None
    view_count: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.channel_id = _text(self.channel_id)
        if not self.channel_id:
            raise ValueError("channel_id is required")
        self.title = _text(self.title)
        self.data = dict(self.data or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "title": self.title,
            "description": self.description,
            "custom_url": self.custom_url,
            "country": self.country,
            "published_at": self.published_at,
            "video_count": self.video_count,
            "subscriber_count": self.subscriber_count,
            "view_count": self.view_count,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "YouTubeChannel":
        return cls(
            channel_id=value.get("channel_id"),
            title=value.get("title", ""),
            description=value.get("description"),
            custom_url=value.get("custom_url"),
            country=value.get("country"),
            published_at=value.get("published_at"),
            video_count=value.get("video_count"),
            subscriber_count=value.get("subscriber_count"),
            view_count=value.get("view_count"),
            data=value.get("data") or value.get("data_json") or {},
        )


@dataclass
class ChannelSnapshot:
    channel_id: str
    captured_at: str | None = None
    subscriber_count: int | None = None
    video_count: int | None = None
    view_count: int | None = None
    new_video_count: int | None = None
    subscriber_growth: int | None = None
    view_growth: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.channel_id = _text(self.channel_id)
        if not self.channel_id:
            raise ValueError("channel_id is required")
        self.data = dict(self.data or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "captured_at": self.captured_at,
            "subscriber_count": self.subscriber_count,
            "video_count": self.video_count,
            "view_count": self.view_count,
            "new_video_count": self.new_video_count,
            "subscriber_growth": self.subscriber_growth,
            "view_growth": self.view_growth,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChannelSnapshot":
        return cls(
            channel_id=value.get("channel_id"),
            captured_at=value.get("captured_at"),
            subscriber_count=value.get("subscriber_count"),
            video_count=value.get("video_count"),
            view_count=value.get("view_count"),
            new_video_count=value.get("new_video_count"),
            subscriber_growth=value.get("subscriber_growth"),
            view_growth=value.get("view_growth"),
            data=value.get("data") or value.get("data_json") or {},
        )


@dataclass
class YouTubeNiche:
    niche_id: str
    name: str
    description: str | None = None
    aliases: list[str] = field(default_factory=list)
    language: str | None = None
    region: str | None = None
    status: str = "active"
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.niche_id = _text(self.niche_id)
        self.name = _text(self.name)
        if not self.niche_id:
            raise ValueError("niche_id is required")
        if not self.name:
            raise ValueError("name is required")
        self.aliases = [_text(item) for item in _list(self.aliases) if _text(item)]
        self.data = dict(self.data or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "niche_id": self.niche_id,
            "name": self.name,
            "description": self.description,
            "aliases": list(self.aliases),
            "language": self.language,
            "region": self.region,
            "status": self.status,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "YouTubeNiche":
        return cls(
            niche_id=value.get("niche_id"),
            name=value.get("name", ""),
            description=value.get("description"),
            aliases=value.get("aliases") or [],
            language=value.get("language"),
            region=value.get("region"),
            status=value.get("status", "active"),
            data=value.get("data") or value.get("data_json") or {},
        )


@dataclass
class NicheSnapshot:
    niche_id: str
    captured_at: str | None = None
    video_count: int | None = None
    channel_count: int | None = None
    median_views: float | None = None
    average_views: float | None = None
    growth_rate: float | None = None
    new_video_count: int | None = None
    new_channel_count: int | None = None
    top_channel_share: float | None = None
    competition_score: float | None = None
    opportunity_score: float | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.niche_id = _text(self.niche_id)
        if not self.niche_id:
            raise ValueError("niche_id is required")
        self.data = dict(self.data or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "niche_id": self.niche_id,
            "captured_at": self.captured_at,
            "video_count": self.video_count,
            "channel_count": self.channel_count,
            "median_views": self.median_views,
            "average_views": self.average_views,
            "growth_rate": self.growth_rate,
            "new_video_count": self.new_video_count,
            "new_channel_count": self.new_channel_count,
            "top_channel_share": self.top_channel_share,
            "competition_score": self.competition_score,
            "opportunity_score": self.opportunity_score,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NicheSnapshot":
        return cls(
            niche_id=value.get("niche_id"),
            captured_at=value.get("captured_at"),
            video_count=value.get("video_count"),
            channel_count=value.get("channel_count"),
            median_views=value.get("median_views"),
            average_views=value.get("average_views"),
            growth_rate=value.get("growth_rate"),
            new_video_count=value.get("new_video_count"),
            new_channel_count=value.get("new_channel_count"),
            top_channel_share=value.get("top_channel_share"),
            competition_score=value.get("competition_score"),
            opportunity_score=value.get("opportunity_score"),
            data=value.get("data") or value.get("data_json") or {},
        )


__all__ = [
    "YouTubeChannel",
    "ChannelSnapshot",
    "YouTubeNiche",
    "NicheSnapshot",
]
