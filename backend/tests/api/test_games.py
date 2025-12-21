"""Game endpoint tests."""

import pytest
from httpx import AsyncClient

from gamegame.models import Game
from tests.conftest import AuthenticatedClient


@pytest.mark.asyncio
async def test_list_games_empty(client: AsyncClient):
    """Test listing games when none exist."""
    response = await client.get("/api/games")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_games(client: AsyncClient, game: Game):
    """Test listing games."""
    response = await client.get("/api/games")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Game"
    assert data[0]["slug"] == "test-game"
    assert data[0]["resource_count"] == 0


@pytest.mark.asyncio
async def test_get_game_by_id(client: AsyncClient, game: Game):
    """Test getting a game by ID."""
    response = await client.get(f"/api/games/{game.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Game"
    assert data["slug"] == "test-game"


@pytest.mark.asyncio
async def test_get_game_by_slug(client: AsyncClient, game: Game):
    """Test getting a game by slug."""
    response = await client.get("/api/games/test-game")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Game"


@pytest.mark.asyncio
async def test_get_game_not_found(client: AsyncClient):
    """Test getting a non-existent game."""
    response = await client.get("/api/games/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_game_anonymous_denied(client: AsyncClient):
    """Test that anonymous users cannot create games."""
    response = await client.post("/api/games", json={"name": "New Game"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_game_requires_admin(authenticated_client: AuthenticatedClient):
    """Test that non-admin users cannot create games."""
    response = await authenticated_client.post(
        "/api/games",
        json={"name": "New Game"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_game(admin_client: AuthenticatedClient):
    """Test creating a game as admin."""
    response = await admin_client.post(
        "/api/games",
        json={"name": "New Game", "year": 2024},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Game"
    assert data["slug"] == "new-game-2024"  # slug includes year
    assert data["year"] == 2024
    assert data["resource_count"] == 0


@pytest.mark.asyncio
async def test_create_game_extracts_bgg_id(admin_client: AuthenticatedClient):
    """Test that BGG ID is extracted from URL."""
    response = await admin_client.post(
        "/api/games",
        json={
            "name": "Catan",
            "year": 1995,
            "bgg_url": "https://boardgamegeek.com/boardgame/13/catan",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["bgg_id"] == 13
    assert data["slug"] == "catan-1995"


@pytest.mark.asyncio
async def test_create_game_with_custom_slug(admin_client: AuthenticatedClient):
    """Test creating a game with a custom slug."""
    response = await admin_client.post(
        "/api/games",
        json={"name": "My Game", "slug": "custom-slug"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "custom-slug"


@pytest.mark.asyncio
async def test_create_game_duplicate_slug(admin_client: AuthenticatedClient, game: Game):
    """Test that duplicate slugs are rejected."""
    response = await admin_client.post(
        "/api/games",
        json={"name": "Another Game", "slug": "test-game"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_update_game_anonymous_denied(client: AsyncClient, game: Game):
    """Test that anonymous users cannot update games."""
    response = await client.patch(f"/api/games/{game.id}", json={"name": "Hacked"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_game(admin_client: AuthenticatedClient, game: Game):
    """Test updating a game."""
    response = await admin_client.patch(
        f"/api/games/{game.id}",
        json={"name": "Updated Game"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Game"


@pytest.mark.asyncio
async def test_delete_game_anonymous_denied(client: AsyncClient, game: Game):
    """Test that anonymous users cannot delete games."""
    response = await client.delete(f"/api/games/{game.id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_game(admin_client: AuthenticatedClient, game: Game):
    """Test deleting a game."""
    response = await admin_client.delete(f"/api/games/{game.id}")
    assert response.status_code == 204
