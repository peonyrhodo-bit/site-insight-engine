import os

from local_ai import local_generate


FREE_MODE = os.getenv("FREE_MODE", "true").lower() == "true"


async def generate_text(
    prompt: str,
    provider: str = "auto",
    **kwargs,
):
    if provider == "local":
        return await local_generate(
            prompt=prompt,
            **kwargs,
        )

    if provider == "auto":
        if FREE_MODE:
            return await local_generate(
                prompt=prompt,
                **kwargs,
            )

    raise RuntimeError(
        f"No provider available for text generation: {provider}"
    )


async def generate(
    task: str,
    prompt: str,
    provider: str = "auto",
    **kwargs,
):
    if task == "text":
        return await generate_text(
            prompt=prompt,
            provider=provider,
            **kwargs,
        )

    raise ValueError(
        f"Unsupported AI task: {task}"
    )
