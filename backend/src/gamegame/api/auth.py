"""Authentication endpoints."""

from datetime import UTC, datetime, timedelta
from secrets import token_hex
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlmodel import select

from gamegame.api.deps import AuthRateLimit, CurrentUser, SessionDep
from gamegame.config import settings
from gamegame.models import User, VerificationToken
from gamegame.models.user import UserRead
from gamegame.services.auth import AuthError, create_token, decode_token
from gamegame.services.email import email_service

security = HTTPBearer()

router = APIRouter()


class LoginRequest(BaseModel):
    """Request body for login."""

    email: EmailStr


class LoginResponse(BaseModel):
    """Response for login request."""

    message: str
    # In development, include the magic link for testing
    magic_link: str | None = None


class VerifyRequest(BaseModel):
    """Request body for token verification."""

    token: str


class TokenResponse(BaseModel):
    """Response containing JWT token."""

    access_token: str
    token_type: str = "bearer"
    user: UserRead


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    session: SessionDep,
    _rate_limit: AuthRateLimit,
):
    """
    Request a magic link for authentication.

    Sends a magic link to the provided email if the user exists.
    """
    # Find or create user
    stmt = select(User).where(User.email == request.email)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # In production, you might want to silently succeed to prevent enumeration
        # For now, we'll create the user
        user = User(email=request.email)
        session.add(user)
        await session.flush()

    # Generate verification token
    token = token_hex(32)
    expires = datetime.now(UTC) + timedelta(minutes=settings.magic_link_expiration_minutes)

    # Delete any existing tokens for this email
    existing = await session.execute(
        select(VerificationToken).where(VerificationToken.identifier == request.email)
    )
    for old_token in existing.scalars():
        await session.delete(old_token)

    # Create new token
    verification = VerificationToken(
        identifier=request.email,
        token=token,
        expires=expires,
    )
    session.add(verification)
    await session.commit()

    # Build magic link with full URL
    magic_link = f"{settings.app_url}/auth/verify?token={token}"

    # Send the magic link email
    email_sent = await email_service.send_magic_link(to=request.email, magic_link=magic_link)

    if not email_sent and settings.is_production:
        # In production, fail if email couldn't be sent
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send magic link email",
        )

    response = LoginResponse(message="Check your email for a magic link")

    # Include magic link in development for testing
    if settings.is_development:
        response.magic_link = f"/auth/verify?token={token}"

    return response


@router.post("/verify", response_model=TokenResponse)
async def verify(
    request: VerifyRequest,
    session: SessionDep,
    _rate_limit: AuthRateLimit,
):
    """
    Verify a magic link token and return JWT.
    """
    # Find token
    stmt = select(VerificationToken).where(VerificationToken.token == request.token)
    result = await session.execute(stmt)
    verification = result.scalar_one_or_none()

    if not verification:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    # Check expiration
    if verification.expires < datetime.now(UTC):
        await session.delete(verification)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token has expired",
        )

    # Find user
    user_stmt = select(User).where(User.email == verification.identifier)
    user_result = await session.execute(user_stmt)
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found",
        )

    # Delete used token
    await session.delete(verification)

    # Create JWT
    access_token = create_token(user)

    await session.commit()

    return TokenResponse(
        access_token=access_token,
        user=UserRead.model_validate(user),
    )


@router.get("/me", response_model=UserRead)
async def get_current_user_info(user: CurrentUser):
    """Get current authenticated user info."""
    return UserRead.model_validate(user)


@router.post("/logout")
async def logout():
    """
    Logout endpoint.

    Since we use stateless JWT, this is mostly for client-side token clearing.
    """
    return {"message": "Logged out successfully"}


class RefreshResponse(BaseModel):
    """Response for token refresh."""

    access_token: str
    token_type: str = "bearer"
    user: UserRead


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    _rate_limit: AuthRateLimit,
):
    """
    Refresh JWT token.

    Validates the current token and issues a new one with fresh user data
    and extended expiration.
    """
    try:
        # Decode existing token to get user ID
        payload = decode_token(credentials.credentials)
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID",
            )

        # Fetch fresh user data from database
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        # Create new token with fresh user data
        access_token = create_token(user)

        return RefreshResponse(
            access_token=access_token,
            user=UserRead.model_validate(user),
        )

    except AuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e
