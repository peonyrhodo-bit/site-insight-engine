import os
from typing import Any


LOCAL_LLM_URL = os.getenv(
    "LOCAL_LLM_URL",
    "",
)


async def local_generate(
    prompt: str,
    **kwargs: Any,
) -> str:

    if not LOCAL_LLM_URL:
        raise RuntimeError(
            "LOCAL_LLM_URL is not configured"
        )

    try:
        import httpx
    except ImportError as error:
        raise RuntimeError(
            "httpx is required for local AI"
        ) from error

    payload = {
        "prompt": prompt,
        **kwargs,
    }

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            LOCAL_LLM_URL,
            json=payload,
        )

        response.raise_for_status()

        data = response.json()

    if isinstance(data, str):
        return data

    if isinstance(data, dict):
        for key in (
            "response",
            "text",
            "content",
            "output",
        ):
            if key in data:
                return str(data[key])

    raise RuntimeError(
        "Local AI returned an unsupported response"
    )
