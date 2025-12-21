"""Search endpoint tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from gamegame.models import Fragment, Game, Resource
from gamegame.models.fragment import FragmentType
from gamegame.models.resource import ResourceStatus, ResourceType


@pytest.fixture
async def resource(session: AsyncSession, game: Game) -> Resource:
    """Create a test resource."""
    resource = Resource(
        game_id=game.id,  # type: ignore[arg-type]
        name="Test Rulebook",
        original_filename="rulebook.pdf",
        url="/uploads/test.pdf",
        content="",  # Required field
        status=ResourceStatus.COMPLETED,
        resource_type=ResourceType.RULEBOOK,
    )
    session.add(resource)
    await session.flush()
    return resource


@pytest.fixture
async def fragment(session: AsyncSession, game: Game, resource: Resource) -> Fragment:
    """Create a test fragment with content for FTS."""
    content = "The player who controls the most territory wins the game. Each turn you can move units."
    fragment = Fragment(
        game_id=game.id,  # type: ignore[arg-type]
        resource_id=resource.id,  # type: ignore[arg-type]
        content=content,
        type=FragmentType.TEXT,
        page_number=5,
        section="Victory Conditions",
        embedding=[0.0] * 1536,  # Required: dummy embedding vector
    )
    session.add(fragment)
    await session.flush()
    # Manually set search_vector since trigger doesn't exist in test DB
    await session.execute(
        text("UPDATE fragments SET search_vector = to_tsvector('english', :content) WHERE id = :id"),
        {"content": content, "id": fragment.id},
    )
    await session.refresh(fragment)
    return fragment


@pytest.fixture
async def another_fragment(session: AsyncSession, game: Game, resource: Resource) -> Fragment:
    """Create another test fragment."""
    content = "Setup: Place the board in the center. Each player takes 10 pieces."
    fragment = Fragment(
        game_id=game.id,  # type: ignore[arg-type]
        resource_id=resource.id,  # type: ignore[arg-type]
        content=content,
        type=FragmentType.TEXT,
        page_number=2,
        section="Setup",
        embedding=[0.0] * 1536,  # Required: dummy embedding vector
    )
    session.add(fragment)
    await session.flush()
    await session.execute(
        text("UPDATE fragments SET search_vector = to_tsvector('english', :content) WHERE id = :id"),
        {"content": content, "id": fragment.id},
    )
    await session.refresh(fragment)
    return fragment


@pytest.mark.asyncio
async def test_search_requires_query(client: AsyncClient):
    """Test that search requires a query parameter."""
    response = await client.get("/api/search")
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_search_empty_results(client: AsyncClient):
    """Test search with no matching fragments."""
    response = await client.get("/api/search", params={"q": "xyznonexistent"})
    assert response.status_code == 200
    data = response.json()
    assert data["results"] == []
    assert data["query"] == "xyznonexistent"
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_search_fts(client: AsyncClient, fragment: Fragment):
    """Test full-text search finds matching content."""
    response = await client.get("/api/search", params={"q": "territory wins"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(r["fragment_id"] == fragment.id for r in data["results"])


@pytest.mark.asyncio
async def test_search_by_game_id(client: AsyncClient, game: Game, fragment: Fragment):
    """Test filtering search by game_id."""
    response = await client.get(
        "/api/search",
        params={"q": "territory", "game_id": game.id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["game_id"] == game.id
    # All results should be from this game
    for result in data["results"]:
        assert result["game_id"] == game.id


@pytest.mark.asyncio
async def test_search_game_not_found(client: AsyncClient):
    """Test search with non-existent game_id."""
    response = await client.get("/api/search", params={"q": "test", "game_id": "nonexistent"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_search_limit(client: AsyncClient, fragment: Fragment, another_fragment: Fragment):
    """Test search respects limit parameter."""
    response = await client.get("/api/search", params={"q": "player", "limit": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] <= 1


@pytest.mark.asyncio
async def test_search_game_by_slug(client: AsyncClient, game: Game, fragment: Fragment):
    """Test searching within a game by slug."""
    response = await client.get(
        f"/api/search/games/{game.slug}",
        params={"q": "territory"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["game_id"] == game.id


@pytest.mark.asyncio
async def test_search_game_by_id(client: AsyncClient, game: Game, fragment: Fragment):
    """Test searching within a game by ID."""
    response = await client.get(
        f"/api/search/games/{game.id}",
        params={"q": "territory"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["game_id"] == game.id


@pytest.mark.asyncio
async def test_search_game_not_found_by_slug(client: AsyncClient):
    """Test search with non-existent game slug."""
    response = await client.get(
        "/api/search/games/nonexistent-game",
        params={"q": "test"},
    )
    assert response.status_code == 404
