"""Resilience patterns for external API calls (retry, circuit breaker)."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import ParamSpec, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


# Exceptions that should trigger retry
RETRYABLE_EXCEPTIONS = (
    asyncio.TimeoutError,
    ConnectionError,
    OSError,
)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """Simple circuit breaker implementation.

    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, reject requests immediately
    - HALF_OPEN: Testing if service recovered, allow limited requests
    """

    name: str
    failure_threshold: int = 5  # Failures before opening
    recovery_timeout: float = 30.0  # Seconds before trying again
    half_open_max_calls: int = 3  # Calls to test in half-open state

    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    failure_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)
    half_open_calls: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def call(
        self,
        func: Callable[P, Awaitable[T]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """Execute function with circuit breaker protection."""
        async with self._lock:
            await self._check_state()

            if self.state == CircuitState.OPEN:
                raise CircuitOpenError(f"Circuit breaker '{self.name}' is open")

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure(e)
            raise

    async def _check_state(self) -> None:
        """Check if circuit should transition states."""
        if (
            self.state == CircuitState.OPEN
            and time.time() - self.last_failure_time >= self.recovery_timeout
        ):
            logger.info(f"Circuit '{self.name}' transitioning to half-open")
            self.state = CircuitState.HALF_OPEN
            self.half_open_calls = 0

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.half_open_calls += 1
                if self.half_open_calls >= self.half_open_max_calls:
                    logger.info(f"Circuit '{self.name}' recovered, closing")
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
            elif self.state == CircuitState.CLOSED:
                # Reset failure count on success
                self.failure_count = 0

    async def _on_failure(self, error: Exception) -> None:
        """Handle failed call."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                logger.warning(f"Circuit '{self.name}' failed in half-open, reopening")
                self.state = CircuitState.OPEN
            elif self.failure_count >= self.failure_threshold:
                logger.warning(
                    f"Circuit '{self.name}' opened after {self.failure_count} failures: {error}"
                )
                self.state = CircuitState.OPEN

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_calls = 0


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass


# Global circuit breakers for external services
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name=name)
    return _circuit_breakers[name]


# Pre-configured circuit breakers
openai_circuit = get_circuit_breaker("openai")
mistral_circuit = get_circuit_breaker("mistral")


async def with_retry(
    func: Callable[P, Awaitable[T]],
    *args: P.args,
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 10.0,
    **kwargs: P.kwargs,
) -> T:  # type: ignore[return-value]
    """Execute an async function with exponential backoff retry.

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        max_attempts: Maximum retry attempts
        min_wait: Minimum wait between retries (seconds)
        max_wait: Maximum wait between retries (seconds)
        **kwargs: Keyword arguments for func

    Returns:
        Result from func

    Raises:
        The last exception if all retries fail
    """
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
        ):
            with attempt:
                return await func(*args, **kwargs)
    except RetryError:
        raise  # Re-raise the last exception


def with_resilience(
    circuit_breaker: CircuitBreaker | None = None,
    max_retries: int = 3,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator that adds retry and circuit breaker to an async function.

    Args:
        circuit_breaker: Optional circuit breaker to use
        max_retries: Maximum retry attempts

    Example:
        @with_resilience(circuit_breaker=openai_circuit)
        async def call_openai(...):
            ...
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            async def wrapped() -> T:
                return await with_retry(func, *args, max_attempts=max_retries, **kwargs)  # type: ignore[arg-type]

            if circuit_breaker:
                return await circuit_breaker.call(wrapped)
            return await wrapped()

        return wrapper

    return decorator
