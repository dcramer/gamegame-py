"""Chat endpoint tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from gamegame.models import Game, Resource
from tests.conftest import make_openai_chat_response


@pytest.mark.asyncio
async def test_chat_game_not_found(client: AsyncClient):
    """Test chat with non-existent game."""
    response = await client.post(
        "/api/games/nonexistent/chat",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_empty_messages(client: AsyncClient, game: Game):
    """Test chat with empty messages."""
    response = await client.post(
        f"/api/games/{game.id}/chat",
        json={"messages": []},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_chat_success(client: AsyncClient, game: Game, resource: Resource):
    """Test successful chat request."""
    mock_response = make_openai_chat_response("The game setup requires placing tokens on the board.")

    with (
        patch("gamegame.services.chat.settings") as mock_settings,
        patch("gamegame.services.chat.get_openai_client") as mock_get_client,
    ):
        mock_settings.openai_api_key = "test-key"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        response = await client.post(
            f"/api/games/{game.id}/chat",
            json={"messages": [{"role": "user", "content": "How do I set up the game?"}]},
        )

        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert data["content"] == "The game setup requires placing tokens on the board."
        assert "citations" in data
        assert "confidence" in data


@pytest.mark.asyncio
async def test_chat_by_slug(client: AsyncClient, game: Game, resource: Resource):
    """Test chat using game slug instead of ID."""
    mock_response = make_openai_chat_response("Test response")

    with (
        patch("gamegame.services.chat.settings") as mock_settings,
        patch("gamegame.services.chat.get_openai_client") as mock_get_client,
    ):
        mock_settings.openai_api_key = "test-key"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        response = await client.post(
            f"/api/games/{game.slug}/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )

        assert response.status_code == 200

