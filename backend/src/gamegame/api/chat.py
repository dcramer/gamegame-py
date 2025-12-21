"""Chat API endpoint."""

import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gamegame.api.deps import CurrentUserOptional, SessionDep
from gamegame.api.utils import get_game_by_id_or_slug
from gamegame.services.chat import ChatMessage, chat, chat_stream
from gamegame.services.rate_limit import (
    RateLimitType,
    check_rate_limit,
    rate_limit_headers,
)
from gamegame.services.resilience import CircuitOpenError

logger = logging.getLogger(__name__)

router = APIRouter()


class MessageInput(BaseModel):
    """A single message in the conversation."""

    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""

    messages: list[MessageInput]
    stream: bool = False


class CitationResponse(BaseModel):
    """A citation in the response."""

    resource_id: str
    resource_name: str
    page_number: int | None = None
    section: str | None = None
    relevance: str = "primary"


class ChatResponseModel(BaseModel):
    """Response from chat endpoint."""

    content: str
    citations: list[CitationResponse]
    confidence: str = "high"


@router.post("/{game_id_or_slug}/chat", response_model=ChatResponseModel)
async def chat_with_game(
    game_id_or_slug: str,
    request: ChatRequest,
    http_request: Request,
    session: SessionDep,
    user: CurrentUserOptional,
):
    """Chat with an AI about a game's rules.

    Send messages and get AI-powered responses based on the game's rulebooks
    and other resources. The AI uses RAG to search through the game's
    documentation and provide accurate answers.

    Args:
        game_id_or_slug: Game ID or slug
        request: Chat request with messages

    Returns:
        AI response with citations
    """
    # Check rate limit
    user_id = user.id if user else None
    rate_limit = await check_rate_limit(http_request, RateLimitType.CHAT, user_id)
    if not rate_limit.success:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers=rate_limit_headers(rate_limit),
        )

    game = await get_game_by_id_or_slug(game_id_or_slug, session)

    if not request.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Messages array cannot be empty",
        )

    # Convert to internal message format
    messages = [
        ChatMessage(role=m.role, content=m.content) for m in request.messages
    ]

    # Handle streaming
    if request.stream:
        async def generate():
            try:
                async for token in chat_stream(session, game, messages):
                    yield f"data: {token}\n\n"
                yield "data: [DONE]\n\n"
            except Exception:
                logger.exception(f"Error during chat stream for game {game.id}")
                error_data = json.dumps({"error": "An error occurred during chat"})
                yield f"data: {error_data}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming response
    try:
        response = await chat(session, game, messages)
    except CircuitOpenError:
        logger.warning(f"Circuit breaker open for chat request on game {game.id}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is temporarily unavailable. Please try again in a few moments.",
            headers={"Retry-After": "30"},
        ) from None

    return ChatResponseModel(
        content=response.content,
        citations=[
            CitationResponse(
                resource_id=c.resource_id,
                resource_name=c.resource_name,
                page_number=c.page_number,
                section=c.section,
                relevance=c.relevance,
            )
            for c in response.citations
        ],
        confidence=response.confidence,
    )
