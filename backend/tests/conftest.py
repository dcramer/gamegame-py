"""Pytest configuration and fixtures."""

import os
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Set test environment before importing app
os.environ["ENVIRONMENT"] = "test"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from gamegame.config import settings
from gamegame.database import get_session
from gamegame.main import app
from gamegame.models import Game, User
from gamegame.services.auth import create_token


@pytest.fixture(autouse=True)
def mock_queue():
    """Mock the SAQ queue to avoid Redis connections in tests."""
    mock_job = MagicMock()
    mock_job.id = "test-job-id"
    mock_job.key = "test-job-key"

    # Mock the queue object's enqueue method (queue is a Queue instance in gamegame.tasks.queue)
    with patch("gamegame.tasks.queue.queue.enqueue", new_callable=AsyncMock) as mock_enqueue:
        mock_enqueue.return_value = mock_job
        yield mock_enqueue


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_engine():
    """Create a test database engine."""
    engine = create_async_engine(
        settings.database_url_test,
        echo=False,
        poolclass=NullPool,
    )

    async with engine.begin() as conn:
        # Enable pgvector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create all tables
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with rollback after each test.

    Uses nested transactions (SAVEPOINTs) so that commits within tests
    don't actually commit to the database.
    """
    async with test_engine.connect() as conn:
        # Start outer transaction that will be rolled back
        await conn.begin()

        async_session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        async with async_session_factory() as session:
            # Start a nested transaction (SAVEPOINT)
            await session.begin_nested()

            yield session

            # Rollback nested transaction
            await session.rollback()

        # Rollback outer transaction
        await conn.rollback()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test HTTP client."""

    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def user(session: AsyncSession) -> User:
    """Create a test user."""
    user = User(email="test@example.com", name="Test User", is_admin=False)
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def admin_user(session: AsyncSession) -> User:
    """Create a test admin user."""
    user = User(email="admin@example.com", name="Admin User", is_admin=True)
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
def user_token(user: User) -> str:
    """Create a JWT token for the test user."""
    return create_token(user)


@pytest.fixture
def admin_token(admin_user: User) -> str:
    """Create a JWT token for the admin user."""
    return create_token(admin_user)


@pytest.fixture
def auth_headers(user_token: str) -> dict[str, str]:
    """Create authorization headers for the test user."""
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def admin_headers(admin_token: str) -> dict[str, str]:
    """Create authorization headers for the admin user."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
async def game(session: AsyncSession) -> Game:
    """Create a test game."""
    game = Game(
        name="Test Game",
        slug="test-game",
        year=2024,
        description="A test game for unit tests",
    )
    session.add(game)
    await session.flush()
    return game


# Helper to make authenticated requests
class AuthenticatedClient:
    """Wrapper for AsyncClient with authentication."""

    def __init__(self, client: AsyncClient, headers: dict[str, str]):
        self.client = client
        self.headers = headers

    async def get(self, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("headers", {}).update(self.headers)
        return await self.client.get(url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("headers", {}).update(self.headers)
        return await self.client.post(url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("headers", {}).update(self.headers)
        return await self.client.patch(url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("headers", {}).update(self.headers)
        return await self.client.delete(url, **kwargs)


@pytest.fixture
def authenticated_client(client: AsyncClient, auth_headers: dict[str, str]) -> AuthenticatedClient:
    """Create an authenticated test client."""
    return AuthenticatedClient(client, auth_headers)


@pytest.fixture
def admin_client(client: AsyncClient, admin_headers: dict[str, str]) -> AuthenticatedClient:
    """Create an authenticated admin test client."""
    return AuthenticatedClient(client, admin_headers)
