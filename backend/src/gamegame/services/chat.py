"""Chat service for RAG-based Q&A."""

import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gamegame.config import settings
from gamegame.models import Attachment, Embedding, Fragment, Game, Resource
from gamegame.models.embedding import EmbeddingType
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import get_openai_client
from gamegame.services.search import (
    PageResult,
    SearchService,
    SegmentResult,
    search_segments,
)

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """A chat message."""

    role: str  # "user", "assistant", "system"
    content: str


@dataclass
class Citation:
    """A citation from a source."""

    resource_id: str
    resource_name: str
    page_number: int | None = None
    section: str | None = None
    relevance: str = "primary"  # primary, supporting, related
    quote: str | None = None


@dataclass
class ChatResponse:
    """Response from the chat service."""

    content: str
    citations: list[Citation]
    confidence: str = "high"  # high, medium, low
    follow_ups: list[str] | None = None


# Stream event types for AI SDK-compatible streaming
@dataclass
class StreamEvent:
    """Base stream event with type and id."""

    type: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class TextDeltaEvent(StreamEvent):
    """Streaming text chunk."""

    type: str = field(default="text-delta", init=False)
    text: str = ""


@dataclass
class ToolInputStartEvent(StreamEvent):
    """Tool call begins."""

    type: str = field(default="tool-input-start", init=False)
    toolName: str = ""


@dataclass
class ToolInputAvailableEvent(StreamEvent):
    """Tool input fully parsed."""

    type: str = field(default="tool-input-available", init=False)
    input: dict = field(default_factory=dict)


@dataclass
class ToolOutputAvailableEvent(StreamEvent):
    """Tool execution result."""

    type: str = field(default="tool-output-available", init=False)
    output: Any = None


@dataclass
class FinishEvent(StreamEvent):
    """Stream complete with usage stats."""

    type: str = field(default="finish", init=False)
    finishReason: str = "stop"
    totalUsage: dict = field(default_factory=lambda: {"promptTokens": 0, "completionTokens": 0})


@dataclass
class ErrorEvent(StreamEvent):
    """Error event."""

    type: str = field(default="error", init=False)
    error: str = ""


@dataclass
class ContextDataEvent(StreamEvent):
    """Structured context metadata (citations/images) for streaming clients."""

    type: str = field(default="context-data", init=False)
    citations: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)


def _serialize_event(event: StreamEvent) -> str:
    """Serialize a stream event to JSON string for SSE."""
    data: dict[str, Any] = {
        "type": event.type,
        "id": event.id,
    }

    if isinstance(event, TextDeltaEvent):
        data["text"] = event.text
    elif isinstance(event, ToolInputStartEvent):
        data["toolName"] = event.toolName
    elif isinstance(event, ToolInputAvailableEvent):
        data["input"] = event.input
    elif isinstance(event, ToolOutputAvailableEvent):
        data["output"] = event.output
    elif isinstance(event, FinishEvent):
        data["finishReason"] = event.finishReason
        data["totalUsage"] = event.totalUsage
    elif isinstance(event, ErrorEvent):
        data["error"] = event.error
    elif isinstance(event, ContextDataEvent):
        data["citations"] = event.citations
        data["images"] = event.images

    return json.dumps(data)


GITHUB_URL = "https://github.com/dcramer/gamegame"

SYSTEM_PROMPT_TEMPLATE = """You are a rules expert for **{game_name}**{year_part}, operating on GameGame.

## Your Role
- Answer gameplay questions accurately using provided resources
- Cite sources with page numbers
- Be concise but complete
- Never advise on strategy—only explain rules

## Game Information
- **Name**: {game_name}{year_info}{bgg_info}

## Response Guidelines

### Length by Question Type
| Type | Length | Format |
|------|--------|--------|
| Factual (count, timing) | 1-2 sentences | Direct answer + citation |
| Procedural (how to) | 3-5 bullets | Numbered steps |
| Complex (interactions) | 2-4 sentences + bullets | Summary then details |
| Ambiguous | Quote + interpretation | "Rules state '...' This means..." |

### Citation Format
Always cite: "(Section Name, p.XX)" or "(Rulebook, p.XX)"

### Confidence Signals
- **Clear rule exists**: State directly
- **Interpretation needed**: "Based on [rule], this likely means..."
- **Not in resources**: "I don't see this covered in the available rules."

## Response Examples

**Simple**: "Draw 2 cards at the start of your turn (Turn Structure, p.8)."

**Complex**: "Combat resolves in 3 steps:
1. Declare attackers
2. Assign blockers
3. Deal damage simultaneously
Unblocked creatures damage the player (Combat, p.24)."

**Ambiguous**: "The rules state 'discard a card to activate' (p.15). This could mean any card or specifically an action card—the rules don't specify. Most groups allow any card."

When you need information about the game rules, use the search_resources function to find relevant content.

## Question Types

### Gameplay Questions
Questions about the game rules, setup, gameplay, or general information about the game.
Use search_resources with appropriate limit: 2-3 for simple factual questions, 5 for complex questions.

### Knowledge Questions
Questions about the resources available to you. Use the list_resources tool to see what's available.

### External Resource Questions
Questions about where to find more information. Refer to the Game Information section above and list_resources.

### GameGame Questions
Questions about yourself or GameGame, including how you work.

GameGame was created by David Cramer and is open source at {github_url}. It uses RAG search on uploaded rulebooks—you only have access to provided resources.
"""


