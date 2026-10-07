"""
Director research strategy.

Research planning only.
Actual data acquisition belongs to data/youtube.py and youtube-mcp.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
from uuid import uuid4


class ResearchPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ResearchStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass
class ResearchQuery:
    query: str
    language: str = "en"
    region_code: str | None = None
    purpose: str = ""
    priority: ResearchPriority = ResearchPriority.MEDIUM
    max_results: int = 25
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchGap:
    description: str
    importance: float = 0.5
    suggested_method: str = ""
    topic: str | None = None

    def __post_init__(self) -> None:
        self.importance = max(0.0, min(1.0, float(self.importance)))


@dataclass
class ResearchPlan:
    research_id: str
    objective: str
    status: ResearchStatus
    priorities: list[str]
    languages: list[str]
    directions: list[str]
    queries: list[ResearchQuery]
    gaps: list[ResearchGap]
    reason: str
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default

    if isinstance(source, dict):
        return source.get(key, default)

    return getattr(source, key, default)


def normalize_languages(
    languages: Iterable[str] | None,
) -> list[str]:
    result: list[str] = []

    for language in languages or []:
        value = str(language).strip().lower()

        if value and value not in result:
            result.append(value)

    return result


def choose_research_languages(
    *,
    preferred: Iterable[str] | None = None,
    observed_languages: Iterable[str] | None = None,
    defaults: Iterable[str] = ("en", "ru"),
) -> list[str]:
    """
    Build a research language set.

    Preference:
    1. explicit user/project preference
    2. languages already producing useful evidence
    3. conservative defaults
    """
    result = normalize_languages(preferred)

    for language in normalize_languages(observed_languages):
        if language not in result:
            result.append(language)

    for language in normalize_languages(defaults):
        if language not in result:
            result.append(language)

    return result[:8]


def build_query(
    *,
    query: str,
    language: str,
    purpose: str,
    priority: ResearchPriority = ResearchPriority.MEDIUM,
    region_code: str | None = None,
    max_results: int = 25,
    metadata: dict[str, Any] | None = None,
) -> ResearchQuery:
    return ResearchQuery(
        query=str(query).strip(),
        language=language,
        purpose=str(purpose).strip(),
        priority=priority,
        region_code=region_code,
        max_results=max(1, min(int(max_results), 100)),
        metadata=dict(metadata or {}),
    )


def build_research_plan(
    *,
    objective: str,
    directions: Iterable[str] | None = None,
    queries: Iterable[ResearchQuery] | None = None,
    gaps: Iterable[ResearchGap] | None = None,
    languages: Iterable[str] | None = None,
    reason: str = "",
    priorities: Iterable[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResearchPlan:
    return ResearchPlan(
        research_id=f"research_{uuid4().hex[:12]}",
        objective=str(objective or "").strip(),
        status=ResearchStatus.PLANNED,
        priorities=[str(x) for x in (priorities or []) if str(x).strip()],
        languages=normalize_languages(languages),
        directions=[
            str(x) for x in (directions or []) if str(x).strip()
        ],
        queries=list(queries or []),
        gaps=list(gaps or []),
        reason=str(reason or "").strip(),
        metadata=dict(metadata or {}),
    )


def research_from_gaps(
    gaps: Iterable[Any],
    *,
    objective: str,
    languages: Iterable[str] = ("en", "ru"),
) -> ResearchPlan:
    """
    Turn analytical missing-data signals into a concrete research plan.
    """
    normalized_languages = choose_research_languages(
        preferred=languages
    )

    research_gaps: list[ResearchGap] = []
    directions: list[str] = []
    queries: list[ResearchQuery] = []

    for gap in gaps:
        if isinstance(gap, str):
            description = gap
            topic = None
            importance = 0.8
            suggested_method = "Собрать недостающие данные через доступный Research/Data источник."
        else:
            description = _get(gap, "description", "") or _get(
                gap, "reason", ""
            )
            topic = _get(gap, "topic")
            importance = _get(gap, "importance", 0.5)
            suggested_method = _get(gap, "suggested_method", "")
        if not description:
            continue

        research_gap = ResearchGap(
            description=str(description),
            importance=float(importance or 0.5),
            topic=topic,
            suggested_method=suggested_method,
        )

        research_gaps.append(research_gap)

        direction = topic or str(description)
        if direction not in directions:
            directions.append(direction)

        for language in normalized_languages:
            queries.append(
                build_query(
                    query=str(direction),
                    language=language,
                    purpose=str(description),
                    priority=(
                        ResearchPriority.HIGH
                        if research_gap.importance >= 0.7
                        else ResearchPriority.MEDIUM
                    ),
                )
            )

    return build_research_plan(
        objective=objective,
        directions=directions,
        queries=queries,
        gaps=research_gaps,
        languages=normalized_languages,
        priorities=["close_missing_data", "validate_signal"],
        reason=(
            "Исследование сформировано из пробелов в текущей доказательной базе."
        ),
    )


def plan_next_research(
    *,
    objective: str,
    missing_data: Iterable[Any] | None = None,
    current_topics: Iterable[str] | None = None,
    preferred_languages: Iterable[str] | None = None,
) -> ResearchPlan:
    """
    Main entry point for the Director's research strategy.
    """
    gaps = list(missing_data or [])

    if gaps:
        return research_from_gaps(
            gaps,
            objective=objective,
            languages=preferred_languages or ("en", "ru"),
        )

    topics = [
        str(x).strip()
        for x in (current_topics or [])
        if str(x).strip()
    ]

    languages = choose_research_languages(
        preferred=preferred_languages
    )

    queries = [
        build_query(
            query=topic,
            language=language,
            purpose="Проверить текущее состояние направления.",
        )
        for topic in topics
        for language in languages
    ]

    return build_research_plan(
        objective=objective,
        directions=topics,
        queries=queries,
        languages=languages,
        priorities=["explore"],
        reason=(
            "Явных пробелов не найдено; исследование направлено "
            "на проверку текущих направлений."
        ),
    )


def mark_running(plan: ResearchPlan) -> ResearchPlan:
    plan.status = ResearchStatus.RUNNING
    return plan


def mark_completed(plan: ResearchPlan) -> ResearchPlan:
    plan.status = ResearchStatus.COMPLETED
    return plan


def mark_blocked(
    plan: ResearchPlan,
    reason: str | None = None,
) -> ResearchPlan:
    plan.status = ResearchStatus.BLOCKED

    if reason:
        plan.metadata["blocked_reason"] = reason

    return plan


def research_to_dict(plan: ResearchPlan) -> dict[str, Any]:
    return plan.to_dict()
