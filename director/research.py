"""
Director research planning.

This module decides WHAT the Director will research next:
- which research languages to use;
- which concrete YouTube search queries to run.

It is a pure planning helper. It does not perform research,
does not store state and does not make strategic decisions.
All decisions remain in the Director flow.

Dependencies (quota status, AI availability, JSON generation,
event logging) are injected by the caller so that this module
stays free of server-level configuration and circular imports.
"""

from __future__ import annotations

import json
import logging

from datetime import datetime, timezone
from typing import Any, Callable


logger = logging.getLogger(
    "site-insight-engine"
)


def choose_director_research_languages(
    language: str | None = None,
    region_code: str | None = None,
    *,
    quota_status: dict[str, Any] | None = None,
) -> list[str]:

    # --------------------------------------------------------
    # AUTONOMOUS GLOBAL RESEARCH
    # --------------------------------------------------------

    available_languages = [
        "en",
        "hi",
        "zh",
        "ja",
        "ko",
        "es",
        "pt",
        "ar",
        "de",
        "fr",
        "it",
        "tr",
        "id",
        "vi",
        "th",
        "pl",
        "ru",
    ]

    # --------------------------------------------------------
    # MANUAL TARGETED RESEARCH
    # --------------------------------------------------------

    if language:
        return [language]

    # --------------------------------------------------------
    # QUOTA-AWARE LANGUAGE SELECTION
    # --------------------------------------------------------

    quota = (
        quota_status
        if isinstance(quota_status, dict)
        else {}
    )

    search_remaining = int(
        quota.get(
            "search_remaining",
            0,
        )
    )

    if search_remaining <= 0:
        return []

    day_number = (
        datetime.now(timezone.utc).timetuple().tm_yday
    )

    offset = day_number % len(
        available_languages
    )

    rotated = (
        available_languages[offset:]
        + available_languages[:offset]
    )

    return rotated


def choose_director_research_queries(
    language: str | None = None,
    previous_analysis: dict[str, Any] | None = None,
    *,
    ai_enabled: bool = True,
    generate_json: Callable[[str, str], dict[str, Any]] | None = None,
    log_event_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[str]:

    previous_analysis = (
        previous_analysis
        if isinstance(
            previous_analysis,
            dict,
        )
        else {}
    )

    prompt = json.dumps(
        {
            "task": (
                "Choose the YouTube research directions "
                "that the Director should investigate next."
            ),
            "language": language,
            "previous_analysis": previous_analysis,
            "rules": [
                (
                    "There is no fixed topic catalog."
                ),
                (
                    "Do not restrict research to predefined "
                    "topics."
                ),
                (
                    "You may choose completely new topics."
                ),
                (
                    "You may investigate adjacent topics."
                ),
                (
                    "You may investigate unrelated topics "
                    "when that is useful for discovering "
                    "new opportunities."
                ),
                (
                    "Queries must be concrete YouTube search "
                    "queries."
                ),
                (
                    "Use the previous analysis when it provides "
                    "useful evidence."
                ),
                (
                    "Do not assume that previous topics are "
                    "the only topics worth researching."
                ),
                (
                    "Do not recommend news."
                ),
                (
                    "Do not recommend politics."
                ),
                (
                    "Do not recommend 18+ content."
                ),
                (
                    "Do not recommend gore, torture, graphic "
                    "injury, glorification or incitement "
                    "of violence."
                ),
            ],
        },
        ensure_ascii=False,
        default=str,
    )

    system_instruction = """
You are the research-planning brain of an autonomous
AI Director for YouTube.

Your job is to decide what the Director should search
for next.

There is NO fixed topic catalog.

The Director must be able to discover completely new
topics, niches, formats, audience interests and emerging
content directions.

Previous research is evidence, not a restriction.

You may:
- continue a promising direction;
- investigate an adjacent direction;
- compare different niches;
- test a hypothesis;
- investigate a completely new subject;
- investigate a new format;
- investigate a new audience interest.

Do not recommend:
- news;
- politics;
- 18+ content;
- gore;
- torture;
- graphic injury;
- glorification or incitement of violence.

Return ONLY valid JSON in this structure:

{
  "queries": [
    "concrete YouTube search query"
  ]
}

Do not return explanations.
"""

    if not ai_enabled:
        return []

    if generate_json is None:
        raise RuntimeError(
            "generate_json dependency is not configured"
        )

    try:
        result = generate_json(
            system_instruction=system_instruction,
            prompt=prompt,
        )

    except Exception as exc:

        logger.warning(
            "DIRECTOR_QUERY_PLANNER_FAILED "
            "error_type=%s",
            type(exc).__name__,
        )

        if log_event_fn is not None:
            log_event_fn(
                "director_query_planner_failed",
                {
                    "error_type": type(exc).__name__,
                },
            )

        return []

    queries = result.get(
        "queries",
        [],
    )

    if not isinstance(
        queries,
        list,
    ):
        return []

    cleaned_queries = []

    for query in queries:

        if not isinstance(
            query,
            str,
        ):
            continue

        query = query.strip()

        if not query:
            continue

        if query not in cleaned_queries:
            cleaned_queries.append(
                query
            )

    return cleaned_queries