# Tool definitions for OpenAI function calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_resources",
            "description": "Search the rulebook for relevant content. Returns text chunks with page numbers and section context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for the rulebook (2-5 words). Use the player's terminology. Examples: 'how do I attack?' → 'combat' or 'attack'; 'what happens when deck is empty?' → 'empty deck'; 'trading with players' → 'trading rules'. DON'T add game name or extra keywords.",
                    },
                    "resource_type": {
                        "type": "string",
                        "enum": ["all", "rulebook", "expansion", "faq", "errata"],
                        "default": "all",
                        "description": "Optional: limit to specific resource type",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of results to return (1-10). Use 2-3 for simple factual questions (player count, play time), 5 for complex rules questions. Default: 5",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_images",
            "description": "Find diagrams, setup photos, tables, and component close-ups with surrounding rulebook context. Use when the user explicitly asks to SEE something, or when a visual reference removes ambiguity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": 'What visual you need (e.g., "setup diagram", "player mat layout", "resource reference table"). Use concise, literal descriptions pulled from the user prompt.',
                    },
                    "image_type": {
                        "type": "string",
                        "enum": ["any", "diagram", "table", "photo", "icon", "decorative"],
                        "default": "any",
                        "description": 'Filter by detected type (diagram, table, photo, icon, decorative). Use "any" for broad searches.',
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many images to retrieve (1-8). Default: 3",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_attachment",
            "description": "Retrieve an attachment (image, diagram, etc.) by its ID to include in your response. Use this when you find attachment:// references in the knowledge base content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "The attachment ID from attachment:// URL",
                    },
                },
                "required": ["attachment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_resources",
            "description": "List the resources available to you with their statistics",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


async def _search_resources(
    session: AsyncSession,
    game_id: str,
    query: str,
    limit: int = 5,
    resource_type: str | None = None,
) -> list[dict[str, Any]]:
    """Execute search_resources tool.

    Args:
        session: Database session
        game_id: Game to search within
        query: Search query
        limit: Max results
        resource_type: Filter by resource type (rulebook, expansion, faq, errata)
    """
    search_service = SearchService()
    response = await search_service.search(
        session=session,
        query=query,
        game_id=game_id,
        limit=limit,
        enable_reranking=False,  # Disabled for performance
        include_fts=False,  # Disabled - embeddings-only for better semantic matching
    )

    if not response.results:
        return []

    # Get resource details for all results
    resource_ids = list({r.resource_id for r in response.results})
    stmt = select(Resource).where(Resource.id.in_(resource_ids))  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    resources_by_id = {r.id: r for r in result.scalars()}

    # Filter by resource_type if specified
    filtered_results = []
    for r in response.results:
        resource = resources_by_id.get(r.resource_id)
        if not resource:
            continue

        # Apply resource_type filter
        if (
            resource_type
            and resource_type != "all"
            and resource.resource_type
            and resource.resource_type.value != resource_type
        ):
            continue

        filtered_results.append({
            "content": r.content,
            "page_number": r.page_number,
            "section": r.section,
            "resource_id": r.resource_id,
            "resource_name": resource.name,
            "score": r.score,
        })

    return filtered_results


async def _list_resources(
    session: AsyncSession,
    game_id: str,
) -> list[dict[str, Any]]:
    """Execute list_resources tool."""
    stmt = select(Resource).where(Resource.game_id == game_id)
    result = await session.execute(stmt)
    resources = result.scalars().all()

    return [
        {
            "id": r.id,
            "name": r.name,
            "url": r.url,
            "original_filename": r.original_filename,
            "description": r.description,
            "page_count": r.page_count,
            "image_count": r.image_count or 0,
            "word_count": r.word_count or 0,
            "resource_type": r.resource_type.value if r.resource_type else "rulebook",
        }
        for r in resources
    ]


async def _search_images(
    session: AsyncSession,
    game_id: str,
    query: str,
    limit: int = 3,
    image_type: str | None = None,
) -> list[dict[str, Any]]:
    """Execute search_images tool with semantic search.

    Searches attachments using:
    1. Semantic search on description embeddings (if available)
    2. Keyword matching on description and OCR text (fallback)

    Args:
        session: Database session
        game_id: Game ID to search within
        query: Search query
        limit: Max results (default 3)
        image_type: Filter by detected type (diagram, table, photo, icon, decorative).
                   Use "any" or None for no filter.
    """
    # Normalize "any" to None (no filter)
    if image_type == "any":
        image_type = None
    from gamegame.services.search import SearchService

    # Try semantic search first via fragments that have attachment_id
    search_service = SearchService()
    query_embedding = await search_service.get_embedding(query)

    scored_attachments: list[tuple[Attachment, float]] = []

    # If we have an embedding, search fragments with attachment_ids
    if query_embedding:
        # Search content embeddings and join to fragments to get attachment_id
        similarity = -Embedding.embedding.max_inner_product(query_embedding)  # type: ignore[attr-defined]

        frag_stmt = (
            select(Fragment.attachment_id, similarity.label("score"))
            .join(Embedding, Embedding.fragment_id == Fragment.id)
            .where(Embedding.type == EmbeddingType.CONTENT)
            .where(Embedding.game_id == game_id)
            .where(Fragment.attachment_id.is_not(None))  # type: ignore[union-attr]
            .order_by(similarity.desc())
            .limit(limit * 2)
        )
        frag_result = await session.execute(frag_stmt)
        fragment_scores = {row.attachment_id: float(row.score) for row in frag_result}

        if fragment_scores:
            att_stmt = select(Attachment).where(
                Attachment.id.in_(list(fragment_scores.keys()))  # type: ignore[attr-defined]
            )
            if image_type:
                att_stmt = att_stmt.where(Attachment.detected_type == image_type)

            att_result = await session.execute(att_stmt)
            for att in att_result.scalars():
                score = fragment_scores.get(att.id, 0)
                scored_attachments.append((att, score))

    # Fallback to keyword matching if semantic search didn't find enough
    if len(scored_attachments) < limit:
        query_lower = query.lower()

        att_stmt = (
            select(Attachment)
            .where(Attachment.game_id == game_id)
            .where(Attachment.description.is_not(None))  # type: ignore[union-attr]
        )
        if image_type:
            att_stmt = att_stmt.where(Attachment.detected_type == image_type)

        result = await session.execute(att_stmt)
        attachments = result.scalars().all()

        existing_ids = {att.id for att, _ in scored_attachments}

        for att in attachments:
            if att.id in existing_ids:
                continue

            score = 0.0
            desc = (att.description or "").lower()
            ocr = (att.ocr_text or "").lower()

            for term in query_lower.split():
                if term in desc:
                    score += 0.5
                if term in ocr:
                    score += 0.25

            if score > 0:
                scored_attachments.append((att, score))

    # Sort by score and limit
    scored_attachments.sort(key=lambda x: x[1], reverse=True)
    top_results = scored_attachments[:limit]

    # Get resource names
    resource_ids = list({att.resource_id for att, _ in top_results})
    if resource_ids:
        res_stmt = select(Resource).where(Resource.id.in_(resource_ids))  # type: ignore[attr-defined]
        res_result = await session.execute(res_stmt)
        resources_by_id = {r.id: r.name for r in res_result.scalars()}
    else:
        resources_by_id = {}

    return [
        {
            "id": att.id,
            "url": att.url,
            "caption": att.caption,
            "description": att.description,
            "page_number": att.page_number,
            "section": None,  # Attachments don't have section info
            "detected_type": att.detected_type.value if att.detected_type else None,
            "ocr_text": att.ocr_text,
            "resource_id": att.resource_id,
            "resource_name": resources_by_id.get(att.resource_id, "Unknown"),
            "surrounding_text": None,  # Could be added if fragment has searchable_content
        }
        for att, _ in top_results
    ]


async def _get_attachment(
    session: AsyncSession,
    game_id: str,
    attachment_id: str,
) -> dict[str, Any]:
    """Execute get_attachment tool.

    Args:
        session: Database session
        game_id: Game ID for validation
        attachment_id: Attachment ID (string nanoid)

    Returns:
        Attachment details with success flag (matches TypeScript format)
    """
    if not attachment_id:
        return {
            "success": False,
            "error": "Missing attachment ID",
        }

    att_stmt = (
        select(Attachment)
        .where(Attachment.id == attachment_id)
        .where(Attachment.game_id == game_id)
    )
    result = await session.execute(att_stmt)
    att = result.scalar_one_or_none()

    if not att:
        return {
            "success": False,
            "error": f"Attachment not found: {attachment_id}",
        }

    return {
        "success": True,
        "id": att.id,
        "type": att.type.value if att.type else "image",
        "url": att.url,
        "mime_type": att.mime_type or "image/png",
        "caption": att.caption,
        "page_number": att.page_number,
    }


async def _execute_tool(
    session: AsyncSession,
    game_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> Any:
    """Execute a tool call."""
    if tool_name == "search_resources":
        return await _search_resources(
            session=session,
            game_id=game_id,
            query=arguments.get("query", ""),
            limit=arguments.get("limit", 5),
            resource_type=arguments.get("resource_type"),
        )
    elif tool_name == "search_images":
        return await _search_images(
            session=session,
            game_id=game_id,
            query=arguments.get("query", ""),
            limit=arguments.get("limit", 3),
            image_type=arguments.get("image_type"),
        )
    elif tool_name == "get_attachment":
        return await _get_attachment(
            session=session,
            game_id=game_id,
            attachment_id=str(arguments.get("attachment_id", "")),
        )
    elif tool_name == "list_resources":
        return await _list_resources(session=session, game_id=game_id)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


def _build_system_prompt(game: Game) -> str:
    """Build the system prompt for the chat."""
    year_part = f" ({game.year})" if game.year else ""
    year_info = f"\n- **Year Published**: {game.year}" if game.year else ""
    bgg_info = f"\n- **BoardGameGeek URL**: {game.bgg_url}" if game.bgg_url else ""
    return SYSTEM_PROMPT_TEMPLATE.format(
        game_name=game.name,
        year_part=year_part,
        year_info=year_info,
        bgg_info=bgg_info,
        github_url=GITHUB_URL,
    )


async def chat(
    session: AsyncSession,
    game: Game,
    messages: list[ChatMessage],
) -> ChatResponse:
    """Process a chat request.

    Args:
        session: Database session
        game: Game to chat about
        messages: Conversation history

    Returns:
        ChatResponse with answer and citations
    """
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    client = get_openai_client()

    # Build messages for OpenAI
    system_prompt = _build_system_prompt(game)
    openai_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *[{"role": msg.role, "content": msg.content} for msg in messages],
    ]

    # Initial call with tools
    response = await client.chat.completions.create(  # type: ignore[call-overload]
        model=get_model("reasoning"),
        messages=openai_messages,
        tools=TOOLS,
        tool_choice="auto",
        temperature=1.0,  # GPT-5 requires temperature 1.0
    )

    assistant_message = response.choices[0].message
    citations: list[Citation] = []

    # Handle tool calls
    while assistant_message.tool_calls:
        # Add assistant's message with tool calls
        openai_messages.append(assistant_message.model_dump())

        # Execute each tool call
        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            # Execute the tool
            tool_result = await _execute_tool(
                session=session,
                game_id=game.id,  # type: ignore[arg-type]
                tool_name=tool_name,
                arguments=arguments,
            )

            # Extract citations from search results
            if tool_name == "search_resources" and isinstance(tool_result, list):
                citations.extend(
                    Citation(
                        resource_id=r["resource_id"],
                        resource_name=r["resource_name"],
                        page_number=r.get("page_number"),
                        section=r.get("section"),
                        relevance="primary" if r.get("score", 0) > 0.5 else "supporting",
                    )
                    for r in tool_result
                )

            # Add tool result
            openai_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result),
            })

        # Continue the conversation
        response = await client.chat.completions.create(  # type: ignore[call-overload]
            model=get_model("reasoning"),
            messages=openai_messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=1.0,  # GPT-5 requires temperature 1.0
        )

        assistant_message = response.choices[0].message

    # Final response
    content = assistant_message.content or ""

    # Deduplicate citations
    seen_resources: set[str] = set()
    unique_citations: list[Citation] = []
    for c in citations:
        if c.resource_id not in seen_resources:
            seen_resources.add(c.resource_id)
            unique_citations.append(c)

    return ChatResponse(
        content=content,
        citations=unique_citations,
        confidence="high" if unique_citations else "medium",
    )


