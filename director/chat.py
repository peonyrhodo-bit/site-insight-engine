"""
Director chat control layer.

Chat is an interface to the Director, not a separate intelligence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from .language import format_user_message


class ChatIntent(str, Enum):
    RESEARCH = "research"
    ANALYZE = "analyze"
    RECOMMEND = "recommend"
    ACCEPT = "accept"
    REJECT = "reject"
    MODIFY = "modify"
    PRIORITIZE = "prioritize"
    STATUS = "status"
    CONTINUE = "continue"
    STOP = "stop"
    CLARIFY = "clarify"
    UNKNOWN = "unknown"


@dataclass
class ChatCommand:
    command_id: str
    intent: ChatIntent
    message: str
    target: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatResult:
    command: ChatCommand
    handled: bool
    action: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def detect_intent(message: str) -> ChatIntent:
    text = format_user_message(message).lower()

    if not text:
        return ChatIntent.UNKNOWN

    if _contains_any(
        text,
        (
            "прими",
            "принимаю",
            "да, делаем",
            "согласна",
            "одобряю",
            "берём",
            "берем",
        ),
    ):
        return ChatIntent.ACCEPT

    if _contains_any(
        text,
        (
            "отклон",
            "не хочу",
            "не надо",
            "не делаем",
            "не подходит",
            "не нравится",
        ),
    ):
        return ChatIntent.REJECT

    if _contains_any(
        text,
        (
            "исследуй",
            "исследование",
            "поищи",
            "изучи",
            "посмотри youtube",
            "проверь рынок",
        ),
    ):
        return ChatIntent.RESEARCH

    if _contains_any(
        text,
        (
            "проанализируй",
            "анализ",
            "сравни",
            "посчитай",
            "разбери",
        ),
    ):
        return ChatIntent.ANALYZE

    if _contains_any(
        text,
        (
            "рекоменд",
            "что предлагаешь",
            "что делать",
            "что попробовать",
            "какую нишу",
            "какое направление",
        ),
    ):
        return ChatIntent.RECOMMEND

    if _contains_any(
        text,
        (
            "приоритет",
            "важнее",
            "сделай главным",
            "сфокусируйся",
        ),
    ):
        return ChatIntent.PRIORITIZE

    if _contains_any(
        text,
        (
            "статус",
            "что происходит",
            "где мы",
            "что уже сделал",
        ),
    ):
        return ChatIntent.STATUS

    if _contains_any(
        text,
        (
            "продолжай",
            "продолжить",
            "дальше",
            "работай дальше",
        ),
    ):
        return ChatIntent.CONTINUE

    if _contains_any(
        text,
        (
            "остановись",
            "стоп",
            "остановить",
            "не продолжай",
        ),
    ):
        return ChatIntent.STOP

    if _contains_any(
        text,
        (
            "уточни",
            "что ты имеешь в виду",
            "объясни",
        ),
    ):
        return ChatIntent.CLARIFY

    return ChatIntent.UNKNOWN


def parse_chat_command(
    message: str,
    *,
    target: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> ChatCommand:
    intent = detect_intent(message)

    confidence = {
        ChatIntent.UNKNOWN: 0.30,
        ChatIntent.RESEARCH: 0.90,
        ChatIntent.ANALYZE: 0.90,
        ChatIntent.RECOMMEND: 0.85,
        ChatIntent.ACCEPT: 0.95,
        ChatIntent.REJECT: 0.95,
        ChatIntent.MODIFY: 0.70,
        ChatIntent.PRIORITIZE: 0.80,
        ChatIntent.STATUS: 0.95,
        ChatIntent.CONTINUE: 0.95,
        ChatIntent.STOP: 0.95,
        ChatIntent.CLARIFY: 0.90,
    }[intent]

    return ChatCommand(
        command_id=f"cmd_{uuid4().hex[:12]}",
        intent=intent,
        message=format_user_message(message),
        target=target,
        parameters=dict(parameters or {}),
        confidence=confidence,
    )


def command_to_action(command: ChatCommand) -> str:
    mapping = {
        ChatIntent.RESEARCH: "start_research",
        ChatIntent.ANALYZE: "run_analysis",
        ChatIntent.RECOMMEND: "generate_recommendation",
        ChatIntent.ACCEPT: "accept_recommendation",
        ChatIntent.REJECT: "reject_recommendation",
        ChatIntent.MODIFY: "modify_recommendation",
        ChatIntent.PRIORITIZE: "change_priority",
        ChatIntent.STATUS: "inspect_state",
        ChatIntent.CONTINUE: "continue_cycle",
        ChatIntent.STOP: "stop_cycle",
        ChatIntent.CLARIFY: "ask_clarification",
        ChatIntent.UNKNOWN: "ask_clarification",
    }

    return mapping[command.intent]


async def execute_chat_command(
    command: ChatCommand,
    *,
    handlers: dict[str, Any] | None = None,
) -> ChatResult:
    """
    Dispatch a parsed command to Director-owned handlers.

    Handlers are injected so chat does not know implementation details.
    Async handlers are awaited.
    """
    action = command_to_action(command)
    handlers = handlers or {}

    handler = handlers.get(action)

    if handler is None:
        return ChatResult(
            command=command,
            handled=False,
            action=action,
            message=(
                "Я понял направление запроса, но это действие "
                "ещё не подключено к текущему циклу."
            ),
        )

    try:
        result = handler(command)

        if hasattr(result, "__await__"):
            result = await result

        if isinstance(result, ChatResult):
            return result

        if isinstance(result, dict):
            return ChatResult(
                command=command,
                handled=True,
                action=action,
                message=str(
                    result.get(
                        "message",
                        "Действие выполнено.",
                    )
                ),
                data=result,
            )

        return ChatResult(
            command=command,
            handled=True,
            action=action,
            message=str(result or "Действие выполнено."),
        )

    except Exception as exc:
        return ChatResult(
            command=command,
            handled=False,
            action=action,
            message=f"Не удалось выполнить действие: {exc}",
        )
