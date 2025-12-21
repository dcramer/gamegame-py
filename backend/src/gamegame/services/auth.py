"""Authentication service for JWT token management."""

from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gamegame.config import settings
from gamegame.models import User


class AuthError(Exception):
    """Authentication error."""

    pass


def create_token(user: User) -> str:
    """Create a JWT token for a user."""
    expires = datetime.now(UTC) + timedelta(days=settings.jwt_expiration_days)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "is_admin": user.is_admin,
        "exp": expires,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.session_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.session_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        raise AuthError(f"Invalid token: {e}") from e


async def verify_token(session: AsyncSession, token: str) -> User:
    """Verify a JWT token and return the associated user."""
    payload = decode_token(token)

    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("Invalid token: missing user ID")

    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise AuthError("User not found")

    return user


def refresh_token(token: str) -> str:
    """Refresh a JWT token if still valid."""
    payload = decode_token(token)

    # Create new token with same user info
    expires = datetime.now(UTC) + timedelta(days=settings.jwt_expiration_days)
    new_payload = {
        "sub": payload["sub"],
        "email": payload["email"],
        "is_admin": payload.get("is_admin", False),
        "exp": expires,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(new_payload, settings.session_secret, algorithm=settings.jwt_algorithm)