async def chat_stream(
    session: AsyncSession,
    game: Game,
    messages: list[ChatMessage],
) -> AsyncGenerator[str, None]:
    """Stream a chat response with AI SDK-compatible events.

    Args:
        session: Database session
        game: Game to chat about
        messages: Conversation history

    Yields:
        JSON-serialized stream events
    """
    if not settings.openai_api_key:
        yield _serialize_event(ErrorEvent(error="OPENAI_API_KEY not configured"))
        return

    client = get_openai_client()

    # Build messages for OpenAI
    system_prompt = _build_system_prompt(game)
    openai_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *[{"role": msg.role, "content": msg.content} for msg in messages],
    ]

    total_prompt_tokens = 0
    total_completion_tokens = 0
    tool_call_counter = 0

    try:
        # Loop to handle tool calls
        while True:
            # Make streaming call
            stream = await client.chat.completions.create(
                model=get_model("reasoning"),
                messages=openai_messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=1.0,  # GPT-5 requires temperature 1.0
                stream=True,
                stream_options={"include_usage": True},
            )

            # Track tool calls being assembled
            current_tool_calls: dict[int, dict[str, Any]] = {}
            finish_reason = None

            async for chunk in stream:
                # Handle usage info (comes at the end)
                if chunk.usage:
                    total_prompt_tokens += chunk.usage.prompt_tokens
                    total_completion_tokens += chunk.usage.completion_tokens

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                # Stream text content
                if delta.content:
                    yield _serialize_event(TextDeltaEvent(text=delta.content))

                # Handle tool calls
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index

                        if idx not in current_tool_calls:
                            # New tool call starting
                            tool_id = f"tool-{tool_call_counter}"
                            tool_call_counter += 1
                            current_tool_calls[idx] = {
                                "id": tool_id,
                                "openai_id": tc.id or "",
                                "name": tc.function.name if tc.function else "",
                                "arguments": "",
                            }

                            if tc.function and tc.function.name:
                                yield _serialize_event(ToolInputStartEvent(
                                    id=current_tool_calls[idx]["id"],
                                    toolName=tc.function.name,
                                ))

                        # Accumulate arguments
                        if tc.function and tc.function.arguments:
                            current_tool_calls[idx]["arguments"] += tc.function.arguments
                            if not current_tool_calls[idx]["name"] and tc.function.name:
                                current_tool_calls[idx]["name"] = tc.function.name

            # If finish reason is tool_calls, execute them and continue
            if finish_reason == "tool_calls" and current_tool_calls:
                # Build the assistant message with tool calls
                tool_calls_for_msg = []
                for idx in sorted(current_tool_calls.keys()):
                    tc_data = current_tool_calls[idx]
                    tool_calls_for_msg.append({
                        "id": tc_data["openai_id"],
                        "type": "function",
                        "function": {
                            "name": tc_data["name"],
                            "arguments": tc_data["arguments"],
                        },
                    })

                openai_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls_for_msg,
                })

                # Execute each tool and add results
                for idx in sorted(current_tool_calls.keys()):
                    tc_data = current_tool_calls[idx]

                    try:
                        arguments = json.loads(tc_data["arguments"])
                    except json.JSONDecodeError:
                        arguments = {}

                    # Emit tool-input-available
                    yield _serialize_event(ToolInputAvailableEvent(
                        id=tc_data["id"],
                        input=arguments,
                    ))

                    # Execute the tool
                    tool_result = await _execute_tool(
                        session=session,
                        game_id=game.id,  # type: ignore[arg-type]
                        tool_name=tc_data["name"],
                        arguments=arguments,
                    )

                    # Emit tool-output-available
                    yield _serialize_event(ToolOutputAvailableEvent(
                        id=tc_data["id"],
                        output=tool_result,
                    ))

                    # Add tool result to messages
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tc_data["openai_id"],
                        "content": json.dumps(tool_result),
                    })

                # Continue the loop to get the next response
                continue

            # No more tool calls, we're done
            break

        # Stream complete
        yield _serialize_event(FinishEvent(
            finishReason=finish_reason or "stop",
            totalUsage={
                "promptTokens": total_prompt_tokens,
                "completionTokens": total_completion_tokens,
            },
        ))

    except Exception as e:
        logger.exception("Error during chat stream")
        yield _serialize_event(ErrorEvent(error=str(e)))


