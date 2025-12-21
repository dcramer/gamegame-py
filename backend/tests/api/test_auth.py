"""Authentication endpoint tests."""

import pytest
from httpx import AsyncClient

from gamegame.models import User
from tests.conftest import AuthenticatedClient


@pytest.mark.asyncio
async def test_login_creates_user(client: AsyncClient):
    """Test that login creates a new user if they don't exist."""
    response = await client.post(
        "/api/auth/login",
        json={"email": "newuser@example.com"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    # In development, magic link is included
    assert "magic_link" in data


@pytest.mark.asyncio
async def test_login_existing_user(client: AsyncClient, user: User):
    """Test login for existing user."""
    response = await client.post(
        "/api/auth/login",
        json={"email": user.email},
    )
    assert response.status_code == 200
    data = response.json()
    assert "magic_link" in data


@pytest.mark.asyncio
async def test_verify_invalid_token(client: AsyncClient):
    """Test verifying an invalid token."""
    response = await client.post(
        "/api/auth/verify",
        json={"token": "invalid-token"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_current_user(authenticated_client: AuthenticatedClient, user: User):
    """Test getting current user info."""
    response = await authenticated_client.get("/api/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == user.email
    assert data["is_admin"] is False


@pytest.mark.asyncio
async def test_get_current_user_unauthenticated(client: AsyncClient):
    """Test getting current user without authentication."""
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout(authenticated_client: AuthenticatedClient):
    """Test logout endpoint."""
    response = await authenticated_client.post("/api/auth/logout")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_refresh_token(authenticated_client: AuthenticatedClient, user: User):
    """Test refreshing an access token."""
    response = await authenticated_client.post("/api/auth/refresh")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == user.email


@pytest.mark.asyncio
async def test_refresh_token_unauthenticated(client: AsyncClient):
    """Test refresh without authentication fails."""
    response = await client.post("/api/auth/refresh")
    assert response.status_code == 401  # HTTPBearer returns 401 when no token


@pytest.mark.asyncio
async def test_refresh_token_invalid(client: AsyncClient):
    """Test refresh with invalid token fails."""
    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_rate_limit(client: AsyncClient):
    """Test that login endpoint has rate limiting."""
    from gamegame.services.rate_limit import (
        RATE_LIMIT_CONFIG,
        RateLimitType,
        get_rate_limiter,
    )

    # Reset rate limiter to ensure clean state
    get_rate_limiter().reset()

    config = RATE_LIMIT_CONFIG[RateLimitType.AUTH]

    # Make requests up to the limit
    for i in range(config.requests):
        response = await client.post(
            "/api/auth/login",
            json={"email": f"user{i}@example.com"},
        )
        assert response.status_code == 200

    # Next request should be rate limited
    response = await client.post(
        "/api/auth/login",
        json={"email": "extra@example.com"},
    )
    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]
    assert "X-RateLimit-Limit" in response.headers
    assert "Retry-After" in response.headers
