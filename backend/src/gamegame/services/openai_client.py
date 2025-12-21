"""Shared OpenAI client with configured timeout."""

from openai import AsyncOpenAI

from gamegame.config import settings


def get_openai_client() -> AsyncOpenAI:
    """Get an AsyncOpenAI client with configured timeout.

    Returns:
        AsyncOpenAI client with timeout from settings.
    """
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout,
    )