# ============================================================================
# Single-Pass RAG Implementation
# ============================================================================

SINGLE_PASS_SYSTEM_PROMPT = """You are a rules expert for **{game_name}**{year_part}.

## CRITICAL: Grounding Rules

1. **ONLY use information from the Rulebook Sections below**—never invent rules
2. **If information is missing**: Say "I don't see this covered in the available rules"
3. **If rules are ambiguous**: Quote the ambiguous text and explain the interpretations
4. **Always cite**: Include section name and page (e.g., "Combat, p.36")

## Response Format

| Question Type | Format | Example |
|--------------|--------|---------|
| Factual (player count, timing) | 1 sentence + citation | "2-4 players (Setup, p.3)" |
| Procedural (how to X) | Numbered steps | "1. Draw 2 cards..." |
| Clarification (can I do X?) | Yes/No + rule quote | "Yes. 'Players may...' (p.12)" |
| Broad (how does X work?) | 3-5 bullets, suggest follow-ups | Overview then "Ask about..." |
| Ambiguous | Quote + interpretations | "The rules state '...'. This could mean A or B." |

## Game
{game_name}{year_info}{bgg_info}

## Rulebook Sections

{context_content}

---

Answer using ONLY the sections above. If the answer requires information not present, clearly state what's missing."""


