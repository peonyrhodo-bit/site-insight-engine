from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class AIResponse:
    text: str
    provider: str
    model: str | None = None
    usage: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class AIProvider(Protocol):
    name: str

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AIResponse:
        ...


class ProviderRouter:
    def __init__(
        self,
        providers: dict[str, AIProvider] | None = None,
        default_provider: str | None = None,
    ) -> None:
        self.providers: dict[str, AIProvider] = providers or {}

        self.default_provider = (
            default_provider
            or os.environ.get("AI_PROVIDER")
            or "local"
        )

    def register(self, provider: AIProvider) -> None:
        name = getattr(provider, "name", None)

        if not name:
            raise ValueError(
                "AI provider должен иметь атрибут 'name'"
            )

        self.providers[name] = provider

    def get_provider(
        self,
        provider_name: str | None = None,
    ) -> AIProvider:
        name = provider_name or self.default_provider

        provider = self.providers.get(name)

        if provider is None:
            available = ", ".join(
                sorted(self.providers.keys())
            )

            raise RuntimeError(
                f"AI provider '{name}' не зарегистрирован. "
                f"Доступные providers: {available or 'нет'}"
            )

        return provider

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AIResponse:
        if not prompt or not prompt.strip():
            raise ValueError(
                "AI prompt не может быть пустым"
            )

        selected_provider = self.get_provider(provider)

        return selected_provider.generate(
            prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def run_task(
        self,
        task: str,
        prompt: str,
        *,
        system_prompt: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AIResponse:
        response = self.generate(
            prompt,
            system_prompt=system_prompt,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if response.metadata is None:
            response.metadata = {}

        response.metadata["task"] = task

        return response

    def list_providers(self) -> list[str]:
        return sorted(self.providers.keys())

    def status(self) -> dict[str, Any]:
        return {
            "default_provider": self.default_provider,
            "providers": self.list_providers(),
            "provider_count": len(self.providers),
        }


def create_router() -> ProviderRouter:
    return ProviderRouter()


router = create_router()


def generate(
    prompt: str,
    *,
    system_prompt: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> AIResponse:
    return router.generate(
        prompt,
        system_prompt=system_prompt,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
