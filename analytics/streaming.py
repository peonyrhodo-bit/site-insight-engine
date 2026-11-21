"""Bounded streaming aggregates for complete persisted YouTube history.

The accumulator retains counts, online numeric statistics, bounded frequency
maps, and a small evidence sample. It never retains every source row.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite
from typing import Any, Mapping


def _number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        result = float(str(value).replace(",", "").strip())
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _bounded_increment(counter: Counter[str], value: Any, *, cap: int = 1000) -> None:
    if value is None:
        return
    label = str(value).strip()[:160]
    if not label:
        return
    counter[label] += 1
    if len(counter) > cap * 2:
        for key, _ in counter.most_common()[cap:]:
            del counter[key]


class _OnlineStats:
    def __init__(self) -> None:
        self.count = 0
        self.total = 0.0
        self.minimum: float | None = None
        self.maximum: float | None = None

    def add(self, value: Any) -> None:
        number = _number(value)
        if number is None:
            return
        self.count += 1
        self.total += number
        self.minimum = number if self.minimum is None else min(self.minimum, number)
        self.maximum = number if self.maximum is None else max(self.maximum, number)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "sum": round(self.total, 3),
            "average": round(self.total / self.count, 3) if self.count else None,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


class StreamingYouTubeAnalytics:
    """Accumulate complete-history metrics with bounded process memory."""

    METRICS = ("views", "viewCount", "view_count", "likes", "likeCount",
               "comments", "commentCount", "views_per_hour", "engagement")

    def __init__(self, *, sample_limit: int = 100) -> None:
        self.sample_limit = max(1, int(sample_limit))
        self.video_count = 0
        self.snapshot_count = 0
        self.channel_counts: Counter[str] = Counter()
        self.topic_counts: Counter[str] = Counter()
        self.topic_view_stats: dict[str, _OnlineStats] = {}
        self.video_stats = {name: _OnlineStats() for name in ("views",)}
        self.snapshot_stats = {name: _OnlineStats() for name in self.METRICS}
        self.top_videos: list[dict[str, Any]] = []
        self.latest_snapshot_at: str | None = None
        self.earliest_snapshot_at: str | None = None

    def add_video(self, row: Mapping[str, Any]) -> None:
        self.video_count += 1
        channel = row.get("channel_id") or row.get("channelId")
        _bounded_increment(self.channel_counts, channel)
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        topics: set[str] = set()
        for field in ("topic", "category", "niche", "thematic_direction"):
            value = metadata.get(field)
            if value is not None and str(value).strip():
                topics.add(str(value).strip()[:160])
        for field in ("topics", "categories", "niches", "thematic_directions", "tags"):
            values = metadata.get(field)
            if isinstance(values, (list, tuple, set)):
                for value in values:
                    if value is not None and str(value).strip():
                        topics.add(str(value).strip()[:160])
        for topic in topics:
            _bounded_increment(self.topic_counts, topic)
        metrics = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
        views = next((_number(row.get(key)) for key in ("views", "viewCount", "view_count") if _number(row.get(key)) is not None), None)
        if views is None:
            views = next((_number(metrics.get(key)) for key in ("views", "viewCount", "view_count") if _number(metrics.get(key)) is not None), None)
        self.video_stats["views"].add(views)
        if views is not None:
            for topic in topics:
                if topic not in self.topic_view_stats and len(self.topic_view_stats) >= 1000:
                    continue
                self.topic_view_stats.setdefault(topic, _OnlineStats()).add(views)
        candidate = {
            "video_id": str(row.get("video_id") or ""),
            "title": str(row.get("title") or "")[:300],
            "channel_id": str(channel or ""),
            "views": views,
            "source_table": "videos",
        }
        if candidate["video_id"]:
            self.top_videos.append(candidate)
            self.top_videos.sort(key=lambda item: item.get("views") or -1, reverse=True)
            del self.top_videos[self.sample_limit:]

    def add_snapshot(self, row: Mapping[str, Any]) -> None:
        self.snapshot_count += 1
        data = row.get("data_json") if isinstance(row.get("data_json"), Mapping) else {}
        statistics = data.get("statistics") if isinstance(data.get("statistics"), Mapping) else {}
        radar = data.get("_radar") if isinstance(data.get("_radar"), Mapping) else {}
        for metric in self.METRICS:
            value = statistics.get(metric, radar.get(metric, data.get(metric)))
            self.snapshot_stats[metric].add(value)
        captured = str(row.get("created_at") or "")
        if captured:
            self.latest_snapshot_at = max(captured, self.latest_snapshot_at or captured)
            self.earliest_snapshot_at = min(captured, self.earliest_snapshot_at or captured)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "complete",
            "scope": "all_persisted_rows_scanned",
            "video_count": self.video_count,
            "snapshot_count": self.snapshot_count,
            "unique_channel_count_observed": len(self.channel_counts),
            "top_channels": [{"channel_id": key, "videos": count} for key, count in self.channel_counts.most_common(100)],
            "top_topics": [{"topic": key, "videos": count} for key, count in self.topic_counts.most_common(100)],
            "video_metrics": {key: value.to_dict() for key, value in self.video_stats.items()},
            "topic_view_metrics": [
                {"topic": topic, "videos_with_views": stats.count, "average_views": stats.to_dict()["average"]}
                for topic, stats in sorted(self.topic_view_stats.items(), key=lambda item: item[1].count, reverse=True)[:100]
            ],
            "snapshot_metrics": {key: value.to_dict() for key, value in self.snapshot_stats.items()},
            "top_videos": list(self.top_videos),
            "earliest_snapshot_at": self.earliest_snapshot_at,
            "latest_snapshot_at": self.latest_snapshot_at,
            "retention": "aggregates_and_top_evidence_only; source_rows_remain_in_supabase",
        }
