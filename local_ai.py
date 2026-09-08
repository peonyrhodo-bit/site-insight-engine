from __future__ import annotations

import os
from typing import Any

import requests

from provider_router import AIResponse


class LocalAI:
    """
    Адаптер локальной AI-модели через Ollama.

    Provider Router работает с LocalAI через единый интерфейс.
    """

    name = "local"

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get(
                "LOCAL_AI_URL",
                "http://localhost:11434",
            )
        ).rstrip("/")

        self.default_model = (
            default_model
            or os.environ.get(
                "LOCAL_AI_MODEL",
                "llama3.2",
            )
        )

        self.timeout = timeout or int(
            os.environ.get(
                "LOCAL_AI_TIMEOUT",
                "120",
            )
        )

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AIResponse:
        if not prompt or not prompt.strip():
            raise ValueError(
                "AI prompt не может быть пустым"
            )

        selected_model = model or self.default_model

        messages: list[dict[str, str]] = []

        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        options: dict[str, Any] = {
            "temperature": temperature,
        }

        if max_tokens is not None:
            options["num_predict"] = max_tokens

        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "options": options,
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )

            response.raise_for_status()

        except requests.RequestException as error:
            raise RuntimeError(
                f"Ошибка подключения к Local AI: {error}"
            ) from error

        try:
            data = response.json()

        except ValueError as error:
            raise RuntimeError(
                "Local AI вернула некорректный JSON"
            ) from error

        message = data.get("message", {})
        text = message.get("content")

        if not text:
            raise RuntimeError(
                "Local AI не вернула текстовый ответ"
            )

        usage = {
            key: data[key]
            for key in (
                "prompt_eval_count",
                "eval_count",
                "total_duration",
                "load_duration",
            )
            if key in data
        }

        return AIResponse(
            text=text,
            provider=self.name,
            model=selected_model,
            usage=usage or None,
            metadata={
                "base_url": self.base_url,
            },
        )

    def health(self) -> dict[str, Any]:
        """
        Проверка доступности Local AI.
        """

        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=10,
            )

            response.raise_for_status()

            data = response.json()

            models = [
                model.get("name")
                for model in data.get("models", [])
                if model.get("name")
            ]

            return {
                "available": True,
                "url": self.base_url,
                "models": models,
            }

        except (requests.RequestException, ValueError) as error:
            return {
                "available": False,
                "url": self.base_url,
                "models": [],
                "error": str(error),
            }


def create_local_ai() -> LocalAI:
    return LocalAI()


local_ai = create_local_ai()
