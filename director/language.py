"""
Director language policy.

Valery communicates with the user in Russian.
Original YouTube titles, channel names and other source text must not
be translated or altered.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


DIRECTOR_LANGUAGE = "ru"

DIRECTOR_LANGUAGE_RULE = """
Все пользовательские сообщения, решения, рекомендации, объяснения,
вопросы и отчёты Директора должны быть на русском языке.

Оригинальные названия YouTube-видео, каналов, авторов, поисковых запросов
и другие исходные данные нельзя переводить или изменять.
"""


@dataclass(frozen=True)
class LanguagePolicy:
    language: str = "ru"
    preserve_original_titles: bool = True
    preserve_source_names: bool = True


POLICY = LanguagePolicy()


def is_russian_text(text: str) -> bool:
    """
    Heuristic check only.

    This is not intended as a linguistic classifier. It simply helps detect
    accidental English fallback in user-facing Director output.
    """
    if not text or not text.strip():
        return True

    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))

    if latin == 0:
        return True

    return cyrillic >= latin * 0.25


def ensure_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def ensure_russian_fallback(text: str, fallback: str) -> str:
    """
    Prevent empty/non-user-facing fallback from leaking into the UI.

    This does not translate text automatically. It only replaces an empty
    or obviously accidental fallback.
    """
    value = ensure_text(text)

    if not value:
        return fallback

    return value


def preserve_original(value: Any) -> str:
    """
    Return source text unchanged except for surrounding whitespace.
    """
    return ensure_text(value)


def format_source_title(title: Any) -> str:
    """
    Titles from YouTube/source data are never translated.
    """
    return preserve_original(title)


def format_user_message(text: Any) -> str:
    """
    Normalizes only presentation whitespace.
    Does not translate content.
    """
    value = ensure_text(text)
    return re.sub(r"\n{3,}", "\n\n", value)


def format_list(items: Iterable[Any], bullet: str = "• ") -> str:
    values = []

    for item in items:
        value = ensure_text(item)
        if value:
            values.append(f"{bullet}{value}")

    return "\n".join(values)


def build_director_message(
    *,
    summary: str,
    details: Iterable[str] | None = None,
    next_step: str | None = None,
) -> str:
    """
    Build concise user-facing Director communication.

    The Director should communicate decisions and useful conclusions,
    not expose internal orchestration.
    """
    parts: list[str] = []

    summary = ensure_text(summary)
    if summary:
        parts.append(summary)

    if details:
        detail_text = format_list(details)
        if detail_text:
            parts.append(detail_text)

    next_step = ensure_text(next_step)
    if next_step:
        parts.append(f"Следующий шаг: {next_step}")

    return "\n\n".join(parts).strip()


def protect_original_titles(
    text: str,
    original_titles: Iterable[str] | None = None,
) -> str:
    """
    Semantic protection hook.

    The current implementation intentionally does not rewrite text.
    It exists so a stronger protection layer can be introduced later
    without changing Director contracts.
    """
    return ensure_text(text)
