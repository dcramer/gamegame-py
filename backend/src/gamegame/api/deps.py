"""FastAPI dependencies for dependency injection."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from gamegame.database import get_session
from gamegame.models import User
from gamegame.services.auth import verify_token
from gamegame.services.rate_limit import (
    RateLimitType,
    check_rate_limit,
    rate_limit_headers,
)

logger = logging.getLogger(__name__)

# Type alias for database session dependency
SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Security scheme
security = HTTPBearer(auto_error=False)


async def get_current_user_optional(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> User | None:
    """Get current user if authenticated, None otherwise."""
    if not credentials:
        return None

    try:
        user = await verify_token(session, credentials.credentials)
        return user
    except Exception:
        # Log at debug level since this is expected for invalid/expired tokens
        logger.debug("Token verification failed for optional auth")
        return None


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> User:
    """Get current authenticated user or raise 401."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user = await verify_token(session, credentials.credentials)
        return user
    except Exception as e:
        logger.debug(f"Token verification failed: {e!r}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_admin_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current user and verify they are an admin."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# Type aliases for common dependencies
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
AdminUser = Annotated[User, Depends(get_admin_user)]


class RateLimitDependency:
    """Dependency class for rate limiting endpoints.

    Usage:
        @router.post("/endpoint")
        async def endpoint(
            rate_limit: Annotated[None, Depends(RateLimitDependency(RateLimitType.AUTH))]
        ):
            ...
    """

    def __init__(self, limit_type: RateLimitType) -> None:
        self.limit_type = limit_type

    async def __call__(self, request: Request) -> None:
        """Check rate limit and raise 429 if exceeded."""
        result = await check_rate_limit(request, self.limit_type)

        if not result.success:
            headers = rate_limit_headers(result)
            retry_after = headers.get("Retry-After", "60")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Please try again in {retry_after} seconds.",
                headers=headers,
            )


# Pre-configured rate limit dependencies
AuthRateLimit = Annotated[None, Depends(RateLimitDependency(RateLimitType.AUTH))]
