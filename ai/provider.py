# ai/provider.py
"""
AI provider abstraction for the AI Director.

Responsibilities:
- provide a unified interface for AI models;
- support text and structured JSON generation;
- normalize provider responses;
- expose model/provider metadata;
- handle provider-level errors.

This module does NOT:
- make strategic decisions;
- create Director recommendations;
- access YouTube;
- access Supabase;
- decide which model should be used for a specific business action.

Director decides WHAT needs to be done.
AIProvider decides HOW to ask an AI model to do it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
from typing import Any, Mapping, Sequence

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AIProviderError(RuntimeError):
    """Base error for AI provider failures."""


class AIProviderConfigurationError(AIProviderError):
    """Provider is not configured correctly."""


class AIProviderRequestError(AIProviderError):
    """Provider request failed."""


class AIProviderResponseError(AIProviderError):
    """Provider returned an invalid or unusable response."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AIMessage:
    role: str
    content: str


@dataclass(slots=True)
class AIRequest:
    messages: list[AIMessage]

    model: str | None = None

    temperature: float = 0.2
    max_tokens: int | None = None

    response_format: dict[str, Any] | None = None

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AIResponse:
    content: str

    provider: str
    model: str

    usage: dict[str, Any] = field(default_factory=dict)

    raw: dict[str, Any] = field(default_factory=dict)

    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class AIProvider(ABC):
    """
    Abstract AI provider.

    Director and other application modules should depend on this interface,
    not on OpenRouter, OpenAI, Anthropic, etc.
    """

    name: str = "unknown"

    @abstractmethod
    async def generate(
        self,
        request: AIRequest,
    ) -> AIResponse:
        """
        Generate a response from an AI model.
        """
        raise NotImplementedError

    async def generate_text(
        self,
        messages: Sequence[AIMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AIResponse:
        request = AIRequest(
            messages=list(messages),
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=dict(metadata or {}),
        )

        return await self.generate(request)

    async def generate_json(
        self,
        messages: Sequence[AIMessage],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = AIRequest(
            messages=list(messages),
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={
                "type": "json_object",
            },
            metadata=dict(metadata or {}),
        )

        response = await self.generate(request)

        return parse_json_response(response.content)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def extract_json_text(text: str) -> str:
    """
    Extract JSON from a model response.

    Handles:
    - plain JSON;
    - ```json ... ``` blocks;
    - text surrounding a JSON object.
    """

    content = (text or "").strip()

    if not content:
        raise AIProviderResponseError(
            "AI returned an empty response."
        )

    if content.startswith("```"):
        lines = content.splitlines()

        if len(lines) >= 3:
            first = lines[0].strip().lower()

            if first in {"```json", "```"}:
                content = "\n".join(lines[1:-1]).strip()

    try:
        json.loads(content)
        return content
    except json.JSONDecodeError:
        pass

    start = content.find("{")
    end = content.rfind("}")

    if start >= 0 and end > start:
        candidate = content[start : end + 1]

        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    raise AIProviderResponseError(
        "AI response does not contain valid JSON."
    )


def parse_json_response(
    text: str,
) -> dict[str, Any]:
    json_text = extract_json_text(text)

    try:
        value = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise AIProviderResponseError(
            f"Failed to decode AI JSON response: {exc}"
        ) from exc

    if not isinstance(value, dict):
        raise AIProviderResponseError(
            "AI JSON response must be an object."
        )

    return value


# ---------------------------------------------------------------------------
# OpenRouter implementation
# ---------------------------------------------------------------------------


class OpenRouterProvider(AIProvider):
    """
    OpenRouter implementation of AIProvider.

    OpenRouter remains an infrastructure detail.
    Director does not need to know that it is being used.
    """

    name = "openrouter"

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "openai/gpt-4o-mini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        app_name: str = "AI Director",
        app_url: str | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
        )

        self.model = (
            model
            or os.getenv("OPENROUTER_MODEL")
            or self.DEFAULT_MODEL
        )

        self.base_url = (
            base_url
            or os.getenv("OPENROUTER_BASE_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")

        self.timeout = timeout

        self.app_name = app_name
        self.app_url = app_url

    def _validate_configuration(self) -> None:
        if not self.api_key:
            raise AIProviderConfigurationError(
                "OPENROUTER_API_KEY is not configured."
            )

        if httpx is None:
            raise AIProviderConfigurationError(
                "httpx is required for OpenRouterProvider."
            )

    def _build_payload(
        self,
        request: AIRequest,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in request.messages
            ],
            "temperature": request.temperature,
        }

        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        if request.response_format is not None:
            payload["response_format"] = request.response_format

        return payload

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if self.app_name:
            headers["X-Title"] = self.app_name

        if self.app_url:
            headers["HTTP-Referer"] = self.app_url

        return headers

    @staticmethod
    def _extract_content(
        payload: Mapping[str, Any],
    ) -> str:
        choices = payload.get("choices")

        if not isinstance(choices, list) or not choices:
            raise AIProviderResponseError(
                "OpenRouter response contains no choices."
            )

        first = choices[0]

        if not isinstance(first, Mapping):
            raise AIProviderResponseError(
                "Invalid OpenRouter choice."
            )

        message = first.get("message")

        if not isinstance(message, Mapping):
            raise AIProviderResponseError(
                "OpenRouter response contains no message."
            )

        content = message.get("content")

        if content is None:
            raise AIProviderResponseError(
                "OpenRouter message contains no content."
            )

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []

            for item in content:
                if isinstance(item, Mapping):
                    text = item.get("text")

                    if text:
                        parts.append(str(text))

            return "".join(parts).strip()

        return str(content).strip()

    async def generate(
        self,
        request: AIRequest,
    ) -> AIResponse:
        self._validate_configuration()

        payload = self._build_payload(request)
        headers = self._build_headers()

        url = f"{self.base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                )

        except Exception as exc:
            raise AIProviderRequestError(
                f"OpenRouter request failed: {exc}"
            ) from exc

        if response.status_code >= 400:
            try:
                error_payload = response.json()
            except Exception:
                error_payload = {
                    "text": response.text,
                }

            raise AIProviderRequestError(
                "OpenRouter returned HTTP "
                f"{response.status_code}: "
                f"{error_payload}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise AIProviderResponseError(
                "OpenRouter returned invalid JSON."
            ) from exc

        if not isinstance(data, Mapping):
            raise AIProviderResponseError(
                "OpenRouter response must be an object."
            )

        content = self._extract_content(data)

        usage = data.get("usage")

        if not isinstance(usage, Mapping):
            usage = {}

        return AIResponse(
            content=content,
            provider=self.name,
            model=str(
                data.get(
                    "model",
                    request.model or self.model,
                )
            ),
            usage=dict(usage),
            raw=dict(data),
            metadata=dict(request.metadata),
        )


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


def create_ai_provider(
    *,
    provider: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> AIProvider:
    """
    Create the configured AI provider.

    Currently supported:
    - openrouter
    """

    provider_name = (
        provider
        or os.getenv("AI_PROVIDER")
        or os.getenv("DIRECTOR_AI_PROVIDER")
        or "openrouter"
    ).strip().lower()

    if provider_name == "openrouter":
        return OpenRouterProvider(
            model=model,
            **kwargs,
        )

    raise AIProviderConfigurationError(
        f"Unsupported AI provider: {provider_name}"
    )


__all__ = [
    "AIProvider",
    "AIMessage",
    "AIRequest",
    "AIResponse",
    "AIProviderError",
    "AIProviderConfigurationError",
    "AIProviderRequestError",
    "AIProviderResponseError",
    "OpenRouterProvider",
    "create_ai_provider",
    "extract_json_text",
    "parse_json_response",
]
