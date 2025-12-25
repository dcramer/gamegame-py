"""Shared OpenAI client with configured timeout and resilience."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from gamegame.config import settings
from gamegame.services.resilience import CircuitOpenError, openai_circuit

logger = logging.getLogger(__name__)

# OpenAI-specific retryable exceptions
OPENAI_RETRYABLE = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
)


def get_openai_client() -> AsyncOpenAI:
    """Get an AsyncOpenAI client with configured timeout.

    Returns:
        AsyncOpenAI client with timeout from settings.
    """
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout,
    )


async def create_chat_completion(
    messages: list[dict[str, Any]],
    model: str = "gpt-4o-mini",
    temperature: float = 1.0,  # GPT-5 requires temperature 1.0
    max_tokens: int | None = None,
    **kwargs: Any,
) -> ChatCompletion:
    """Create a chat completion with retry and circuit breaker.

    Args:
        messages: List of chat messages
        model: Model to use
        temperature: Sampling temperature
        max_tokens: Maximum tokens in response
        **kwargs: Additional arguments for OpenAI API

    Returns:
        ChatCompletion response

    Raises:
        CircuitOpenError: If OpenAI circuit breaker is open
        OpenAI exceptions: If all retries fail
    """

    async def _call() -> ChatCompletion:
        client = get_openai_client()
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(OPENAI_RETRYABLE),
            reraise=True,
        ):
            with attempt:
                return await client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
        raise RuntimeError("Unreachable")  # For type checker

    return await openai_circuit.call(_call)


async def create_chat_completion_stream(
    messages: list[dict[str, Any]],
    model: str = "gpt-4o-mini",
    temperature: float = 1.0,  # GPT-5 requires temperature 1.0
    max_tokens: int | None = None,
    **kwargs: Any,
) -> AsyncIterator[ChatCompletionChunk]:
    """Create a streaming chat completion with circuit breaker.

    Note: Streaming doesn't support retry mid-stream, but we use
    circuit breaker to fail fast if OpenAI is down.

    Args:
        messages: List of chat messages
        model: Model to use
        temperature: Sampling temperature
        max_tokens: Maximum tokens in response
        **kwargs: Additional arguments for OpenAI API

    Yields:
        ChatCompletionChunk events

    Raises:
        CircuitOpenError: If OpenAI circuit breaker is open
    """
    # Check circuit before starting stream
    if openai_circuit.state.value == "open":
        raise CircuitOpenError("OpenAI circuit breaker is open")

    client = get_openai_client()
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            yield chunk
        await openai_circuit._on_success()
    except OPENAI_RETRYABLE as e:
        await openai_circuit._on_failure(e)
        raise


async def create_embedding(
    text: str | list[str],
    model: str = "text-embedding-3-small",
) -> list[list[float]]:
    """Create embeddings with retry and circuit breaker.

    Args:
        text: Text or list of texts to embed
        model: Embedding model to use

    Returns:
        List of embedding vectors

    Raises:
        CircuitOpenError: If OpenAI circuit breaker is open
        OpenAI exceptions: If all retries fail
    """
    texts = [text] if isinstance(text, str) else text

    async def _call() -> list[list[float]]:
        client = get_openai_client()
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(OPENAI_RETRYABLE),
            reraise=True,
        ):
            with attempt:
                response = await client.embeddings.create(
                    model=model,
                    input=texts,
                )
                return [item.embedding for item in response.data]
        raise RuntimeError("Unreachable")  # For type checker

    return await openai_circuit.call(_call)
