"""Chat endpoint tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from gamegame.models import Attachment, Game, Resource
from gamegame.models.attachment import AttachmentType, DetectedType, QualityRating
from gamegame.models.resource import ResourceStatus


@pytest.fixture
async def resource(session: AsyncSession, game: Game) -> Resource:
    """Create a test resource."""
    resource = Resource(
        game_id=game.id,
        name="Test Rulebook",
        original_filename="test-rulebook.pdf",
        url="/uploads/test.pdf",
        status=ResourceStatus.COMPLETED,
        content="This is a test rulebook with setup instructions.",
    )
    session.add(resource)
    await session.flush()
    return resource


@pytest.fixture
async def attachment(session: AsyncSession, game: Game, resource: Resource) -> Attachment:
    """Create a test attachment."""
    attachment = Attachment(
        game_id=game.id,
        resource_id=resource.id,
        type=AttachmentType.IMAGE,
        mime_type="image/png",
        blob_key="test/test.png",  # Required field
        url="/uploads/test.png",
        page_number=1,
        description="A diagram showing game setup",
        detected_type=DetectedType.DIAGRAM,
        is_good_quality=QualityRating.GOOD,
        ocr_text="Setup: Place tokens on board",
    )
    session.add(attachment)
    await session.flush()
    return attachment


def mock_openai_response(content: str = "This is a test response."):
    """Create a mock OpenAI response."""
    mock_message = MagicMock()
    mock_message.content = content
    mock_message.tool_calls = None
    mock_message.model_dump.return_value = {
        "role": "assistant",
        "content": content,
    }

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    return mock_response


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
    mock_response = mock_openai_response("The game setup requires placing tokens on the board.")

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
    mock_response = mock_openai_response("Test response")

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


@pytest.mark.asyncio
async def test_chat_with_tool_call(client: AsyncClient, game: Game, resource: Resource):
    """Test chat that uses a tool call."""
    # First response triggers a tool call
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.function.name = "search_resources"
    mock_tool_call.function.arguments = '{"query": "setup"}'

    mock_message_with_tool = MagicMock()
    mock_message_with_tool.content = None
    mock_message_with_tool.tool_calls = [mock_tool_call]
    mock_message_with_tool.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call_123", "function": {"name": "search_resources", "arguments": '{"query": "setup"}'}}],
    }

    mock_choice_with_tool = MagicMock()
    mock_choice_with_tool.message = mock_message_with_tool

    mock_response_with_tool = MagicMock()
    mock_response_with_tool.choices = [mock_choice_with_tool]

    # Final response after tool execution
    mock_final_response = mock_openai_response("Based on the rulebook, setup involves...")

    with (
        patch("gamegame.services.chat.settings") as mock_settings,
        patch("gamegame.services.chat.get_openai_client") as mock_get_client,
    ):
        mock_settings.openai_api_key = "test-key"
        mock_client = MagicMock()
        # First call returns tool call, second returns final response
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[mock_response_with_tool, mock_final_response]
        )
        mock_get_client.return_value = mock_client

        response = await client.post(
            f"/api/games/{game.id}/chat",
            json={"messages": [{"role": "user", "content": "How do I set up?"}]},
        )

        assert response.status_code == 200
        data = response.json()
        assert "Based on the rulebook" in data["content"]


@pytest.mark.asyncio
async def test_chat_search_images_tool(
    client: AsyncClient,
    game: Game,
    resource: Resource,
    attachment: Attachment,
):
    """Test chat that uses search_images tool."""
    # First response triggers search_images tool
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_456"
    mock_tool_call.function.name = "search_images"
    mock_tool_call.function.arguments = '{"query": "setup diagram"}'

    mock_message_with_tool = MagicMock()
    mock_message_with_tool.content = None
    mock_message_with_tool.tool_calls = [mock_tool_call]
    mock_message_with_tool.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call_456", "function": {"name": "search_images", "arguments": '{"query": "setup diagram"}'}}],
    }

    mock_choice_with_tool = MagicMock()
    mock_choice_with_tool.message = mock_message_with_tool

    mock_response_with_tool = MagicMock()
    mock_response_with_tool.choices = [mock_choice_with_tool]

    mock_final_response = mock_openai_response("I found a diagram showing the setup.")

    with (
        patch("gamegame.services.chat.settings") as mock_settings,
        patch("gamegame.services.chat.get_openai_client") as mock_get_client,
    ):
        mock_settings.openai_api_key = "test-key"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[mock_response_with_tool, mock_final_response]
        )
        mock_get_client.return_value = mock_client

        response = await client.post(
            f"/api/games/{game.id}/chat",
            json={"messages": [{"role": "user", "content": "Is there a setup diagram?"}]},
        )

        assert response.status_code == 200


@pytest.mark.asyncio
async def test_chat_list_resources_tool(
    client: AsyncClient,
    game: Game,
    resource: Resource,
):
    """Test chat that uses list_resources tool."""
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_789"
    mock_tool_call.function.name = "list_resources"
    mock_tool_call.function.arguments = "{}"

    mock_message_with_tool = MagicMock()
    mock_message_with_tool.content = None
    mock_message_with_tool.tool_calls = [mock_tool_call]
    mock_message_with_tool.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call_789", "function": {"name": "list_resources", "arguments": "{}"}}],
    }

    mock_choice_with_tool = MagicMock()
    mock_choice_with_tool.message = mock_message_with_tool

    mock_response_with_tool = MagicMock()
    mock_response_with_tool.choices = [mock_choice_with_tool]

    mock_final_response = mock_openai_response("The game has a rulebook available.")

    with (
        patch("gamegame.services.chat.settings") as mock_settings,
        patch("gamegame.services.chat.get_openai_client") as mock_get_client,
    ):
        mock_settings.openai_api_key = "test-key"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[mock_response_with_tool, mock_final_response]
        )
        mock_get_client.return_value = mock_client

        response = await client.post(
            f"/api/games/{game.id}/chat",
            json={"messages": [{"role": "user", "content": "What resources are available?"}]},
        )

        assert response.status_code == 200
        data = response.json()
        assert "rulebook" in data["content"].lower()
