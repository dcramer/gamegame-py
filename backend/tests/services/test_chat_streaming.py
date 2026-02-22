"""Tests for structured streaming events in chat service."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gamegame.models import Attachment, Game
from gamegame.models.attachment import AttachmentType
from gamegame.services.chat import (
    ChatMessage,
    _segment_limit_for_question,
    single_pass_chat,
    single_pass_chat_stream,
)
from gamegame.services.search import SegmentResult


class _AsyncChunkStream:
    """Simple async iterator for mocked OpenAI stream chunks."""

    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration as e:  # pragma: no cover - iterator protocol
            raise StopAsyncIteration from e


def _make_chunk(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
):
    """Create a mocked OpenAI stream chunk."""
    usage = None
    if prompt_tokens is not None and completion_tokens is not None:
        usage = SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish_reason)],
        usage=usage,
    )


@pytest.mark.asyncio
async def test_single_pass_stream_emits_context_data_with_citations():
    """Stream emits a context-data event before text deltas."""
    game = Game(name="Test Game", slug="test-game")
    messages = [ChatMessage(role="user", content="How do I win?")]
    segments = [
        SegmentResult(
            segment_id="seg1",
            title="Winning",
            hierarchy_path="Scoring > End Game",
            content="You win with most points.",
            resource_id="res1",
            resource_name="Core Rulebook",
            page_start=12,
            page_end=12,
        ),
    ]

    stream_chunks = [
        _make_chunk(content="You win with the most points."),
        _make_chunk(finish_reason="stop", prompt_tokens=10, completion_tokens=4),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_AsyncChunkStream(stream_chunks))

    with (
        patch("gamegame.services.chat.settings") as mock_settings,
        patch("gamegame.services.chat.SearchService.get_embedding", new=AsyncMock(return_value=[0.1] * 5)),
        patch("gamegame.services.chat.search_segments", new=AsyncMock(return_value=segments)),
        patch("gamegame.services.chat.get_openai_client", return_value=mock_client),
    ):
        mock_settings.openai_api_key = "test-key"

        events = [
            json.loads(event)
            async for event in single_pass_chat_stream(
                session=AsyncMock(),
                game=game,
                messages=messages,
            )
        ]

    assert events[0]["type"] == "context-data"
    assert events[0]["citations"] == [{
        "resource_id": "res1",
        "resource_name": "Core Rulebook",
        "page_number": 12,
        "section": "Scoring > End Game",
        "relevance": "primary",
    }]
    assert events[0]["images"] == []
    assert any(e["type"] == "text-delta" for e in events)
    assert events[-1]["type"] == "finish"


@pytest.mark.asyncio
async def test_single_pass_stream_resolves_attachment_images():
    """Context-data event includes images referenced via attachment:// syntax."""
    game = Game(id="game1", name="Test Game", slug="test-game")
    messages = [ChatMessage(role="user", content="Show setup diagram")]
    segments = [
        SegmentResult(
            segment_id="seg1",
            title="Setup",
            hierarchy_path="Setup",
            content="See this figure: ![diagram](attachment://att1)",
            resource_id="res1",
            resource_name="Core Rulebook",
            page_start=2,
            page_end=2,
        ),
    ]
    attachment = Attachment(
        id="att1",
        game_id="game1",
        resource_id="res1",
        type=AttachmentType.IMAGE,
        mime_type="image/png",
        blob_key="uploads/att1.png",
        url="/uploads/att1.png",
        caption="Setup Diagram",
        description="Board setup layout",
    )

    stream_chunks = [
        _make_chunk(content="Here's the setup diagram."),
        _make_chunk(finish_reason="stop", prompt_tokens=8, completion_tokens=3),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_AsyncChunkStream(stream_chunks))
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: [attachment]))

    with (
        patch("gamegame.services.chat.settings") as mock_settings,
        patch("gamegame.services.chat.SearchService.get_embedding", new=AsyncMock(return_value=[0.1] * 5)),
        patch("gamegame.services.chat.search_segments", new=AsyncMock(return_value=segments)),
        patch("gamegame.services.chat.get_openai_client", return_value=mock_client),
    ):
        mock_settings.openai_api_key = "test-key"

        events = [
            json.loads(event)
            async for event in single_pass_chat_stream(
                session=mock_session,
                game=game,
                messages=messages,
            )
        ]

    assert events[0]["type"] == "context-data"
    assert events[0]["images"] == [{
        "id": "att1",
        "url": "/uploads/att1.png",
        "caption": "Setup Diagram",
        "description": "Board setup layout",
        "page_number": None,
    }]


@pytest.mark.asyncio
async def test_single_pass_chat_returns_safe_fallback_when_no_context():
    """Non-stream chat should avoid model calls when retrieval returns no context."""
    game = Game(name="Test Game", slug="test-game")
    messages = [ChatMessage(role="user", content="What does card X do?")]

    with (
        patch("gamegame.services.chat.settings") as mock_settings,
        patch("gamegame.services.chat.SearchService.get_embedding", new=AsyncMock(return_value=[0.1] * 5)),
        patch("gamegame.services.chat.search_segments", new=AsyncMock(return_value=[])),
        patch("gamegame.services.chat.get_openai_client") as mock_get_client,
    ):
        mock_settings.openai_api_key = "test-key"
        response = await single_pass_chat(
            session=AsyncMock(),
            game=game,
            messages=messages,
        )

    assert response.citations == []
    assert response.confidence == "low"
    assert "don't see this covered" in response.content.lower()
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
async def test_single_pass_stream_returns_safe_fallback_when_no_context():
    """Streaming chat should emit fallback text and finish when no segments are found."""
    game = Game(name="Test Game", slug="test-game")
    messages = [ChatMessage(role="user", content="How is tie-break resolved?")]

    with (
        patch("gamegame.services.chat.settings") as mock_settings,
        patch("gamegame.services.chat.SearchService.get_embedding", new=AsyncMock(return_value=[0.1] * 5)),
        patch("gamegame.services.chat.search_segments", new=AsyncMock(return_value=[])),
        patch("gamegame.services.chat.get_openai_client") as mock_get_client,
    ):
        mock_settings.openai_api_key = "test-key"
        events = [
            json.loads(event)
            async for event in single_pass_chat_stream(
                session=AsyncMock(),
                game=game,
                messages=messages,
            )
        ]

    assert events[0]["type"] == "context-data"
    assert events[0]["citations"] == []
    assert any(e["type"] == "text-delta" for e in events)
    assert events[-1]["type"] == "finish"
    assert events[-1]["totalUsage"] == {"promptTokens": 0, "completionTokens": 0}
    mock_get_client.assert_not_called()


def test_segment_limit_increases_for_complex_questions():
    """Complex rule interaction questions should retrieve deeper context."""
    assert _segment_limit_for_question("How do I score?") == 2
    assert _segment_limit_for_question("If I attack and then move, when does timing resolve?") >= 4
    assert _segment_limit_for_question(
        "When does this resolve and what happens if there are simultaneous effects after combat "
        "and before cleanup while another condition applies?"
    ) == 6
