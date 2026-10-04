# analytics/analytics.py
"""
Analytical layer for the Director system.

Responsibilities:
- normalize video/research data;
- calculate comparable metrics;
- aggregate research results;
- compare videos and groups;
- detect basic performance signals;
- prepare structured analytical input for Director;
- remain independent from FastAPI/server transport.

This module intentionally does NOT:
- call YouTube/MCP;
- call OpenRouter/AI;
- make final Director decisions;
- mutate application state.

The module accepts ordinary Python dictionaries/lists so it can work
with MCP results, database records, snapshots, research sets and
future analytics sources.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import log1p
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_LIMIT = 100
EPSILON = 1e-9

VIEW_WEIGHT = 0.35
LIKE_WEIGHT = 0.15
COMMENT_WEIGHT = 0.10
ENGAGEMENT_WEIGHT = 0.20
RECENCY_WEIGHT = 0.10
MOMENTUM_WEIGHT = 0.10

DEFAULT_SIGNAL_THRESHOLDS = {
    "strong": 0.70,
    "positive": 0.50,
    "neutral": 0.35,
    "weak": 0.20,
}


# ============================================================
# DATACLASSES
# ============================================================

@dataclass(slots=True)
class VideoMetrics:
    video_id: str | None = None
    views: float = 0.0
    likes: float = 0.0
    comments: float = 0.0
    duration_seconds: float = 0.0

    like_rate: float = 0.0
    comment_rate: float = 0.0
    engagement_rate: float = 0.0

    views_per_hour: float = 0.0
    momentum: float = 0.0
    recency_score: float = 0.0

    performance_score: float = 0.0
    confidence: float = 0.0

    @property
    def interaction_count(self) -> float:
        return self.likes + self.comments


@dataclass(slots=True)
class TrendSignal:
    direction: str
    strength: float
    change_ratio: float
    sample_size: int
    explanation: str


@dataclass(slots=True)
class AggregateMetrics:
    count: int = 0

    total_views: float = 0.0
    average_views: float = 0.0
    median_views: float = 0.0

    average_likes: float = 0.0
    average_comments: float = 0.0

    average_like_rate: float = 0.0
    average_comment_rate: float = 0.0
    average_engagement_rate: float = 0.0

    average_views_per_hour: float = 0.0
    average_performance_score: float = 0.0

    top_video_id: str | None = None
    top_video_score: float = 0.0

    unique_channels: int = 0
    unique_topics: int = 0


@dataclass(slots=True)
class ResearchAnalytics:
    research_id: str | None = None

    metrics: AggregateMetrics = field(
        default_factory=AggregateMetrics
    )

    top_videos: list[dict[str, Any]] = field(
        default_factory=list
    )

    topic_distribution: dict[str, int] = field(
        default_factory=dict
    )

    channel_distribution: dict[str, int] = field(
        default_factory=dict
    )

    trend: TrendSignal | None = None

    signals: list[str] = field(
        default_factory=list
    )

    confidence: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        if value is None:
            return default

        number = float(value)

        if number != number:
            return default

        return number
    except (TypeError, ValueError):
        return default


def _safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(
    value: Any,
) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _first(
    data: Mapping[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]

    return default


def _clamp(
    value: float,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    return max(
        minimum,
        min(maximum, value),
    )


def _mean(
    values: Iterable[float],
) -> float:
    values = list(values)

    if not values:
        return 0.0

    return float(mean(values))


def _median(
    values: Iterable[float],
) -> float:
    values = list(values)

    if not values:
        return 0.0

    return float(median(values))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(
    value: Any,
) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )

        return value

    text = _text(value)

    if not text:
        return None

    try:
        normalized = text.replace(
            "Z",
            "+00:00",
        )

        parsed = datetime.fromisoformat(
            normalized
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed

    except ValueError:
        return None


# ============================================================
# VIDEO FIELD EXTRACTION
# ============================================================

def get_video_id(
    video: Mapping[str, Any],
) -> str | None:
    value = _first(
        video,
        "video_id",
        "id",
        "youtube_id",
        "videoId",
    )

    if isinstance(value, Mapping):
        value = _first(
            value,
            "videoId",
            "id",
        )

    value = _text(value)

    return value or None


def get_views(
    video: Mapping[str, Any],
) -> float:
    return max(
        0.0,
        _safe_float(
            _first(
                video,
                "views",
                "view_count",
                "viewCount",
                "statistics.views",
                "stats.views",
            )
        ),
    )


def get_likes(
    video: Mapping[str, Any],
) -> float:
    return max(
        0.0,
        _safe_float(
            _first(
                video,
                "likes",
                "like_count",
                "likeCount",
                "statistics.likes",
                "stats.likes",
            )
        ),
    )


def get_comments(
    video: Mapping[str, Any],
) -> float:
    return max(
        0.0,
        _safe_float(
            _first(
                video,
                "comments",
                "comment_count",
                "commentCount",
                "statistics.comments",
                "stats.comments",
            )
        ),
    )


def get_duration_seconds(
    video: Mapping[str, Any],
) -> float:
    value = _first(
        video,
        "duration_seconds",
        "duration",
        "durationSeconds",
    )

    if isinstance(value, (int, float)):
        return max(
            0.0,
            float(value),
        )

    text = _text(value)

    if not text:
        return 0.0

    # ISO-8601 YouTube duration, e.g. PT12M34S
    if text.startswith("PT"):
        try:
            import re

            match = re.fullmatch(
                r"PT"
                r"(?:(?P<hours>\d+)H)?"
                r"(?:(?P<minutes>\d+)M)?"
                r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?",
                text,
            )

            if match:
                hours = _safe_float(
                    match.group("hours")
                )

                minutes = _safe_float(
                    match.group("minutes")
                )

                seconds = _safe_float(
                    match.group("seconds")
                )

                return (
                    hours * 3600
                    + minutes * 60
                    + seconds
                )

        except Exception:
            return 0.0

    # HH:MM:SS / MM:SS
    if ":" in text:
        try:
            parts = [
                _safe_float(part)
                for part in text.split(":")
            ]

            if len(parts) == 3:
                return (
                    parts[0] * 3600
                    + parts[1] * 60
                    + parts[2]
                )

            if len(parts) == 2:
                return (
                    parts[0] * 60
                    + parts[1]
                )

        except Exception:
            return 0.0

    return 0.0


def get_published_at(
    video: Mapping[str, Any],
) -> datetime | None:
    return _parse_datetime(
        _first(
            video,
            "published_at",
            "publishedAt",
            "created_at",
            "createdAt",
        )
    )


def get_channel(
    video: Mapping[str, Any],
) -> str:
    value = _first(
        video,
        "channel_title",
        "channelTitle",
        "channel_name",
        "channel",
        "author",
    )

    return _text(value)


def get_topics(
    video: Mapping[str, Any],
) -> list[str]:
    raw = _first(
        video,
        "topics",
        "topic",
        "tags",
        "keywords",
    )

    if raw is None:
        return []

    if isinstance(raw, str):
        parts = [
            item.strip()
            for item in raw.split(",")
        ]

        return [
            item
            for item in parts
            if item
        ]

    if isinstance(raw, Sequence):
        return [
            _text(item)
            for item in raw
            if _text(item)
        ]

    return []


# ============================================================
# RECENCY
# ============================================================

def calculate_recency_score(
    published_at: datetime | None,
    *,
    now: datetime | None = None,
    half_life_hours: float = 72.0,
) -> float:
    if published_at is None:
        return 0.0

    now = now or _now()

    age_hours = max(
        0.0,
        (
            now - published_at
        ).total_seconds()
        / 3600.0,
    )

    if half_life_hours <= 0:
        return 0.0

    # Exponential decay.
    score = 0.5 ** (
        age_hours / half_life_hours
    )

    return _clamp(score)


# ============================================================
# ENGAGEMENT
# ============================================================

def calculate_like_rate(
    views: float,
    likes: float,
) -> float:
    if views <= 0:
        return 0.0

    return _clamp(
        likes / views
    )


def calculate_comment_rate(
    views: float,
    comments: float,
) -> float:
    if views <= 0:
        return 0.0

    return _clamp(
        comments / views
    )


def calculate_engagement_rate(
    views: float,
    likes: float,
    comments: float,
) -> float:
    if views <= 0:
        return 0.0

    return _clamp(
        (
            likes + comments
        ) / views
    )


# ============================================================
# NORMALIZATION
# ============================================================

def _normalize_log_score(
    value: float,
    reference: float,
) -> float:
    if value <= 0:
        return 0.0

    if reference <= 0:
        return 0.0

    return _clamp(
        log1p(value)
        / log1p(reference)
    )


def _percentile_score(
    value: float,
    values: Sequence[float],
) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)

    if len(ordered) == 1:
        return 1.0

    less_or_equal = sum(
        1
        for item in ordered
        if item <= value
    )

    return _clamp(
        (
            less_or_equal - 1
        )
        / (
            len(ordered) - 1
        )
    )


# ============================================================
# VIDEO METRICS
# ============================================================

def calculate_video_metrics(
    video: Mapping[str, Any],
    *,
    reference_views: float | None = None,
    reference_engagement: float | None = None,
    now: datetime | None = None,
) -> VideoMetrics:
    views = get_views(video)
    likes = get_likes(video)
    comments = get_comments(video)

    duration = get_duration_seconds(
        video
    )

    published_at = get_published_at(
        video
    )

    like_rate = calculate_like_rate(
        views,
        likes,
    )

    comment_rate = calculate_comment_rate(
        views,
        comments,
    )

    engagement_rate = (
        calculate_engagement_rate(
            views,
            likes,
            comments,
        )
    )

    recency_score = (
        calculate_recency_score(
            published_at,
            now=now,
        )
    )

    reference_views = (
        reference_views
        if reference_views is not None
        else views
    )

    reference_engagement = (
        reference_engagement
        if reference_engagement is not None
        else engagement_rate
    )

    view_score = _normalize_log_score(
        views,
        reference_views,
    )

    engagement_score = _normalize_log_score(
        engagement_rate,
        reference_engagement,
    )

    # The score is deliberately a composite signal,
    # not a "truth" metric.
    performance_score = _clamp(
        VIEW_WEIGHT * view_score
        + LIKE_WEIGHT * _clamp(
            like_rate * 100
        )
        + COMMENT_WEIGHT * _clamp(
            comment_rate * 1000
        )
        + ENGAGEMENT_WEIGHT * engagement_score
        + RECENCY_WEIGHT * recency_score
    )

    hours_since_publish = None

    if published_at is not None:
        current = now or _now()

        hours_since_publish = max(
            1.0,
            (
                current - published_at
            ).total_seconds()
            / 3600.0,
        )

    if hours_since_publish:
        views_per_hour = (
            views
            / hours_since_publish
        )
    else:
        views_per_hour = 0.0

    momentum = _clamp(
        _normalize_log_score(
            views_per_hour,
            max(
                views_per_hour,
                1.0,
            ),
        )
    )

    confidence = _clamp(
        min(
            1.0,
            0.25
            + (
                0.25
                if views > 0
                else 0
            )
            + (
                0.20
                if published_at
                else 0
            )
            + (
                0.15
                if likes > 0
                else 0
            )
            + (
                0.15
                if comments > 0
                else 0
            ),
        )
    )

    return VideoMetrics(
        video_id=get_video_id(video),
        views=views,
        likes=likes,
        comments=comments,
        duration_seconds=duration,
        like_rate=like_rate,
        comment_rate=comment_rate,
        engagement_rate=engagement_rate,
        views_per_hour=views_per_hour,
        momentum=momentum,
        recency_score=recency_score,
        performance_score=performance_score,
        confidence=confidence,
    )


# ============================================================
# COLLECTION NORMALIZATION
# ============================================================

def normalize_video(
    video: Mapping[str, Any],
    *,
    metrics: VideoMetrics | None = None,
) -> dict[str, Any]:
    result = dict(video)

    calculated = (
        metrics
        or calculate_video_metrics(video)
    )

    result["video_id"] = (
        calculated.video_id
    )

    result["analytics"] = asdict(
        calculated
    )

    return result


def normalize_videos(
    videos: Iterable[
        Mapping[str, Any]
    ],
) -> list[dict[str, Any]]:
    videos = [
        video
        for video in videos
        if isinstance(
            video,
            Mapping,
        )
    ]

    if not videos:
        return []

    views = [
        get_views(video)
        for video in videos
    ]

    engagements = [
        calculate_engagement_rate(
            get_views(video),
            get_likes(video),
            get_comments(video),
        )
        for video in videos
    ]

    reference_views = max(
        max(views, default=0.0),
        1.0,
    )

    reference_engagement = max(
        max(engagements, default=0.0),
        EPSILON,
    )

    normalized = []

    for video in videos:
        metrics = calculate_video_metrics(
            video,
            reference_views=reference_views,
            reference_engagement=reference_engagement,
        )

        normalized.append(
            normalize_video(
                video,
                metrics=metrics,
            )
        )

    return normalized


# ============================================================
# AGGREGATION
# ============================================================

def aggregate_metrics(
    videos: Iterable[
        Mapping[str, Any]
    ],
) -> AggregateMetrics:
    videos = [
        video
        for video in videos
        if isinstance(
            video,
            Mapping,
        )
    ]

    if not videos:
        return AggregateMetrics()

    normalized = normalize_videos(
        videos
    )

    metrics = [
        item["analytics"]
        for item in normalized
    ]

    view_values = [
        _safe_float(
            item.get("views")
        )
        for item in metrics
    ]

    like_values = [
        _safe_float(
            item.get("likes")
        )
        for item in metrics
    ]

    comment_values = [
        _safe_float(
            item.get("comments")
        )
        for item in metrics
    ]

    like_rates = [
        _safe_float(
            item.get("like_rate")
        )
        for item in metrics
    ]

    comment_rates = [
        _safe_float(
            item.get("comment_rate")
        )
        for item in metrics
    ]

    engagement_rates = [
        _safe_float(
            item.get("engagement_rate")
        )
        for item in metrics
    ]

    views_per_hour = [
        _safe_float(
            item.get("views_per_hour")
        )
        for item in metrics
    ]

    performance_scores = [
        _safe_float(
            item.get("performance_score")
        )
        for item in metrics
    ]

    channels = {
        get_channel(video)
        for video in videos
        if get_channel(video)
    }

    topics = {
        topic
        for video in videos
        for topic in get_topics(video)
    }

    top_item = max(
        normalized,
        key=lambda item: _safe_float(
            item["analytics"].get(
                "performance_score"
            )
        ),
    )

    top_metrics = top_item[
        "analytics"
    ]

    return AggregateMetrics(
        count=len(videos),
        total_views=sum(
            view_values
        ),
        average_views=_mean(
            view_values
        ),
        median_views=_median(
            view_values
        ),
        average_likes=_mean(
            like_values
        ),
        average_comments=_mean(
            comment_values
        ),
        average_like_rate=_mean(
            like_rates
        ),
        average_comment_rate=_mean(
            comment_rates
        ),
        average_engagement_rate=_mean(
            engagement_rates
        ),
        average_views_per_hour=_mean(
            views_per_hour
        ),
        average_performance_score=_mean(
            performance_scores
        ),
        top_video_id=(
            get_video_id(top_item)
        ),
        top_video_score=_safe_float(
            top_metrics.get(
                "performance_score"
            )
        ),
        unique_channels=len(
            channels
        ),
        unique_topics=len(
            topics
        ),
    )


# ============================================================
# DISTRIBUTIONS
# ============================================================

def topic_distribution(
    videos: Iterable[
        Mapping[str, Any]
    ],
) -> dict[str, int]:
    counter: Counter[str] = Counter()

    for video in videos:
        for topic in get_topics(video):
            counter[topic] += 1

    return dict(
        counter.most_common()
    )


def channel_distribution(
    videos: Iterable[
        Mapping[str, Any]
    ],
) -> dict[str, int]:
    counter: Counter[str] = Counter()

    for video in videos:
        channel = get_channel(video)

        if channel:
            counter[channel] += 1

    return dict(
        counter.most_common()
    )


# ============================================================
# COMPARISON
# ============================================================

def compare_videos(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any]:
    left_metrics = calculate_video_metrics(
        left
    )

    right_metrics = calculate_video_metrics(
        right
    )

    def ratio(
        left_value: float,
        right_value: float,
    ) -> float:
        if right_value == 0:
            if left_value == 0:
                return 0.0

            return float("inf")

        return (
            left_value
            / right_value
        )

    return {
        "left_video_id": (
            left_metrics.video_id
        ),
        "right_video_id": (
            right_metrics.video_id
        ),
        "views": {
            "left": left_metrics.views,
            "right": right_metrics.views,
            "ratio": ratio(
                left_metrics.views,
                right_metrics.views,
            ),
        },
        "engagement_rate": {
            "left": (
                left_metrics.engagement_rate
            ),
            "right": (
                right_metrics.engagement_rate
            ),
            "difference": (
                left_metrics.engagement_rate
                - right_metrics.engagement_rate
            ),
        },
        "performance_score": {
            "left": (
                left_metrics.performance_score
            ),
            "right": (
                right_metrics.performance_score
            ),
            "difference": (
                left_metrics.performance_score
                - right_metrics.performance_score
            ),
        },
        "winner": (
            left_metrics.video_id
            if (
                left_metrics.performance_score
                > right_metrics.performance_score
            )
            else right_metrics.video_id
            if (
                right_metrics.performance_score
                > left_metrics.performance_score
            )
            else None
        ),
    }


# ============================================================
# TOP VIDEOS
# ============================================================

def rank_videos(
    videos: Iterable[
        Mapping[str, Any]
    ],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    normalized = normalize_videos(
        videos
    )

    ranked = sorted(
        normalized,
        key=lambda video: (
            _safe_float(
                video["analytics"].get(
                    "performance_score"
                )
            ),
            get_views(video),
            get_published_at(video)
            or datetime.min.replace(
                tzinfo=timezone.utc
            ),
        ),
        reverse=True,
    )

    return ranked[
        : max(
            1,
            min(
                int(limit),
                DEFAULT_LIMIT,
            ),
        )
    ]


# ============================================================
# SIGNAL DETECTION
# ============================================================

def detect_signals(
    videos: Sequence[
        Mapping[str, Any]
    ],
) -> list[str]:
    if not videos:
        return [
            "insufficient_data"
        ]

    metrics = aggregate_metrics(
        videos
    )

    signals: list[str] = []

    if metrics.count < 3:
        signals.append(
            "small_sample"
        )

    if (
        metrics.average_engagement_rate
        >= 0.05
    ):
        signals.append(
            "high_engagement"
        )

    if (
        metrics.average_engagement_rate
        <= 0.01
    ):
        signals.append(
            "low_engagement"
        )

    if (
        metrics.average_views_per_hour
        > 0
    ):
        signals.append(
            "measurable_momentum"
        )

    if (
        metrics.average_performance_score
        >= DEFAULT_SIGNAL_THRESHOLDS[
            "strong"
        ]
    ):
        signals.append(
            "strong_performance"
        )
    elif (
        metrics.average_performance_score
        >= DEFAULT_SIGNAL_THRESHOLDS[
            "positive"
        ]
    ):
        signals.append(
            "positive_performance"
        )
    elif (
        metrics.average_performance_score
        <= DEFAULT_SIGNAL_THRESHOLDS[
            "weak"
        ]
    ):
        signals.append(
            "weak_performance"
        )

    channels = channel_distribution(
        videos
    )

    if len(channels) == 1:
        signals.append(
            "single_channel_dependency"
        )

    if len(channels) >= 10:
        signals.append(
            "broad_creator_distribution"
        )

    return signals


# ============================================================
# RESEARCH-LEVEL ANALYTICS
# ============================================================

def analyze_research(
    videos: Iterable[
        Mapping[str, Any]
    ],
    *,
    research_id: str | None = None,
    previous_videos: Iterable[
        Mapping[str, Any]
    ]
    | None = None,
    metadata: Mapping[str, Any]
    | None = None,
) -> ResearchAnalytics:
    videos = [
        video
        for video in videos
        if isinstance(
            video,
            Mapping,
        )
    ]

    normalized = normalize_videos(
        videos
    )

    metrics = aggregate_metrics(
        normalized
    )

    ranked = rank_videos(
        normalized,
        limit=10,
    )

    topics = topic_distribution(
        normalized
    )

    channels = channel_distribution(
        normalized
    )

    trend = None

    if previous_videos is not None:
        trend = compare_collections(
            current=videos,
            previous=list(
                previous_videos
            ),
        )

    signals = detect_signals(
        normalized
    )

    confidence = calculate_analysis_confidence(
        videos=normalized,
        metrics=metrics,
    )

    return ResearchAnalytics(
        research_id=research_id,
        metrics=metrics,
        top_videos=ranked,
        topic_distribution=topics,
        channel_distribution=channels,
        trend=trend,
        signals=signals,
        confidence=confidence,
        metadata=dict(
            metadata or {}
        ),
    )


# ============================================================
# COLLECTION COMPARISON / TRENDS INPUT
# ============================================================

def compare_collections(
    *,
    current: Sequence[
        Mapping[str, Any]
    ],
    previous: Sequence[
        Mapping[str, Any]
    ],
) -> TrendSignal:
    current_metrics = aggregate_metrics(
        current
    )

    previous_metrics = aggregate_metrics(
        previous
    )

    current_value = (
        current_metrics.average_performance_score
    )

    previous_value = (
        previous_metrics.average_performance_score
    )

    if previous_value <= EPSILON:
        if current_value <= EPSILON:
            change_ratio = 0.0
        else:
            change_ratio = 1.0
    else:
        change_ratio = (
            current_value
            - previous_value
        ) / previous_value

    strength = _clamp(
        abs(change_ratio)
    )

    if change_ratio >= 0.20:
        direction = "strong_up"
        explanation = (
            "Performance increased materially "
            "relative to the previous sample."
        )
    elif change_ratio >= 0.05:
        direction = "up"
        explanation = (
            "Performance is improving "
            "relative to the previous sample."
        )
    elif change_ratio <= -0.20:
        direction = "strong_down"
        explanation = (
            "Performance decreased materially "
            "relative to the previous sample."
        )
    elif change_ratio <= -0.05:
        direction = "down"
        explanation = (
            "Performance is weakening "
            "relative to the previous sample."
        )
    else:
        direction = "stable"
        explanation = (
            "Performance is broadly stable "
            "relative to the previous sample."
        )

    return TrendSignal(
        direction=direction,
        strength=strength,
        change_ratio=change_ratio,
        sample_size=(
            current_metrics.count
            + previous_metrics.count
        ),
        explanation=explanation,
    )


# ============================================================
# CONFIDENCE
# ============================================================

def calculate_analysis_confidence(
    *,
    videos: Sequence[
        Mapping[str, Any]
    ],
    metrics: AggregateMetrics | None = None,
) -> float:
    if not videos:
        return 0.0

    metrics = (
        metrics
        or aggregate_metrics(videos)
    )

    sample_score = _clamp(
        len(videos) / 30.0
    )

    channel_score = _clamp(
        metrics.unique_channels
        / 10.0
    )

    topic_score = _clamp(
        metrics.unique_topics
        / 10.0
    )

    # Per-video completeness is the mean of the four availability
    # signals; the overall score is the mean across videos.
    # (Previously a list of per-video lists was passed to _mean,
    # which expects numeric values.)
    per_video_completeness = [
        _mean(
            [
                1.0
                if get_video_id(video)
                else 0.0,
                1.0
                if get_views(video) > 0
                else 0.0,
                1.0
                if get_published_at(video)
                else 0.0,
                1.0
                if (
                    get_likes(video) > 0
                    or get_comments(video) > 0
                )
                else 0.0,
            ]
        )
        for video in videos
    ]

    data_completeness = _mean(
        per_video_completeness
    )

    return _clamp(
        0.35 * sample_score
        + 0.20 * channel_score
        + 0.15 * topic_score
        + 0.30 * data_completeness
    )


# ============================================================
# DIRECTOR INPUT
# ============================================================

def prepare_for_director(
    analysis: ResearchAnalytics
    | Mapping[str, Any],
) -> dict[str, Any]:
    """
    Convert analytics into a stable, compact structure
    suitable for Director/AI decision making.
    """

    if isinstance(
        analysis,
        ResearchAnalytics,
    ):
        data = asdict(
            analysis
        )
    else:
        data = dict(
            analysis
        )

    metrics = data.get(
        "metrics",
        {},
    )

    if isinstance(
        metrics,
        AggregateMetrics,
    ):
        metrics = asdict(
            metrics
        )

    trend = data.get(
        "trend"
    )

    if isinstance(
        trend,
        TrendSignal,
    ):
        trend = asdict(
            trend
        )

    return {
        "research_id": data.get(
            "research_id"
        ),
        "sample": {
            "videos": metrics.get(
                "count",
                0,
            ),
            "channels": metrics.get(
                "unique_channels",
                0,
            ),
            "topics": metrics.get(
                "unique_topics",
                0,
            ),
        },
        "performance": {
            "total_views": metrics.get(
                "total_views",
                0,
            ),
            "average_views": metrics.get(
                "average_views",
                0,
            ),
            "median_views": metrics.get(
                "median_views",
                0,
            ),
            "engagement_rate": metrics.get(
                "average_engagement_rate",
                0,
            ),
            "views_per_hour": metrics.get(
                "average_views_per_hour",
                0,
            ),
            "score": metrics.get(
                "average_performance_score",
                0,
            ),
        },
        "top_videos": data.get(
            "top_videos",
            [],
        )[:10],
        "topics": data.get(
            "topic_distribution",
            {},
        ),
        "channels": data.get(
            "channel_distribution",
            {},
        ),
        "trend": trend,
        "signals": data.get(
            "signals",
            [],
        ),
        "confidence": data.get(
            "confidence",
            0.0,
        ),
        "metadata": data.get(
            "metadata",
            {},
        ),
    }


# ============================================================
# SERIALIZATION
# ============================================================

def analytics_to_dict(
    analytics: ResearchAnalytics,
) -> dict[str, Any]:
    return asdict(
        analytics
    )


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "AggregateMetrics",
    "ResearchAnalytics",
    "TrendSignal",
    "VideoMetrics",
    "aggregate_metrics",
    "analytics_to_dict",
    "analyze_research",
    "calculate_analysis_confidence",
    "calculate_comment_rate",
    "calculate_engagement_rate",
    "calculate_like_rate",
    "calculate_recency_score",
    "calculate_video_metrics",
    "channel_distribution",
    "compare_collections",
    "compare_videos",
    "detect_signals",
    "get_channel",
    "get_comments",
    "get_duration_seconds",
    "get_likes",
    "get_published_at",
    "get_topics",
    "get_video_id",
    "get_views",
    "normalize_video",
    "normalize_videos",
    "prepare_for_director",
    "rank_videos",
    "topic_distribution",
]
