"""
Topic analytics extension point.

This module intentionally contains only lightweight topic helpers.

Analytics calculates signals.
Director interprets those signals and makes strategic decisions.

Do not put strategy or recommendation logic here.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


def normalize_topic(topic: Any) -> str | None:
    """
    Normalize a topic value for analytical grouping.
    """

    if topic is None:
        return None

    value = str(topic).strip()

    if not value:
        return None

    return value


def collect_topic_counts(
    topics: Iterable[Any],
) -> dict[str, int]:
    """
    Count normalized topics.

    This is descriptive analytics only.
    """

    counter: Counter[str] = Counter()

    for topic in topics:
        normalized = normalize_topic(topic)

        if normalized is not None:
            counter[normalized] += 1

    return dict(counter)


def extract_topics_from_records(
    records: Iterable[dict[str, Any]],
) -> list[str]:
    """
    Extract explicit topic fields from already collected records.

    No topic inference or strategic ranking is performed here.
    """

    result: list[str] = []

    for record in records:
        if not isinstance(record, dict):
            continue

        topic = normalize_topic(
            record.get("topic")
        )

        if topic is not None:
            result.append(topic)

    return result


def summarize_topics(
    records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """
    Produce a small descriptive topic summary.
    """

    topics = extract_topics_from_records(records)
    counts = collect_topic_counts(topics)

    return {
        "topics": list(counts.keys()),
        "counts": counts,
        "total_records_with_topics": len(topics),
    }
