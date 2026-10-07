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


@dataclass(frozen=True)
class ResearchRequirement:
    """Concrete acquisition requirement derived from Director state."""

    key: str
    description: str
    priority: ResearchPriority
    count: int = 0
    needed_now: bool = True


_REQUIREMENT_OPERATIONS: dict[str, dict[str, Any]] = {
    "videos": {"operation": "search_videos", "target": "videos", "reuse": "reuse_existing_video_ids", "completion": "at least one relevant video is stored"},
    "video_snapshots": {"operation": "collect_video_snapshots", "target": "video_snapshots", "reuse": "reuse_existing_snapshots_and_only_collect_missing_history", "completion": "requested videos have usable metric history"},
    "queries": {"operation": "register_queries", "target": "queries", "reuse": "reuse_identical_query_definitions", "completion": "every executed query has a persisted query record"},
    "research_sets": {"operation": "register_research_set", "target": "research_sets", "reuse": "reuse_matching_completed_research", "completion": "the research plan has a persisted research-set record"},
    "relations": {"operation": "link_research_data", "target": "relations", "reuse": "reuse_existing_identical_relations", "completion": "research/query/result/data links are persisted"},
    "channels": {"operation": "collect_channels", "target": "channels", "reuse": "reuse_channels_already_known_from_videos", "completion": "channels for relevant videos are known"},
    "channel_snapshots": {"operation": "collect_channel_snapshots", "target": "channel_snapshots", "reuse": "reuse_existing_snapshots_and_only_collect_missing_history", "completion": "target channels have requested historical observations"},
    "niches": {"operation": "collect_niche_evidence", "target": "niches", "reuse": "reuse_existing_niche_entities", "completion": "candidate niche evidence is collected; Director owns strategic niche decisions"},
    "niche_snapshots": {"operation": "build_niche_snapshots", "target": "niche_snapshots", "reuse": "reuse_existing_historical_aggregates", "completion": "niche history can be derived from video/channel evidence"},
}


def _requirement_from_mapping(value: Any) -> ResearchRequirement | None:
    if not isinstance(value, dict):
        return None
    key = str(value.get("key") or "").strip()
    if key not in _REQUIREMENT_OPERATIONS:
        return None
    try:
        priority = ResearchPriority(str(value.get("priority") or "medium"))
    except ValueError:
        priority = ResearchPriority.MEDIUM
    return ResearchRequirement(
        key=key,
        description=str(value.get("description") or "").strip(),
        priority=priority,
        count=int(value.get("count") or 0),
        needed_now=bool(value.get("needed_now", True)),
    )


def plan_from_requirements(
    *,
    objective: str,
    requirements: Iterable[Any],
    context: dict[str, Any] | None = None,
    preferred_languages: Iterable[str] | None = None,
) -> ResearchPlan:
    """Translate Director requirements into explicit acquisition operations."""
    normalized = [
        item
        for item in (_requirement_from_mapping(value) for value in requirements)
        if item is not None and item.needed_now
    ]
    languages = choose_research_languages(preferred=preferred_languages)
    context = dict(context or {})
    topics = context.get("topics", {})
    topic_values: list[str] = []
    if isinstance(topics, dict):
        values = topics.get("topics", topics.get("items", []))
        if isinstance(values, dict):
            values = values.values()
        for item in values or []:
            if isinstance(item, str) and item.strip():
                topic_values.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("topic") or item.get("title")
                if name:
                    topic_values.append(str(name).strip())

    directions: list[str] = []
    queries: list[ResearchQuery] = []
    operations: list[dict[str, Any]] = []

    for item in normalized:
        spec = _REQUIREMENT_OPERATIONS[item.key]
        operations.append({
            "requirement_key": item.key,
            **spec,
            "available_count": item.count,
        })
        direction = item.key
        if topic_values and item.key in {"videos", "channels", "niches"}:
            direction = f"{item.key}: " + ", ".join(topic_values[:8])
        directions.append(direction)

        # This is deliberately a structured command, not a prose sentence.
        # The future MCP adapter consumes operation/data_targets metadata.
        query_text = (
            ", ".join(topic_values[:8])
            if topic_values and item.key in {"videos", "channels", "niches"}
            else item.key
        )
        metadata = {
            "operation": spec["operation"],
            "data_targets": [spec["target"]],
            "reuse_policy": spec["reuse"],
            "completion_criterion": spec["completion"],
            "requirement_key": item.key,
            "count_already_available": item.count,
            "needed_now": item.needed_now,
            "objective": objective,
        }
        for language in languages:
            queries.append(build_query(
                query=query_text,
                language=language,
                purpose=item.description,
                priority=item.priority,
                metadata=metadata,
            ))

    gaps = [
        ResearchGap(
            description=item.description,
            importance=1.0 if item.priority == ResearchPriority.CRITICAL else (0.8 if item.priority == ResearchPriority.HIGH else 0.5),
            suggested_method=_REQUIREMENT_OPERATIONS[item.key]["operation"],
        )
        for item in normalized
    ]

    return build_research_plan(
        objective=objective,
        directions=directions,
        queries=queries,
        gaps=gaps,
        languages=languages,
        priorities=["close_missing_data", "reuse_existing_data", "validate_signal"],
        reason="Research converted Director data requirements into explicit acquisition operations.",
        metadata={
            "operations": operations,
            "requirements": [asdict(item) for item in normalized],
            "determination_complete": True,
            "next_stage": "execute_operations",
        },
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

class ResearchService:
    """
    Research layer entry point.

    Director sends the research objective and current context here.
    This service owns translation of missing-data signals into a
    ResearchPlan. Data acquisition is intentionally handled separately.
    """

    def plan(
        self,
        *,
        objective: str,
        context: dict[str, Any] | None = None,
    ) -> ResearchPlan:
        context = dict(context or {})

        metadata = context.get("metadata", {})
        preferred_languages = metadata.get("preferred_languages", [])
        requirements = metadata.get("data_requirements", [])

        # Prefer the Director's structured requirements. String gaps remain
        # supported for compatibility with older callers.
        if isinstance(requirements, list) and requirements:
            return plan_from_requirements(
                objective=objective,
                requirements=requirements,
                context=context,
                preferred_languages=(preferred_languages or None),
            )

        missing_data = context.get("missing_data", [])

        current_topics = []
        topics = context.get("topics", {})

        if isinstance(topics, dict):
            values = topics.get("topics", topics.get("items", []))
            if isinstance(values, dict):
                values = values.values()

            for item in values or []:
                if isinstance(item, str):
                    current_topics.append(item)
                elif isinstance(item, dict):
                    name = (
                        item.get("name")
                        or item.get("topic")
                        or item.get("title")
                    )
                    if name:
                        current_topics.append(str(name))

        return plan_next_research(
            objective=objective,
            missing_data=missing_data,
            current_topics=current_topics,
            preferred_languages=(
                preferred_languages or None
            ),
        )
\n