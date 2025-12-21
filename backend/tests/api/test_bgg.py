"""BGG API endpoint tests."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from gamegame.models import Game
from gamegame.services.bgg import BGGGameInfo, BGGSearchResult
from tests.conftest import AuthenticatedClient


@pytest.mark.asyncio
async def test_bgg_search_requires_admin(authenticated_client: AuthenticatedClient):
    """Test that BGG search requires admin."""
    response = await authenticated_client.get("/api/bgg/search?q=catan")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_bgg_search_unauthenticated(client: AsyncClient):
    """Test that BGG search requires authentication."""
    response = await client.get("/api/bgg/search?q=catan")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bgg_search_query_required(admin_client: AuthenticatedClient):
    """Test that BGG search requires a query."""
    response = await admin_client.get("/api/bgg/search")
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_bgg_search_query_min_length(admin_client: AuthenticatedClient):
    """Test that BGG search query has minimum length."""
    response = await admin_client.get("/api/bgg/search?q=a")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bgg_search_success(admin_client: AuthenticatedClient, session):
    """Test successful BGG search."""
    mock_results = [
        BGGSearchResult(bgg_id=13, name="Catan", year=1995, game_type="boardgame"),
        BGGSearchResult(bgg_id=27710, name="Catan: Cities & Knights", year=1998, game_type="boardgameexpansion"),
    ]

    with patch("gamegame.api.bgg.search_games_basic", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_results

        response = await admin_client.get("/api/bgg/search?q=catan")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["bgg_id"] == 13
        assert data[0]["name"] == "Catan"
        assert data[0]["is_imported"] is False


@pytest.mark.asyncio
async def test_bgg_search_shows_imported(admin_client: AuthenticatedClient, session):
    """Test that BGG search shows already imported games."""
    # Create an imported game
    game = Game(name="Catan", slug="catan", bgg_id=13, year=1995)
    session.add(game)
    await session.commit()

    mock_results = [
        BGGSearchResult(bgg_id=13, name="Catan", year=1995, game_type="boardgame"),
    ]

    with patch("gamegame.api.bgg.search_games_basic", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_results

        response = await admin_client.get("/api/bgg/search?q=catan")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["is_imported"] is True
        assert data[0]["game_id"] == game.id
        assert data[0]["game_slug"] == "catan"


@pytest.mark.asyncio
async def test_bgg_import_requires_admin(authenticated_client: AuthenticatedClient):
    """Test that BGG import requires admin."""
    response = await authenticated_client.post("/api/bgg/games/13/import")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_bgg_import_game_not_found(admin_client: AuthenticatedClient):
    """Test importing a non-existent BGG game."""
    with patch("gamegame.api.bgg.fetch_game_info", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = None

        response = await admin_client.post("/api/bgg/games/99999999/import")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_bgg_import_already_imported(admin_client: AuthenticatedClient, session):
    """Test importing an already imported game."""
    # Create existing game with same BGG ID
    game = Game(name="Catan", slug="catan", bgg_id=13, year=1995)
    session.add(game)
    await session.commit()

    response = await admin_client.post("/api/bgg/games/13/import")
    assert response.status_code == 409
    assert "already imported" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bgg_import_success(admin_client: AuthenticatedClient, session):
    """Test successful BGG game import."""
    mock_info = BGGGameInfo(
        bgg_id=13,
        name="Catan",
        year=1995,
        image_url="https://example.com/catan.jpg",
        thumbnail_url="https://example.com/catan_thumb.jpg",
        description="Trade and build settlements",
        min_players=3,
        max_players=4,
        playing_time=90,
    )

    with (
        patch("gamegame.api.bgg.fetch_game_info", new_callable=AsyncMock) as mock_fetch,
        patch("gamegame.api.bgg.download_image", new_callable=AsyncMock) as mock_download,
        patch("gamegame.api.bgg.storage") as mock_storage,
    ):
        mock_fetch.return_value = mock_info
        # Return fake image data (valid PNG header for Pillow)
        mock_download.return_value = None  # Skip image download for simplicity
        mock_storage.upload_file = AsyncMock(return_value=("/uploads/games/test.webp", "games/test.webp"))

        response = await admin_client.post("/api/bgg/games/13/import")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Catan"
        assert data["bgg_id"] == 13
        assert data["year"] == 1995
        assert data["slug"] == "catan-1995"


@pytest.mark.asyncio
async def test_bgg_thumbnail_requires_admin(authenticated_client: AuthenticatedClient):
    """Test that BGG thumbnail requires admin."""
    response = await authenticated_client.get("/api/bgg/games/13/thumbnail")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_bgg_thumbnail_not_found(admin_client: AuthenticatedClient):
    """Test thumbnail for non-existent BGG game."""
    with patch("gamegame.api.bgg.fetch_game_info", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = None

        response = await admin_client.get("/api/bgg/games/99999999/thumbnail")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_bgg_thumbnail_success(admin_client: AuthenticatedClient):
    """Test successful thumbnail retrieval."""
    mock_info = BGGGameInfo(
        bgg_id=13,
        name="Catan",
        year=1995,
        image_url="https://example.com/catan.jpg",
        thumbnail_url="https://example.com/catan_thumb.jpg",
        description="Trade and build settlements",
        min_players=3,
        max_players=4,
        playing_time=90,
    )

    with patch("gamegame.api.bgg.fetch_game_info", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_info

        response = await admin_client.get("/api/bgg/games/13/thumbnail")
        assert response.status_code == 200
        data = response.json()
        assert data["thumbnail_url"] == "https://example.com/catan_thumb.jpg"
        assert data["cached"] is False
