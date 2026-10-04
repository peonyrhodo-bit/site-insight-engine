# analytics/topics.py
"""
Topic analysis layer for the AI Director.

Responsibilities:
- identify and normalize thematic directions;
- group videos/research evidence by topic;
- calculate topic-level metrics;
- detect subtopics;
- connect topics with trend signals;
- collect evidence, risks and missing data;
- prepare structured topic profiles for Opportunity Analysis and Director.

This module does NOT:
- search YouTube;
- call MCP;
- call an AI provider;
- make strategic decisions;
- create final recommendations;
- decide which niche the project should pursue.

It answers:

    "What thematic directions are visible in the available data,
     and what do we know about each of them?"

Director answers:

    "What should we do with this information?"
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from math import log1p
import re
from typing import Any, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_TOPICS = 100
MAX_VIDEOS_PER_TOPIC = 100
MAX_EVIDENCE_ITEMS = 20
MAX_MISSING_ITEMS = 20
MAX_RISK_ITEMS = 20
MAX_SUBTOPICS = 20
MAX_KEYWORDS = 30

MIN_TOPIC_SCORE = 0.0

VIEWS_WEIGHT = 0.45
ENGAGEMENT_WEIGHT = 0.25
VELOCITY_WEIGHT = 0.20
EVIDENCE_WEIGHT = 0.10


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TopicVideo:
    """Normalized video evidence belonging to a topic."""

    video_id: str | None = None
    title: str = ""
    channel_id: str | None = None
    channel_title: str = ""

    views: float = 0.0
    likes: float = 0.0
    comments: float = 0.0

    published_at: str | None = None

    engagement_rate: float = 0.0
    velocity: float = 0.0

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TopicProfile:
    """
    Structured analytical profile of one thematic direction.
    """

    topic_id: str
    name: str
    normalized_name: str

    description: str = ""

    video_count: int = 0
    channel_count: int = 0

    total_views: float = 0.0
    average_views: float = 0.0
    median_views: float = 0.0

    average_likes: float = 0.0
    average_comments: float = 0.0
    average_engagement_rate: float = 0.0
    average_velocity: float = 0.0

    topic_score: float = 0.0
    confidence: float = 0.0

    keywords: list[str] = field(default_factory=list)
    subtopics: list[str] = field(default_factory=list)

    trend: dict[str, Any] = field(default_factory=dict)

    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)

    video_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TopicAnalysis:
    """
    Result of thematic analysis.

    This is the object that can later be passed to Opportunity Analysis
    and then to Director.
    """

    topics: list[TopicProfile] = field(default_factory=list)

    total_items: int = 0
    analyzed_items: int = 0

    uncovered_items: int = 0

    evidence_quality: float = 0.0

    global_keywords: list[str] = field(default_factory=list)
    global_subtopics: list[str] = field(default_factory=list)

    missing_data: list[str] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)

        if number != number:
            return default

        return number
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default

    return str(value).strip()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _unique_strings(
    values: Iterable[Any],
    *,
    limit: int | None = None,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = _text(value)

        if not text:
            continue

        key = text.casefold()

        if key in seen:
            continue

        seen.add(key)
        result.append(text)

        if limit is not None and len(result) >= limit:
            break

    return result


def _get(item: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]

    return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, set):
        return list(value)

    return [value]


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0

    return sum(values) / len(values)


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    middle = len(ordered) // 2

    if len(ordered) % 2:
        return ordered[middle]

    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _normalize_text(value: str) -> str:
    text = _text(value).casefold()

    text = text.replace("_", " ")
    text = text.replace("-", " ")

    text = re.sub(r"[^\w\s+#.]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _slug(value: str) -> str:
    normalized = _normalize_text(value)

    if not normalized:
        return "topic"

    result = re.sub(r"[^\w]+", "_", normalized, flags=re.UNICODE)
    result = result.strip("_")

    return result[:120] or "topic"


def _log_normalize(value: float) -> float:
    if value <= 0:
        return 0.0

    return _clamp(log1p(value) / log1p(10_000_000))


# ---------------------------------------------------------------------------
# Topic normalization
# ---------------------------------------------------------------------------


DEFAULT_TOPIC_ALIASES: dict[str, str] = {
    "ai": "AI",
    "artificial intelligence": "AI",
    "artificial intelligence ai": "AI",
    "ии": "AI",

    "machine learning": "Machine Learning",
    "ml": "Machine Learning",

    "deep learning": "Deep Learning",

    "generative ai": "Generative AI",
    "gen ai": "Generative AI",
    "genai": "Generative AI",

    "ai agents": "AI Agents",
    "ai agent": "AI Agents",
    "agents": "AI Agents",

    "chatgpt": "ChatGPT",
    "gpt": "ChatGPT",

    "youtube shorts": "YouTube Shorts",
    "shorts": "YouTube Shorts",

    "youtube": "YouTube",
}


def normalize_topic_name(
    topic: Any,
    *,
    aliases: Mapping[str, str] | None = None,
) -> str:
    """
    Normalize a topic name while preserving a human-readable form.
    """

    raw = _text(topic)

    if not raw:
        return ""

    normalized = _normalize_text(raw)

    alias_map = dict(DEFAULT_TOPIC_ALIASES)

    if aliases:
        alias_map.update(
            {
                _normalize_text(key): _text(value)
                for key, value in aliases.items()
            }
        )

    if normalized in alias_map:
        return alias_map[normalized]

    words = normalized.split()

    if not words:
        return ""

    return " ".join(
        word.upper()
        if len(word) <= 3
        else word.capitalize()
        for word in words
    )


def topic_id(topic_name: str) -> str:
    return f"topic:{_slug(topic_name)}"


# ---------------------------------------------------------------------------
# Video normalization
# ---------------------------------------------------------------------------


def normalize_video(
    item: Mapping[str, Any],
) -> TopicVideo:
    """
    Convert a raw research item into a normalized TopicVideo.
    """

    views = _safe_float(
        _get(
            item,
            "views",
            "view_count",
            "viewCount",
            "video_views",
            default=0,
        )
    )

    likes = _safe_float(
        _get(
            item,
            "likes",
            "like_count",
            "likeCount",
            "video_likes",
            default=0,
        )
    )

    comments = _safe_float(
        _get(
            item,
            "comments",
            "comment_count",
            "commentCount",
            "video_comments",
            default=0,
        )
    )

    engagement_rate = (
        (likes + comments) / views
        if views > 0
        else 0.0
    )

    velocity = _safe_float(
        _get(
            item,
            "velocity",
            "views_per_hour",
            "view_velocity",
            default=0,
        )
    )

    return TopicVideo(
        video_id=_text(
            _get(
                item,
                "video_id",
                "videoId",
                "id",
                default=None,
            )
        )
        or None,
        title=_text(
            _get(
                item,
                "title",
                "video_title",
                "name",
                default="",
            )
        ),
        channel_id=_text(
            _get(
                item,
                "channel_id",
                "channelId",
                default=None,
            )
        )
        or None,
        channel_title=_text(
            _get(
                item,
                "channel_title",
                "channelTitle",
                "channel_name",
                default="",
            )
        ),
        views=views,
        likes=likes,
        comments=comments,
        published_at=_text(
            _get(
                item,
                "published_at",
                "publishedAt",
                "published",
                default=None,
            )
        )
        or None,
        engagement_rate=engagement_rate,
        velocity=velocity,
        metadata=dict(item),
    )


# ---------------------------------------------------------------------------
# Topic extraction
# ---------------------------------------------------------------------------


def extract_topics(
    item: Mapping[str, Any],
) -> list[str]:
    """
    Extract explicit topic labels from a research item.

    Supported fields:
    - topic
    - topics
    - category
    - categories
    - niche
    - niches
    - thematic_direction
    - thematic_directions
    """

    values: list[Any] = []

    for key in (
        "topic",
        "topics",
        "category",
        "categories",
        "niche",
        "niches",
        "thematic_direction",
        "thematic_directions",
    ):
        values.extend(_as_list(item.get(key)))

    result = [
        normalize_topic_name(value)
        for value in values
    ]

    return _unique_strings(result, limit=MAX_TOPICS)


def extract_keywords(
    item: Mapping[str, Any],
) -> list[str]:
    values: list[Any] = []

    for key in (
        "keywords",
        "tags",
        "search_terms",
        "search_keywords",
    ):
        values.extend(_as_list(item.get(key)))

    return _unique_strings(values, limit=MAX_KEYWORDS)


def extract_subtopics(
    item: Mapping[str, Any],
) -> list[str]:
    values: list[Any] = []

    for key in (
        "subtopic",
        "subtopics",
        "sub_topic",
        "sub_topics",
    ):
        values.extend(_as_list(item.get(key)))

    normalized = [
        normalize_topic_name(value)
        for value in values
    ]

    return _unique_strings(normalized, limit=MAX_SUBTOPICS)


# ---------------------------------------------------------------------------
# Topic metrics
# ---------------------------------------------------------------------------


def calculate_topic_metrics(
    videos: Sequence[TopicVideo],
) -> dict[str, float]:
    if not videos:
        return {
            "video_count": 0,
            "channel_count": 0,
            "total_views": 0.0,
            "average_views": 0.0,
            "median_views": 0.0,
            "average_likes": 0.0,
            "average_comments": 0.0,
            "average_engagement_rate": 0.0,
            "average_velocity": 0.0,
        }

    views = [video.views for video in videos]
    likes = [video.likes for video in videos]
    comments = [video.comments for video in videos]
    engagement = [
        video.engagement_rate
        for video in videos
    ]
    velocity = [
        video.velocity
        for video in videos
        if video.velocity > 0
    ]

    channels = {
        video.channel_id
        for video in videos
        if video.channel_id
    }

    return {
        "video_count": len(videos),
        "channel_count": len(channels),
        "total_views": sum(views),
        "average_views": _mean(views),
        "median_views": _median(views),
        "average_likes": _mean(likes),
        "average_comments": _mean(comments),
        "average_engagement_rate": _mean(engagement),
        "average_velocity": _mean(velocity),
    }


def calculate_topic_score(
    metrics: Mapping[str, Any],
    *,
    evidence_quality: float = 0.0,
) -> float:
    """
    Calculate an analytical topic score.

    This is NOT a strategic recommendation score.
    It simply summarizes the observed strength of the available evidence.
    """

    views_signal = _log_normalize(
        _safe_float(metrics.get("average_views"))
    )

    engagement_signal = _clamp(
        _safe_float(
            metrics.get("average_engagement_rate")
        ) * 100.0
    )

    velocity_signal = _log_normalize(
        _safe_float(metrics.get("average_velocity"))
    )

    evidence_signal = _clamp(evidence_quality)

    score = (
        views_signal * VIEWS_WEIGHT
        + engagement_signal * ENGAGEMENT_WEIGHT
        + velocity_signal * VELOCITY_WEIGHT
        + evidence_signal * EVIDENCE_WEIGHT
    )

    return round(_clamp(score), 6)


# ---------------------------------------------------------------------------
# Evidence and confidence
# ---------------------------------------------------------------------------


def calculate_topic_confidence(
    *,
    video_count: int,
    channel_count: int,
    evidence_quality: float,
) -> float:
    """
    Estimate confidence in the topic profile.

    Confidence grows with:
    - number of observations;
    - diversity of channels;
    - evidence quality.
    """

    sample_signal = _clamp(
        video_count / 30.0
    )

    channel_signal = _clamp(
        channel_count / 10.0
    )

    confidence = (
        sample_signal * 0.45
        + channel_signal * 0.25
        + _clamp(evidence_quality) * 0.30
    )

    return round(_clamp(confidence), 6)


def build_topic_evidence(
    topic: str,
    videos: Sequence[TopicVideo],
    metrics: Mapping[str, Any],
) -> list[str]:
    evidence: list[str] = []

    video_count = _safe_int(metrics.get("video_count"))
    channel_count = _safe_int(metrics.get("channel_count"))
    average_views = _safe_float(metrics.get("average_views"))
    total_views = _safe_float(metrics.get("total_views"))
    engagement = _safe_float(
        metrics.get("average_engagement_rate")
    )

    if video_count:
        evidence.append(
            f"В выборке найдено {video_count} видео по теме «{topic}»."
        )

    if channel_count:
        evidence.append(
            f"Тема представлена как минимум {channel_count} каналами."
        )

    if average_views > 0:
        evidence.append(
            f"Среднее число просмотров видео: {round(average_views):,}."
        )

    if total_views > 0:
        evidence.append(
            f"Суммарно в выборке: {round(total_views):,} просмотров."
        )

    if engagement > 0:
        evidence.append(
            f"Средний engagement signal: {engagement:.4f}."
        )

    return _unique_strings(
        evidence,
        limit=MAX_EVIDENCE_ITEMS,
    )


def build_topic_risks(
    topic: str,
    videos: Sequence[TopicVideo],
    metrics: Mapping[str, Any],
) -> list[str]:
    risks: list[str] = []

    video_count = _safe_int(metrics.get("video_count"))
    channel_count = _safe_int(metrics.get("channel_count"))
    average_views = _safe_float(metrics.get("average_views"))

    if video_count < 5:
        risks.append(
            "Слишком маленькая выборка для уверенных выводов."
        )

    if channel_count < 3:
        risks.append(
            "Недостаточно разнообразия каналов для оценки конкуренции."
        )

    if average_views <= 0:
        risks.append(
            "В данных отсутствуют полезные значения просмотров."
        )

    if not videos:
        risks.append(
            "Нет наблюдений, непосредственно относящихся к теме."
        )

    return _unique_strings(
        risks,
        limit=MAX_RISK_ITEMS,
    )


def build_missing_data(
    topic: str,
    videos: Sequence[TopicVideo],
) -> list[str]:
    missing: list[str] = []

    if not videos:
        missing.extend(
            [
                "Видео по теме",
                "Метрики просмотров",
                "Данные по каналам",
                "Динамика темы",
            ]
        )
        return missing

    if not any(video.views > 0 for video in videos):
        missing.append("Просмотры")

    if not any(video.likes > 0 for video in videos):
        missing.append("Лайки")

    if not any(video.comments > 0 for video in videos):
        missing.append("Комментарии")

    if not any(video.published_at for video in videos):
        missing.append("Даты публикации")

    if not any(video.channel_id for video in videos):
        missing.append("Идентификаторы каналов")

    if not any(video.velocity > 0 for video in videos):
        missing.append("Скорость набора просмотров")

    return _unique_strings(
        missing,
        limit=MAX_MISSING_ITEMS,
    )


# ---------------------------------------------------------------------------
# Topic profile creation
# ---------------------------------------------------------------------------


def build_topic_profile(
    topic: str,
    videos: Sequence[TopicVideo],
    *,
    keywords: Sequence[str] | None = None,
    subtopics: Sequence[str] | None = None,
    trend: Mapping[str, Any] | None = None,
    evidence_quality: float = 0.0,
    description: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> TopicProfile:
    normalized_name = normalize_topic_name(topic)

    metrics = calculate_topic_metrics(videos)

    score = calculate_topic_score(
        metrics,
        evidence_quality=evidence_quality,
    )

    confidence = calculate_topic_confidence(
        video_count=_safe_int(metrics["video_count"]),
        channel_count=_safe_int(metrics["channel_count"]),
        evidence_quality=evidence_quality,
    )

    evidence = build_topic_evidence(
        normalized_name,
        videos,
        metrics,
    )

    risks = build_topic_risks(
        normalized_name,
        videos,
        metrics,
    )

    missing_data = build_missing_data(
        normalized_name,
        videos,
    )

    video_ids = _unique_strings(
        video.video_id
        for video in videos
        if video.video_id
    )

    return TopicProfile(
        topic_id=topic_id(normalized_name),
        name=normalized_name,
        normalized_name=_normalize_text(normalized_name),
        description=_text(description),
        video_count=_safe_int(metrics["video_count"]),
        channel_count=_safe_int(metrics["channel_count"]),
        total_views=_safe_float(metrics["total_views"]),
        average_views=_safe_float(metrics["average_views"]),
        median_views=_safe_float(metrics["median_views"]),
        average_likes=_safe_float(metrics["average_likes"]),
        average_comments=_safe_float(metrics["average_comments"]),
        average_engagement_rate=_safe_float(
            metrics["average_engagement_rate"]
        ),
        average_velocity=_safe_float(
            metrics["average_velocity"]
        ),
        topic_score=score,
        confidence=confidence,
        keywords=_unique_strings(
            keywords or [],
            limit=MAX_KEYWORDS,
        ),
        subtopics=_unique_strings(
            subtopics or [],
            limit=MAX_SUBTOPICS,
        ),
        trend=dict(trend or {}),
        evidence=evidence,
        risks=risks,
        missing_data=missing_data,
        video_ids=video_ids[:MAX_VIDEOS_PER_TOPIC],
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Topic analysis
# ---------------------------------------------------------------------------


def analyze_topics(
    items: Iterable[Mapping[str, Any]],
    *,
    aliases: Mapping[str, str] | None = None,
    topic_field: str | None = None,
    trend_data: Mapping[str, Mapping[str, Any]] | None = None,
) -> TopicAnalysis:
    """
    Analyze thematic directions in a collection of research items.

    The function intentionally works with already collected data.
    It does not fetch anything itself.
    """

    raw_items = list(items)

    topic_videos: dict[str, list[TopicVideo]] = defaultdict(list)
    topic_keywords: dict[str, list[str]] = defaultdict(list)
    topic_subtopics: dict[str, list[str]] = defaultdict(list)

    total_items = len(raw_items)
    analyzed_items = 0

    for item in raw_items:
        if not isinstance(item, Mapping):
            continue

        if topic_field:
            raw_topics = _as_list(item.get(topic_field))
            topics = [
                normalize_topic_name(
                    topic,
                    aliases=aliases,
                )
                for topic in raw_topics
            ]
            topics = _unique_strings(topics)
        else:
            topics = [
                normalize_topic_name(
                    topic,
                    aliases=aliases,
                )
                for topic in extract_topics(item)
            ]

        topics = [
            topic
            for topic in topics
            if topic
        ]

        if not topics:
            continue

        analyzed_items += 1

        video = normalize_video(item)

        keywords = extract_keywords(item)
        subtopics = extract_subtopics(item)

        for topic in topics:
            if len(topic_videos[topic]) < MAX_VIDEOS_PER_TOPIC:
                topic_videos[topic].append(video)

            topic_keywords[topic].extend(keywords)
            topic_subtopics[topic].extend(subtopics)

    topic_profiles: list[TopicProfile] = []

    for topic, videos in topic_videos.items():
        keywords = _unique_strings(
            topic_keywords[topic],
            limit=MAX_KEYWORDS,
        )

        subtopics = _unique_strings(
            topic_subtopics[topic],
            limit=MAX_SUBTOPICS,
        )

        metrics = calculate_topic_metrics(videos)

        evidence_quality = calculate_evidence_quality(
            video_count=_safe_int(metrics["video_count"]),
            channel_count=_safe_int(metrics["channel_count"]),
            has_views=any(
                video.views > 0
                for video in videos
            ),
            has_dates=any(
                video.published_at
                for video in videos
            ),
        )

        trend = (
            dict(trend_data.get(topic, {}))
            if trend_data
            else {}
        )

        profile = build_topic_profile(
            topic,
            videos,
            keywords=keywords,
            subtopics=subtopics,
            trend=trend,
            evidence_quality=evidence_quality,
        )

        topic_profiles.append(profile)

    topic_profiles.sort(
        key=lambda profile: (
            profile.topic_score,
            profile.confidence,
            profile.video_count,
        ),
        reverse=True,
    )

    topic_profiles = topic_profiles[:MAX_TOPICS]

    global_keywords = _rank_terms(
        topic_keywords,
        limit=MAX_KEYWORDS,
    )

    global_subtopics = _rank_terms(
        topic_subtopics,
        limit=MAX_SUBTOPICS,
    )

    uncovered_items = max(
        0,
        total_items - analyzed_items,
    )

    global_missing_data: list[str] = []

    if uncovered_items:
        global_missing_data.append(
            f"{uncovered_items} элементов исследования не удалось "
            "привязать к тематическому направлению."
        )

    if not topic_profiles:
        global_missing_data.append(
            "Не удалось определить ни одного тематического направления."
        )

    evidence_quality = calculate_global_evidence_quality(
        topic_profiles
    )

    return TopicAnalysis(
        topics=topic_profiles,
        total_items=total_items,
        analyzed_items=analyzed_items,
        uncovered_items=uncovered_items,
        evidence_quality=evidence_quality,
        global_keywords=global_keywords,
        global_subtopics=global_subtopics,
        missing_data=_unique_strings(
            global_missing_data,
            limit=MAX_MISSING_ITEMS,
        ),
        metadata={
            "topic_count": len(topic_profiles),
            "analysis_version": "1.0",
        },
    )


# ---------------------------------------------------------------------------
# Evidence quality
# ---------------------------------------------------------------------------


def calculate_evidence_quality(
    *,
    video_count: int,
    channel_count: int,
    has_views: bool,
    has_dates: bool,
) -> float:
    """
    Estimate how complete the evidence behind a topic is.
    """

    sample_signal = _clamp(
        video_count / 20.0
    )

    diversity_signal = _clamp(
        channel_count / 8.0
    )

    metrics_signal = 1.0 if has_views else 0.0
    date_signal = 1.0 if has_dates else 0.0

    score = (
        sample_signal * 0.35
        + diversity_signal * 0.25
        + metrics_signal * 0.25
        + date_signal * 0.15
    )

    return round(_clamp(score), 6)


def calculate_global_evidence_quality(
    topics: Sequence[TopicProfile],
) -> float:
    if not topics:
        return 0.0

    return round(
        _mean(
            [
                topic.confidence
                for topic in topics
            ]
        ),
        6,
    )


# ---------------------------------------------------------------------------
# Keyword / subtopic ranking
# ---------------------------------------------------------------------------


def _rank_terms(
    mapping: Mapping[str, Sequence[str]],
    *,
    limit: int,
) -> list[str]:
    counter: Counter[str] = Counter()

    for values in mapping.values():
        counter.update(
            _normalize_text(value)
            for value in values
            if _text(value)
        )

    return [
        term
        for term, _count in counter.most_common(limit)
    ]


# ---------------------------------------------------------------------------
# Topic comparisons
# ---------------------------------------------------------------------------


def compare_topics(
    topics: Sequence[TopicProfile],
) -> list[TopicProfile]:
    """
    Sort topics by observed analytical strength.

    This is descriptive analytical ordering only.
    It is NOT a strategic recommendation.
    """

    return sorted(
        topics,
        key=lambda topic: (
            topic.topic_score,
            topic.confidence,
            topic.average_views,
            topic.video_count,
        ),
        reverse=True,
    )


def strongest_topics(
    topics: Sequence[TopicProfile],
    *,
    limit: int = 10,
) -> list[TopicProfile]:
    return compare_topics(topics)[:max(0, limit)]


# ---------------------------------------------------------------------------
# Research gaps
# ---------------------------------------------------------------------------


def identify_topic_research_gaps(
    topics: Sequence[TopicProfile],
) -> list[dict[str, Any]]:
    """
    Identify what should be researched further for each topic.

    This does not decide whether a topic is worth pursuing.
    """

    gaps: list[dict[str, Any]] = []

    for topic in topics:
        if not topic.missing_data:
            continue

        gaps.append(
            {
                "topic_id": topic.topic_id,
                "topic": topic.name,
                "confidence": topic.confidence,
                "missing_data": list(topic.missing_data),
                "risks": list(topic.risks),
            }
        )

    return gaps


# ---------------------------------------------------------------------------
# Director payload
# ---------------------------------------------------------------------------


def prepare_for_director(
    analysis: TopicAnalysis,
    *,
    max_topics: int = 20,
) -> dict[str, Any]:
    """
    Convert topic analysis into a compact payload for Director.
    """

    topics = compare_topics(analysis.topics)[:max_topics]

    return {
        "type": "topic_analysis",
        "version": "1.0",
        "summary": {
            "total_items": analysis.total_items,
            "analyzed_items": analysis.analyzed_items,
            "uncovered_items": analysis.uncovered_items,
            "topic_count": len(analysis.topics),
            "evidence_quality": analysis.evidence_quality,
        },
        "topics": [
            {
                "topic_id": topic.topic_id,
                "name": topic.name,
                "description": topic.description,
                "video_count": topic.video_count,
                "channel_count": topic.channel_count,
                "total_views": topic.total_views,
                "average_views": topic.average_views,
                "median_views": topic.median_views,
                "average_likes": topic.average_likes,
                "average_comments": topic.average_comments,
                "average_engagement_rate": (
                    topic.average_engagement_rate
                ),
                "average_velocity": topic.average_velocity,
                "topic_score": topic.topic_score,
                "confidence": topic.confidence,
                "keywords": list(topic.keywords),
                "subtopics": list(topic.subtopics),
                "trend": dict(topic.trend),
                "evidence": list(topic.evidence),
                "risks": list(topic.risks),
                "missing_data": list(topic.missing_data),
                "video_ids": list(topic.video_ids),
            }
            for topic in topics
        ],
        "global_keywords": list(analysis.global_keywords),
        "global_subtopics": list(analysis.global_subtopics),
        "missing_data": list(analysis.missing_data),
    }


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def topic_to_dict(
    topic: TopicProfile,
) -> dict[str, Any]:
    return asdict(topic)


def analysis_to_dict(
    analysis: TopicAnalysis,
) -> dict[str, Any]:
    return asdict(analysis)


# ---------------------------------------------------------------------------
# Convenience API
# ---------------------------------------------------------------------------


def analyze_topic_items(
    items: Iterable[Mapping[str, Any]],
    **kwargs: Any,
) -> TopicAnalysis:
    """
    Public convenience alias.
    """

    return analyze_topics(
        items,
        **kwargs,
    )


def build_topic_profiles(
    items: Iterable[Mapping[str, Any]],
    **kwargs: Any,
) -> list[TopicProfile]:
    """
    Analyze items and return only topic profiles.
    """

    return analyze_topics(
        items,
        **kwargs,
    ).topics


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


__all__ = [
    "TopicVideo",
    "TopicProfile",
    "TopicAnalysis",
    "normalize_topic_name",
    "topic_id",
    "normalize_video",
    "extract_topics",
    "extract_keywords",
    "extract_subtopics",
    "calculate_topic_metrics",
    "calculate_topic_score",
    "calculate_topic_confidence",
    "calculate_evidence_quality",
    "calculate_global_evidence_quality",
    "build_topic_evidence",
    "build_topic_risks",
    "build_missing_data",
    "build_topic_profile",
    "analyze_topics",
    "analyze_topic_items",
    "build_topic_profiles",
    "compare_topics",
    "strongest_topics",
    "identify_topic_research_gaps",
    "prepare_for_director",
    "topic_to_dict",
    "analysis_to_dict",
]
