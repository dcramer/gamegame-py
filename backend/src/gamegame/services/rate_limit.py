"""Rate limiting service using sliding window algorithm."""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from fastapi import Request


class RateLimitType(str, Enum):
    """Rate limit types for different endpoint categories."""

    CHAT = "chat"
    SEARCH = "search"
    UPLOAD = "upload"
    API = "api"
    AUTH = "auth"
    BGG = "bgg"


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit type."""

    requests: int
    window_seconds: int


# Rate limit configuration per type
# Auth endpoints have stricter limits to prevent brute force
RATE_LIMIT_CONFIG: dict[RateLimitType, RateLimitConfig] = {
    RateLimitType.CHAT: RateLimitConfig(requests=20, window_seconds=60),
    RateLimitType.SEARCH: RateLimitConfig(requests=30, window_seconds=60),
    RateLimitType.UPLOAD: RateLimitConfig(requests=10, window_seconds=60),
    RateLimitType.API: RateLimitConfig(requests=60, window_seconds=60),
    RateLimitType.AUTH: RateLimitConfig(requests=10, window_seconds=60),  # Stricter for auth
    RateLimitType.BGG: RateLimitConfig(requests=10, window_seconds=60),
}


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    success: bool
    limit: int
    remaining: int
    reset: int  # Unix timestamp in seconds


class InMemoryRateLimiter:
    """Simple in-memory rate limiter using sliding window.

    Note: This is suitable for single-instance deployments.
    For distributed deployments, use Redis-based rate limiting.
    """

    def __init__(self) -> None:
        # Store request timestamps per identifier (maps identifier to list of timestamps)
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(
        self,
        identifier: str,
        limit_type: RateLimitType,
    ) -> RateLimitResult:
        """Check rate limit for an identifier.

        Args:
            identifier: Unique identifier (e.g., "ip:1.2.3.4" or "user:123")
            limit_type: Type of rate limit to apply

        Returns:
            RateLimitResult with success status and limit info
        """
        config = RATE_LIMIT_CONFIG[limit_type]
        key = f"{limit_type.value}:{identifier}"
        now = time.time()
        window_start = now - config.window_seconds

        async with self._lock:
            # Get existing timestamps and filter to current window
            timestamps = self._requests[key]
            timestamps = [t for t in timestamps if t > window_start]

            # Update stored timestamps
            self._requests[key] = timestamps

            # Check if limit exceeded
            current_count = len(timestamps)
            remaining = max(0, config.requests - current_count)

            if current_count >= config.requests:
                # Rate limit exceeded
                # Find oldest timestamp to determine reset time
                oldest = min(timestamps) if timestamps else now
                reset = int(oldest + config.window_seconds)
                return RateLimitResult(
                    success=False,
                    limit=config.requests,
                    remaining=0,
                    reset=reset,
                )

            # Request allowed - record it
            timestamps.append(now)
            self._requests[key] = timestamps

            return RateLimitResult(
                success=True,
                limit=config.requests,
                remaining=remaining - 1,  # Account for this request
                reset=int(now + config.window_seconds),
            )

    def reset(self) -> None:
        """Reset all rate limit entries. Useful for testing."""
        self._requests.clear()

    async def cleanup_old_entries(self) -> int:
        """Remove expired entries from memory.

        Returns:
            Number of entries removed
        """
        removed = 0
        now = time.time()

        async with self._lock:
            keys_to_remove = []
            for key, timestamps in self._requests.items():
                # Find the window for this key's type
                limit_type_str = key.split(":")[0]
                try:
                    limit_type = RateLimitType(limit_type_str)
                    window = RATE_LIMIT_CONFIG[limit_type].window_seconds
                except ValueError:
                    window = 60  # Default window

                # Filter timestamps
                valid_timestamps = [t for t in timestamps if t > now - window]
                if not valid_timestamps:
                    keys_to_remove.append(key)
                    removed += 1
                else:
                    self._requests[key] = valid_timestamps

            for key in keys_to_remove:
                del self._requests[key]

        return removed


# Global rate limiter instance
_rate_limiter = InMemoryRateLimiter()


def get_rate_limiter() -> InMemoryRateLimiter:
    """Get the global rate limiter instance."""
    return _rate_limiter


def get_client_ip(request: Request) -> str | None:
    """Extract client IP from request headers.

    Checks common headers used by proxies and load balancers.
    """
    # Try common headers in order of preference
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # x-forwarded-for can be a comma-separated list, take the first IP
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    cf_connecting_ip = request.headers.get("cf-connecting-ip")
    if cf_connecting_ip:
        return cf_connecting_ip.strip()

    # Fall back to request client
    if request.client:
        return request.client.host

    return None


def get_identifier(
    ip: str | None,
    user_id: int | None = None,
) -> str:
    """Get identifier for rate limiting.

    Prefers user ID for authenticated requests, falls back to IP address.
    """
    if user_id:
        return f"user:{user_id}"
    return f"ip:{ip or 'unknown'}"


async def check_rate_limit(
    request: Request,
    limit_type: RateLimitType,
    user_id: int | None = None,
) -> RateLimitResult:
    """Check rate limit for a request.

    Args:
        request: FastAPI request
        limit_type: Type of rate limit to apply
        user_id: Optional user ID for authenticated requests

    Returns:
        RateLimitResult with success status and limit info
    """
    ip = get_client_ip(request)
    identifier = get_identifier(ip, user_id)
    limiter = get_rate_limiter()
    return await limiter.check(identifier, limit_type)


def rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    """Generate rate limit headers for response.

    Args:
        result: Rate limit check result

    Returns:
        Dictionary of headers to add to response
    """
    headers = {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.reset),
    }

    if not result.success:
        retry_after = max(0, result.reset - int(time.time()))
        headers["Retry-After"] = str(retry_after)

    return headers
