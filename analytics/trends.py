# analytics/trends.py
"""
Trend analysis layer for the Director system.

Responsibilities:
- compare current and previous research periods;
- detect direction and magnitude of change;
- measure acceleration / deceleration;
- detect emerging and declining topics;
- identify persistent signals;
- estimate trend strength and confidence;
- prepare compact trend intelligence for Director.

This module does NOT:
- call YouTube/MCP;
- call AI providers;
- make final Director decisions;
- mutate database state.

It works with ordinary dictionaries/lists and can therefore consume:
- research snapshots;
- analytics results;
- database records;
- MCP results;
- historical Director runs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import log1p
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence


# ============================================================
# CONSTANTS
# ============================================================

EPSILON = 1e-9

DEFAULT_STRONG_CHANGE = 0.30
DEFAULT_MODERATE_CHANGE = 0.10
DEFAULT_WEAK_CHANGE = 0.03

DEFAULT_PERSISTENCE_PERIODS = 3

MAX_TOPIC_RESULTS = 50
MAX_HISTORY_PERIODS = 20


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(slots=True)
class MetricChange:
    name: str
    current: float
    previous: float
    absolute_change: float
    relative_change: float
    direction: str
    strength: float


@dataclass(slots=True)
class TopicTrend:
    topic: str

    current_count: int = 0
    previous_count: int = 0

    current_share: float = 0.0
    previous_share: float = 0.0

    absolute_change: float = 0.0
    relative_change: float = 0.0

    direction: str = "stable"
    strength: float = 0.0

    emerging: bool = False
    declining: bool = False
    persistent: bool = False


@dataclass(slots=True)
class TrendAnalysis:
    direction: str = "stable"
    strength: float = 0.0
    confidence: float = 0.0

    metrics: list[MetricChange] = field(
        default_factory=list
    )

    topics: list[TopicTrend] = field(
        default_factory=list
    )

    accelerating: bool = False
    decelerating: bool = False

    emerging_topics: list[str] = field(
        default_factory=list
    )

    declining_topics: list[str] = field(
        default_factory=list
    )

    persistent_topics: list[str] = field(
        default_factory=list
    )

    signals: list[str] = field(
        default_factory=list
    )

    explanation: str = ""

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

        result = float(value)

        if result != result:
            return default

        return result

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


def _now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _parse_datetime(
    value: Any,
) -> datetime | None:
    if isinstance(
        value,
        datetime,
    ):
        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )

        return value

    text = _text(value)

    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(
            text.replace(
                "Z",
                "+00:00",
            )
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed

    except ValueError:
        return None


# ============================================================
# GENERIC CHANGE CALCULATION
# ============================================================

def relative_change(
    current: float,
    previous: float,
) -> float:
    """
    Calculate relative change.

    Example:
        120 -> 150 = +0.25
        150 -> 120 = -0.20

    If the previous value is zero:
        - both zero => 0
        - current positive => 1
    """

    current = _safe_float(
        current
    )

    previous = _safe_float(
        previous
    )

    if abs(previous) <= EPSILON:
        if abs(current) <= EPSILON:
            return 0.0

        return 1.0

    return (
        current - previous
    ) / abs(previous)


def classify_change(
    change: float,
    *,
    strong_threshold: float = DEFAULT_STRONG_CHANGE,
    moderate_threshold: float = DEFAULT_MODERATE_CHANGE,
    weak_threshold: float = DEFAULT_WEAK_CHANGE,
) -> str:
    """
    Convert a numeric relative change into a stable signal.
    """

    change = _safe_float(
        change
    )

    if change >= strong_threshold:
        return "strong_up"

    if change >= moderate_threshold:
        return "up"

    if change >= weak_threshold:
        return "slight_up"

    if change <= -strong_threshold:
        return "strong_down"

    if change <= -moderate_threshold:
        return "down"

    if change <= -weak_threshold:
        return "slight_down"

    return "stable"


def change_strength(
    change: float,
) -> float:
    """
    Normalize absolute change into 0..1.

    log scaling prevents extremely large values from
    completely dominating the trend signal.
    """

    change = abs(
        _safe_float(change)
    )

    if change <= 0:
        return 0.0

    return _clamp(
        log1p(change)
        / log1p(1.0)
        if change <= 1.0
        else log1p(change)
        / log1p(10.0)
    )


def metric_change(
    name: str,
    current: float,
    previous: float,
) -> MetricChange:
    current = _safe_float(
        current
    )

    previous = _safe_float(
        previous
    )

    absolute = (
        current - previous
    )

    relative = relative_change(
        current,
        previous,
    )

    return MetricChange(
        name=name,
        current=current,
        previous=previous,
        absolute_change=absolute,
        relative_change=relative,
        direction=classify_change(
            relative
        ),
        strength=change_strength(
            relative
        ),
    )


# ============================================================
# VIDEO FIELD EXTRACTION
# ============================================================

def _get(
    video: Mapping[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    for key in keys:
        if key in video:
            value = video[key]

            if value is not None:
                return value

    return default


def get_views(
    video: Mapping[str, Any],
) -> float:
    analytics = _get(
        video,
        "analytics",
        default={},
    )

    if isinstance(
        analytics,
        Mapping,
    ):
        value = _get(
            analytics,
            "views",
        )

        if value is not None:
            return max(
                0.0,
                _safe_float(value),
            )

    return max(
        0.0,
        _safe_float(
            _get(
                video,
                "views",
                "view_count",
                "viewCount",
            )
        ),
    )


def get_likes(
    video: Mapping[str, Any],
) -> float:
    analytics = _get(
        video,
        "analytics",
        default={},
    )

    if isinstance(
        analytics,
        Mapping,
    ):
        value = _get(
            analytics,
            "likes",
        )

        if value is not None:
            return max(
                0.0,
                _safe_float(value),
            )

    return max(
        0.0,
        _safe_float(
            _get(
                video,
                "likes",
                "like_count",
                "likeCount",
            )
        ),
    )


def get_comments(
    video: Mapping[str, Any],
) -> float:
    analytics = _get(
        video,
        "analytics",
        default={},
    )

    if isinstance(
        analytics,
        Mapping,
    ):
        value = _get(
            analytics,
            "comments",
        )

        if value is not None:
            return max(
                0.0,
                _safe_float(value),
            )

    return max(
        0.0,
        _safe_float(
            _get(
                video,
                "comments",
                "comment_count",
                "commentCount",
            )
        ),
    )


def get_performance_score(
    video: Mapping[str, Any],
) -> float:
    analytics = _get(
        video,
        "analytics",
        default={},
    )

    if isinstance(
        analytics,
        Mapping,
    ):
        return _clamp(
            _safe_float(
                _get(
                    analytics,
                    "performance_score",
                )
            )
        )

    return _clamp(
        _safe_float(
            _get(
                video,
                "performance_score",
                "score",
            )
        )
    )


def get_engagement_rate(
    video: Mapping[str, Any],
) -> float:
    analytics = _get(
        video,
        "analytics",
        default={},
    )

    if isinstance(
        analytics,
        Mapping,
    ):
        value = _get(
            analytics,
            "engagement_rate",
        )

        if value is not None:
            return max(
                0.0,
                _safe_float(value),
            )

    views = get_views(
        video
    )

    if views <= 0:
        return 0.0

    return (
        get_likes(video)
        + get_comments(video)
    ) / views


def get_topics(
    video: Mapping[str, Any],
) -> list[str]:
    raw = _get(
        video,
        "topics",
        "topic",
        "tags",
        "keywords",
        default=[],
    )

    if isinstance(
        raw,
        str,
    ):
        return [
            item.strip()
            for item in raw.split(",")
            if item.strip()
        ]

    if isinstance(
        raw,
        Sequence,
    ):
        return [
            _text(item)
            for item in raw
            if _text(item)
        ]

    return []


# ============================================================
# COLLECTION METRICS
# ============================================================

def collection_metrics(
    videos: Iterable[
        Mapping[str, Any]
    ],
) -> dict[str, float]:
    videos = [
        video
        for video in videos
        if isinstance(
            video,
            Mapping,
        )
    ]

    if not videos:
        return {
            "count": 0,
            "views": 0.0,
            "average_views": 0.0,
            "engagement_rate": 0.0,
            "performance_score": 0.0,
            "likes": 0.0,
            "comments": 0.0,
        }

    views = [
        get_views(video)
        for video in videos
    ]

    likes = [
        get_likes(video)
        for video in videos
    ]

    comments = [
        get_comments(video)
        for video in videos
    ]

    engagement = [
        get_engagement_rate(video)
        for video in videos
    ]

    scores = [
        get_performance_score(video)
        for video in videos
    ]

    return {
        "count": len(videos),
        "views": sum(views),
        "average_views": _mean(views),
        "engagement_rate": _mean(
            engagement
        ),
        "performance_score": _mean(
            scores
        ),
        "likes": sum(likes),
        "comments": sum(comments),
    }


# ============================================================
# METRIC TREND
# ============================================================

def compare_periods(
    current: Sequence[
        Mapping[str, Any]
    ],
    previous: Sequence[
        Mapping[str, Any]
    ],
) -> list[MetricChange]:
    current_metrics = collection_metrics(
        current
    )

    previous_metrics = collection_metrics(
        previous
    )

    metric_names = [
        "count",
        "views",
        "average_views",
        "engagement_rate",
        "performance_score",
        "likes",
        "comments",
    ]

    return [
        metric_change(
            name=name,
            current=current_metrics.get(
                name,
                0.0,
            ),
            previous=previous_metrics.get(
                name,
                0.0,
            ),
        )
        for name in metric_names
    ]


# ============================================================
# OVERALL DIRECTION
# ============================================================

def determine_direction(
    changes: Sequence[
        MetricChange
    ],
) -> tuple[str, float]:
    if not changes:
        return (
            "unknown",
            0.0,
        )

    # Performance and engagement receive more importance
    # than raw item count.
    weights = {
        "performance_score": 0.35,
        "engagement_rate": 0.30,
        "average_views": 0.20,
        "views": 0.10,
        "count": 0.05,
    }

    weighted = []

    for change in changes:
        weight = weights.get(
            change.name,
            0.0,
        )

        if weight <= 0:
            continue

        weighted.append(
            (
                change.relative_change,
                weight,
            )
        )

    if not weighted:
        return (
            "unknown",
            0.0,
        )

    total_weight = sum(
        weight
        for _, weight in weighted
    )

    score = (
        sum(
            value * weight
            for value, weight in weighted
        )
        / max(
            total_weight,
            EPSILON,
        )
    )

    strength = _clamp(
        abs(score)
        * 2.0
    )

    if score >= 0.20:
        return (
            "strong_up",
            strength,
        )

    if score >= 0.05:
        return (
            "up",
            strength,
        )

    if score <= -0.20:
        return (
            "strong_down",
            strength,
        )

    if score <= -0.05:
        return (
            "down",
            strength,
        )

    return (
        "stable",
        strength,
    )


# ============================================================
# TOPIC COUNTS
# ============================================================

def topic_counts(
    videos: Iterable[
        Mapping[str, Any]
    ],
) -> Counter[str]:
    counter: Counter[str] = Counter()

    for video in videos:
        for topic in get_topics(video):
            counter[
                topic
            ] += 1

    return counter


def topic_shares(
    videos: Sequence[
        Mapping[str, Any]
    ],
) -> dict[str, float]:
    counts = topic_counts(
        videos
    )

    total = sum(
        counts.values()
    )

    if total <= 0:
        return {}

    return {
        topic: count / total
        for topic, count
        in counts.items()
    }


# ============================================================
# TOPIC TREND
# ============================================================

def compare_topics(
    current: Sequence[
        Mapping[str, Any]
    ],
    previous: Sequence[
        Mapping[str, Any]
    ],
    *,
    limit: int = MAX_TOPIC_RESULTS,
) -> list[TopicTrend]:
    current_counts = topic_counts(
        current
    )

    previous_counts = topic_counts(
        previous
    )

    current_total = max(
        1,
        sum(
            current_counts.values()
        ),
    )

    previous_total = max(
        1,
        sum(
            previous_counts.values()
        ),
    )

    all_topics = (
        set(current_counts)
        | set(previous_counts)
    )

    results: list[TopicTrend] = []

    for topic in all_topics:
        current_count = (
            current_counts.get(
                topic,
                0,
            )
        )

        previous_count = (
            previous_counts.get(
                topic,
                0,
            )
        )

        current_share = (
            current_count
            / current_total
        )

        previous_share = (
            previous_count
            / previous_total
        )

        absolute_change = (
            current_share
            - previous_share
        )

        if previous_share <= EPSILON:
            if current_share > 0:
                relative = 1.0
            else:
                relative = 0.0
        else:
            relative = (
                current_share
                - previous_share
            ) / previous_share

        direction = classify_change(
            relative
        )

        strength = _clamp(
            abs(absolute_change)
            * 5.0
        )

        emerging = (
            current_count > 0
            and previous_count == 0
        )

        declining = (
            current_count == 0
            and previous_count > 0
        )

        results.append(
            TopicTrend(
                topic=topic,
                current_count=current_count,
                previous_count=previous_count,
                current_share=current_share,
                previous_share=previous_share,
                absolute_change=absolute_change,
                relative_change=relative,
                direction=direction,
                strength=strength,
                emerging=emerging,
                declining=declining,
            )
        )

    results.sort(
        key=lambda item: (
            item.strength,
            item.current_count,
            item.current_share,
        ),
        reverse=True,
    )

    return results[
        : max(
            1,
            min(
                int(limit),
                MAX_TOPIC_RESULTS,
            ),
        )
    ]


# ============================================================
# TOPIC PERSISTENCE
# ============================================================

def detect_persistent_topics(
    history: Sequence[
        Sequence[
            Mapping[str, Any]
        ]
    ],
    *,
    periods: int = DEFAULT_PERSISTENCE_PERIODS,
    min_share: float = 0.05,
) -> list[str]:
    """
    Find topics that remain materially represented across
    multiple historical periods.

    history must be ordered oldest -> newest.
    """

    if not history:
        return []

    selected = list(history)[
        -max(
            1,
            int(periods),
        ):
    ]

    if len(selected) < 2:
        return []

    topic_presence: Counter[str] = Counter()

    for period in selected:
        shares = topic_shares(
            list(period)
        )

        for topic, share in shares.items():
            if share >= min_share:
                topic_presence[
                    topic
                ] += 1

    required = max(
        2,
        len(selected) - 1,
    )

    return [
        topic
        for topic, count
        in topic_presence.items()
        if count >= required
    ]


# ============================================================
# ACCELERATION
# ============================================================

def calculate_acceleration(
    history: Sequence[
        Sequence[
            Mapping[str, Any]
        ]
    ],
) -> dict[str, Any]:
    """
    Compare consecutive periods.

    history:
        oldest -> newest

    Returns a compact description of whether the
    overall performance trend is accelerating or slowing.
    """

    if len(history) < 3:
        return {
            "available": False,
            "accelerating": False,
            "decelerating": False,
            "score": 0.0,
        }

    periods = list(history)[
        -3:
    ]

    first = collection_metrics(
        periods[0]
    )

    second = collection_metrics(
        periods[1]
    )

    third = collection_metrics(
        periods[2]
    )

    first_score = first[
        "performance_score"
    ]

    second_score = second[
        "performance_score"
    ]

    third_score = third[
        "performance_score"
    ]

    first_change = relative_change(
        second_score,
        first_score,
    )

    second_change = relative_change(
        third_score,
        second_score,
    )

    acceleration = (
        second_change
        - first_change
    )

    return {
        "available": True,
        "accelerating": (
            acceleration > 0.05
        ),
        "decelerating": (
            acceleration < -0.05
        ),
        "score": acceleration,
        "first_change": first_change,
        "second_change": second_change,
    }


# ============================================================
# MOMENTUM
# ============================================================

def calculate_momentum(
    videos: Sequence[
        Mapping[str, Any]
    ],
) -> float:
    """
    Estimate current momentum from:
    - performance;
    - engagement;
    - views;
    - freshness.

    This is intentionally a signal rather than a prediction.
    """

    if not videos:
        return 0.0

    scores = []

    now = _now()

    for video in videos:
        performance = (
            get_performance_score(
                video
            )
        )

        engagement = _clamp(
            get_engagement_rate(
                video
            )
            * 20.0
        )

        published = _parse_datetime(
            _get(
                video,
                "published_at",
                "publishedAt",
            )
        )

        if published is not None:
            age_hours = max(
                0.0,
                (
                    now - published
                ).total_seconds()
                / 3600.0,
            )

            freshness = (
                0.5
                ** (
                    age_hours
                    / 72.0
                )
            )
        else:
            freshness = 0.0

        score = (
            0.45 * performance
            + 0.35 * engagement
            + 0.20 * freshness
        )

        scores.append(
            _clamp(score)
        )

    return _clamp(
        _mean(scores)
    )


# ============================================================
# SIGNAL GENERATION
# ============================================================

def generate_signals(
    *,
    direction: str,
    strength: float,
    topics: Sequence[
        TopicTrend
    ],
    acceleration: Mapping[str, Any],
    current_count: int,
    previous_count: int,
) -> list[str]:
    signals: list[str] = []

    if direction in {
        "strong_up",
        "up",
    }:
        signals.append(
            "overall_growth"
        )

    if direction in {
        "strong_down",
        "down",
    }:
        signals.append(
            "overall_decline"
        )

    if direction == "stable":
        signals.append(
            "overall_stability"
        )

    if strength >= 0.70:
        signals.append(
            "strong_trend_signal"
        )

    if acceleration.get(
        "accelerating"
    ):
        signals.append(
            "accelerating"
        )

    if acceleration.get(
        "decelerating"
    ):
        signals.append(
            "decelerating"
        )

    emerging = [
        topic
        for topic in topics
        if topic.emerging
    ]

    declining = [
        topic
        for topic in topics
        if topic.declining
    ]

    if emerging:
        signals.append(
            "emerging_topics"
        )

    if declining:
        signals.append(
            "declining_topics"
        )

    if current_count < 5:
        signals.append(
            "small_current_sample"
        )

    if previous_count < 5:
        signals.append(
            "small_previous_sample"
        )

    return signals


# ============================================================
# CONFIDENCE
# ============================================================

def calculate_trend_confidence(
    *,
    current_count: int,
    previous_count: int,
    metrics: Sequence[
        MetricChange
    ],
    topics: Sequence[
        TopicTrend
    ],
    history_periods: int = 2,
) -> float:
    if (
        current_count <= 0
        or previous_count <= 0
    ):
        return 0.0

    sample_score = _clamp(
        min(
            current_count,
            previous_count,
        )
        / 30.0
    )

    metric_score = _clamp(
        len(metrics)
        / 5.0
    )

    topic_score = _clamp(
        len(topics)
        / 10.0
    )

    history_score = _clamp(
        history_periods
        / 5.0
    )

    return _clamp(
        0.40 * sample_score
        + 0.25 * metric_score
        + 0.20 * topic_score
        + 0.15 * history_score
    )


# ============================================================
# EXPLANATION
# ============================================================

def build_explanation(
    *,
    direction: str,
    strength: float,
    acceleration: Mapping[str, Any],
    emerging_topics: Sequence[str],
    declining_topics: Sequence[str],
) -> str:
    parts: list[str] = []

    direction_text = {
        "strong_up": "strong upward movement",
        "up": "upward movement",
        "strong_down": "strong downward movement",
        "down": "downward movement",
        "stable": "relative stability",
        "unknown": "insufficient directional evidence",
    }.get(
        direction,
        "unclear movement",
    )

    parts.append(
        f"Overall signal indicates {direction_text}."
    )

    if acceleration.get(
        "accelerating"
    ):
        parts.append(
            "The positive movement is accelerating."
        )

    if acceleration.get(
        "decelerating"
    ):
        parts.append(
            "The movement is losing speed."
        )

    if emerging_topics:
        parts.append(
            "Emerging topics are present."
        )

    if declining_topics:
        parts.append(
            "Some previously observed topics are declining."
        )

    if strength < 0.30:
        parts.append(
            "The signal is weak and should be interpreted cautiously."
        )

    return " ".join(parts)


# ============================================================
# MAIN ANALYSIS
# ============================================================

def analyze_trend(
    *,
    current: Sequence[
        Mapping[str, Any]
    ],
    previous: Sequence[
        Mapping[str, Any]
    ] | None = None,
    history: Sequence[
        Sequence[
            Mapping[str, Any]
        ]
    ] | None = None,
    metadata: Mapping[str, Any]
    | None = None,
) -> TrendAnalysis:
    current = [
        item
        for item in current
        if isinstance(
            item,
            Mapping,
        )
    ]

    previous = [
        item
        for item in (
            previous or []
        )
        if isinstance(
            item,
            Mapping,
        )
    ]

    history = list(
        history or []
    )

    if not previous:
        return TrendAnalysis(
            direction="unknown",
            strength=0.0,
            confidence=0.0,
            signals=[
                "insufficient_comparison_data"
            ],
            explanation=(
                "A previous period is required "
                "to establish a directional trend."
            ),
            metadata=dict(
                metadata or {}
            ),
        )

    metrics = compare_periods(
        current,
        previous,
    )

    direction, strength = (
        determine_direction(
            metrics
        )
    )

    topics = compare_topics(
        current,
        previous,
    )

    acceleration = (
        calculate_acceleration(
            history
        )
        if history
        else {
            "available": False,
            "accelerating": False,
            "decelerating": False,
            "score": 0.0,
        }
    )

    persistent_topics = (
        detect_persistent_topics(
            history
        )
        if history
        else []
    )

    for topic in topics:
        if (
            topic.topic
            in persistent_topics
        ):
            topic.persistent = True

    emerging_topics = [
        topic.topic
        for topic in topics
        if topic.emerging
    ]

    declining_topics = [
        topic.topic
        for topic in topics
        if topic.declining
    ]

    signals = generate_signals(
        direction=direction,
        strength=strength,
        topics=topics,
        acceleration=acceleration,
        current_count=len(current),
        previous_count=len(previous),
    )

    confidence = (
        calculate_trend_confidence(
            current_count=len(current),
            previous_count=len(previous),
            metrics=metrics,
            topics=topics,
            history_periods=max(
                2,
                len(history),
            ),
        )
    )

    explanation = build_explanation(
        direction=direction,
        strength=strength,
        acceleration=acceleration,
        emerging_topics=emerging_topics,
        declining_topics=declining_topics,
    )

    return TrendAnalysis(
        direction=direction,
        strength=strength,
        confidence=confidence,
        metrics=metrics,
        topics=topics,
        accelerating=bool(
            acceleration.get(
                "accelerating",
                False,
            )
        ),
        decelerating=bool(
            acceleration.get(
                "decelerating",
                False,
            )
        ),
        emerging_topics=emerging_topics,
        declining_topics=declining_topics,
        persistent_topics=persistent_topics,
        signals=signals,
        explanation=explanation,
        metadata={
            **dict(
                metadata or {}
            ),
            "acceleration": acceleration,
        },
    )


# ============================================================
# HISTORY SUMMARY
# ============================================================

def summarize_history(
    history: Sequence[
        Sequence[
            Mapping[str, Any]
        ]
    ],
) -> list[dict[str, Any]]:
    """
    Produce a compact chronological summary.

    history is expected oldest -> newest.
    """

    result: list[dict[str, Any]] = []

    history = list(history)[
        -MAX_HISTORY_PERIODS:
    ]

    for index, period in enumerate(
        history
    ):
        metrics = collection_metrics(
            period
        )

        result.append(
            {
                "period_index": index,
                "count": metrics[
                    "count"
                ],
                "views": metrics[
                    "views"
                ],
                "average_views": metrics[
                    "average_views"
                ],
                "engagement_rate": metrics[
                    "engagement_rate"
                ],
                "performance_score": metrics[
                    "performance_score"
                ],
            }
        )

    return result


# ============================================================
# DIRECTOR PAYLOAD
# ============================================================

def prepare_for_director(
    trend: TrendAnalysis
    | Mapping[str, Any],
) -> dict[str, Any]:
    """
    Produce the stable trend structure consumed by Director.

    The goal is to expose evidence and signals without
    pretending that the trend layer itself knows the final action.
    """

    if isinstance(
        trend,
        TrendAnalysis,
    ):
        data = asdict(
            trend
        )
    else:
        data = dict(
            trend
        )

    metrics = []

    for item in data.get(
        "metrics",
        [],
    ):
        if isinstance(
            item,
            MetricChange,
        ):
            item = asdict(item)

        metrics.append(
            item
        )

    topics = []

    for item in data.get(
        "topics",
        [],
    ):
        if isinstance(
            item,
            TopicTrend,
        ):
            item = asdict(item)

        topics.append(
            item
        )

    return {
        "direction": data.get(
            "direction",
            "unknown",
        ),
        "strength": _safe_float(
            data.get(
                "strength"
            )
        ),
        "confidence": _safe_float(
            data.get(
                "confidence"
            )
        ),
        "accelerating": bool(
            data.get(
                "accelerating",
                False,
            )
        ),
        "decelerating": bool(
            data.get(
                "decelerating",
                False,
            )
        ),
        "emerging_topics": list(
            data.get(
                "emerging_topics",
                [],
            )
        )[:MAX_TOPIC_RESULTS],
        "declining_topics": list(
            data.get(
                "declining_topics",
                [],
            )
        )[:MAX_TOPIC_RESULTS],
        "persistent_topics": list(
            data.get(
                "persistent_topics",
                [],
            )
        )[:MAX_TOPIC_RESULTS],
        "signals": list(
            data.get(
                "signals",
                [],
            )
        ),
        "metrics": metrics,
        "topics": topics[:MAX_TOPIC_RESULTS],
        "explanation": _text(
            data.get(
                "explanation"
            )
        ),
        "metadata": data.get(
            "metadata",
            {},
        ),
    }


# ============================================================
# SERIALIZATION
# ============================================================

def trend_to_dict(
    trend: TrendAnalysis,
) -> dict[str, Any]:
    return asdict(
        trend
    )


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "MetricChange",
    "TopicTrend",
    "TrendAnalysis",
    "analyze_trend",
    "build_explanation",
    "calculate_acceleration",
    "calculate_momentum",
    "calculate_trend_confidence",
    "change_strength",
    "classify_change",
    "collection_metrics",
    "compare_periods",
    "compare_topics",
    "detect_persistent_topics",
    "determine_direction",
    "get_comments",
    "get_engagement_rate",
    "get_likes",
    "get_performance_score",
    "get_topics",
    "get_views",
    "metric_change",
    "prepare_for_director",
    "relative_change",
    "summarize_history",
    "topic_counts",
    "topic_shares",
    "trend_to_dict",
]