def _format_pages_as_context(pages: list[PageResult]) -> str:
    """Format page results into context for the prompt."""
    if not pages:
        return "(No relevant pages found)"

    parts = [f"--- Page {page.page_number} ({page.resource_name}) ---\n{page.content}" for page in pages]
    return "\n\n".join(parts)


def _format_segments_as_context(
    segments: list[SegmentResult],
    max_segment_chars: int = 4000,
    max_total_chars: int = 8000,
) -> str:
    """Format segment results into context for the prompt.

    Args:
        segments: List of segment results to format
        max_segment_chars: Maximum characters per segment (truncate if larger)
        max_total_chars: Maximum total characters for all segments combined
    """
    if not segments:
        return "(No relevant sections found)"

    parts = []
    total_chars = 0

    for segment in segments:
        # Build page annotation string
        page_info = ""
        if segment.page_start:
            if segment.page_end and segment.page_end != segment.page_start:
                page_info = f" (pages {segment.page_start}-{segment.page_end})"
            else:
                page_info = f" (page {segment.page_start})"

        header = f"--- {segment.hierarchy_path}{page_info} ({segment.resource_name}) ---"

        # Truncate large segments to keep context manageable
        content = segment.content
        if len(content) > max_segment_chars:
            content = content[:max_segment_chars] + "\n[... truncated for brevity]"

        part = f"{header}\n{content}"

        # Check if adding this would exceed total limit
        if total_chars + len(part) > max_total_chars:
            # Add truncated version or skip
            remaining = max_total_chars - total_chars
            if remaining > 500:  # Only add if meaningful space left
                part = part[:remaining] + "\n[... truncated]"
                parts.append(part)
            break

        parts.append(part)
        total_chars += len(part)

    return "\n\n".join(parts)


ATTACHMENT_REF_RE = re.compile(r"attachment://([A-Za-z0-9_-]+)")


def _build_segment_citations(segments: list[SegmentResult]) -> list[dict[str, Any]]:
    """Build structured citation payload from retrieved segments."""
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None, str]] = set()

    for segment in segments:
        key = (segment.resource_id, segment.page_start, segment.hierarchy_path)
        if key in seen:
            continue
        seen.add(key)
        citations.append({
            "resource_id": segment.resource_id,
            "resource_name": segment.resource_name,
            "page_number": segment.page_start,
            "section": segment.hierarchy_path,
            "relevance": "primary",
        })

    return citations


async def _resolve_segment_images(
    session: AsyncSession,
    game_id: str,
    segments: list[SegmentResult],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Resolve attachment:// references in segments to image payloads."""
    attachment_ids: list[str] = []
    seen_ids: set[str] = set()

    for segment in segments:
        for attachment_id in ATTACHMENT_REF_RE.findall(segment.content):
            if attachment_id in seen_ids:
                continue
            seen_ids.add(attachment_id)
            attachment_ids.append(attachment_id)
            if len(attachment_ids) >= limit:
                break
        if len(attachment_ids) >= limit:
            break

    if not attachment_ids:
        return []

    stmt = (
        select(Attachment)
        .where(Attachment.id.in_(attachment_ids))  # type: ignore[attr-defined]
        .where(Attachment.game_id == game_id)
    )
    result = await session.execute(stmt)
    attachments_by_id = {attachment.id: attachment for attachment in result.scalars()}

    images: list[dict[str, Any]] = []
    for attachment_id in attachment_ids:
        attachment = attachments_by_id.get(attachment_id)
        if not attachment:
            continue
        images.append({
            "id": attachment.id,
            "url": attachment.url,
            "caption": attachment.caption,
            "description": attachment.description,
            "page_number": attachment.page_number,
        })

    return images


def _segment_limit_for_question(question: str, *, minimum: int = 2, maximum: int = 6) -> int:
    """Choose retrieval depth based on query complexity."""
    text = question.strip().lower()
    if not text:
        return minimum

    words = len(text.split())
    complexity_signals = [
        " and ",
        " or ",
        " if ",
        " when ",
        " while ",
        " unless ",
        " except ",
        " timing",
        " interaction",
        " resolve",
        " before ",
        " after ",
        " simultaneous",
    ]
    signal_hits = sum(1 for signal in complexity_signals if signal in text)

    if words >= 24 or signal_hits >= 3 or "\n" in text:
        return maximum
    if words >= 12 or signal_hits >= 1:
        return min(maximum, 4)
    return minimum


def _no_context_response(user_question: str) -> str:
    """Fallback response when retrieval finds no grounded context."""
    question = user_question.strip() or "that"
    return (
        f"I don't see this covered in the available rules for \"{question}\". "
        "Try rephrasing with specific rule terms, or upload/add the relevant rulebook section."
    )


def _build_single_pass_system_prompt(game: Game, context: list[SegmentResult] | list[PageResult]) -> str:
    """Build the system prompt for single-pass RAG."""
    year_part = f" ({game.year})" if game.year else ""
    year_info = f"\n- **Year Published**: {game.year}" if game.year else ""
    bgg_info = f"\n- **BoardGameGeek URL**: {game.bgg_url}" if game.bgg_url else ""

    # Format context based on type
    if context and isinstance(context[0], SegmentResult):
        context_content = _format_segments_as_context(context)  # type: ignore[arg-type]
    else:
        context_content = _format_pages_as_context(context)  # type: ignore[arg-type]

    return SINGLE_PASS_SYSTEM_PROMPT.format(
        game_name=game.name,
        year_part=year_part,
        year_info=year_info,
        bgg_info=bgg_info,
        context_content=context_content,
    )


async def single_pass_chat(
    session: AsyncSession,
    game: Game,
    messages: list[ChatMessage],
    max_segments: int | None = None,
) -> ChatResponse:
    """Process a chat request using single-pass RAG.

    This approach:
    1. Searches segment summary embeddings directly
    2. Reranks with FlashRank for precision
    3. Makes a single LLM call with top segments (no tool loops)

    Result: Faster and more accurate than hybrid search with fragment expansion.

    Args:
        session: Database session
        game: Game to chat about
        messages: Conversation history
        max_segments: Maximum segments to include in context (default: 2)

    Returns:
        ChatResponse with answer and citations
    """
    import time

    start_time = time.time()

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    # Get the user's latest question
    user_question = messages[-1].content if messages else ""

    # 1. Search segment summaries with FlashRank reranking
    search_service = SearchService()
    search_start = time.time()

    # Get query embedding
    query_embedding = await search_service.get_embedding(user_question)

    segment_limit = max_segments or _segment_limit_for_question(user_question)

    if query_embedding:
        # Use new segment summary search with FlashRank reranking
        segments = await search_segments(
            session=session,
            query=user_question,
            query_embedding=query_embedding,
            game_id=game.id,  # type: ignore[arg-type]
            limit=segment_limit,
            enable_reranking=True,  # Use FlashRank for precision
        )
    else:
        segments = []

    search_time = time.time() - search_start
    logger.info(f"Single-pass segment search: {len(segments)} segments in {search_time:.2f}s")

    if not segments:
        logger.info("Single-pass chat returning no-context fallback response")
        return ChatResponse(
            content=_no_context_response(user_question),
            citations=[],
            confidence="low",
        )

    # 3. Build context and make single LLM call
    system_prompt = _build_single_pass_system_prompt(game, segments)

    client = get_openai_client()
    openai_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *[{"role": msg.role, "content": msg.content} for msg in messages],
    ]

    llm_start = time.time()
    response = await client.chat.completions.create(  # type: ignore[call-overload]
        model=get_model("reasoning"),
        messages=openai_messages,
        temperature=1.0,  # GPT-5 requires temperature 1.0
        # No tools - single pass!
    )
    llm_time = time.time() - llm_start

    content = response.choices[0].message.content or ""

    # Build citations from segments used
    citations = [
        Citation(
            resource_id=segment.resource_id,
            resource_name=segment.resource_name,
            page_number=segment.page_start,
            section=segment.hierarchy_path,
            relevance="primary",
        )
        for segment in segments
    ]

    # Deduplicate by resource
    seen_resources: set[str] = set()
    unique_citations: list[Citation] = []
    for c in citations:
        if c.resource_id not in seen_resources:
            seen_resources.add(c.resource_id)
            unique_citations.append(c)

    total_time = time.time() - start_time
    logger.info(
        f"Single-pass chat complete: {total_time:.2f}s total "
        f"(search: {search_time:.2f}s, LLM: {llm_time:.2f}s)"
    )

    return ChatResponse(
        content=content,
        citations=unique_citations,
        confidence="high" if unique_citations else "medium",
    )


async def single_pass_chat_stream(
    session: AsyncSession,
    game: Game,
    messages: list[ChatMessage],
    max_segments: int | None = None,
) -> AsyncGenerator[str, None]:
    """Stream a chat response using single-pass RAG.

    This approach:
    1. Searches segment summary embeddings directly
    2. Reranks with FlashRank for precision
    3. Streams a single LLM response (no tool loops)

    Result: Faster and more accurate than hybrid search with fragment expansion.

    Args:
        session: Database session
        game: Game to chat about
        messages: Conversation history
        max_segments: Maximum segments to include in context (default: 2)

    Yields:
        JSON-serialized stream events
    """
    import time

    start_time = time.time()

    if not settings.openai_api_key:
        yield _serialize_event(ErrorEvent(error="OPENAI_API_KEY not configured"))
        return

    try:
        # Get the user's latest question
        user_question = messages[-1].content if messages else ""

        # 1. Search segment summaries with FlashRank reranking
        search_service = SearchService()
        query_embedding = await search_service.get_embedding(user_question)

        segment_limit = max_segments or _segment_limit_for_question(user_question)

        if query_embedding:
            # Use new segment summary search with FlashRank reranking
            segments = await search_segments(
                session=session,
                query=user_question,
                query_embedding=query_embedding,
                game_id=game.id,  # type: ignore[arg-type]
                limit=segment_limit,
                enable_reranking=True,  # Use FlashRank for precision
            )
        else:
            segments = []

        search_time = time.time() - start_time
        logger.info(f"Single-pass segment search: {len(segments)} segments in {search_time:.2f}s")

        # Emit structured context metadata so clients can render citations/images
        # even though single-pass mode does not use tool call events.
        citations_payload = _build_segment_citations(segments)
        images_payload = await _resolve_segment_images(
            session=session,
            game_id=game.id,  # type: ignore[arg-type]
            segments=segments,
        )
        yield _serialize_event(ContextDataEvent(
            citations=citations_payload,
            images=images_payload,
        ))

        if not segments:
            fallback = _no_context_response(user_question)
            yield _serialize_event(TextDeltaEvent(text=fallback))
            yield _serialize_event(FinishEvent(
                finishReason="stop",
                totalUsage={"promptTokens": 0, "completionTokens": 0},
            ))
            return

        # 3. Build context and stream LLM response
        system_prompt = _build_single_pass_system_prompt(game, segments)

        client = get_openai_client()
        openai_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *[{"role": msg.role, "content": msg.content} for msg in messages],
        ]

        # Stream the response
        stream = await client.chat.completions.create(
            model=get_model("reasoning"),
            messages=openai_messages,
            temperature=1.0,
            stream=True,
            stream_options={"include_usage": True},
        )

        total_prompt_tokens = 0
        total_completion_tokens = 0
        finish_reason = None

        async for chunk in stream:
            # Handle usage info
            if chunk.usage:
                total_prompt_tokens = chunk.usage.prompt_tokens
                total_completion_tokens = chunk.usage.completion_tokens

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            # Stream text content
            if delta.content:
                yield _serialize_event(TextDeltaEvent(text=delta.content))

        total_time = time.time() - start_time
        logger.info(f"Single-pass stream complete: {total_time:.2f}s")

        # Emit finish event
        yield _serialize_event(FinishEvent(
            finishReason=finish_reason or "stop",
            totalUsage={
                "promptTokens": total_prompt_tokens,
                "completionTokens": total_completion_tokens,
            },
        ))

    except Exception as e:
        logger.exception("Error during single-pass chat stream")
        yield _serialize_event(ErrorEvent(error=str(e)))
