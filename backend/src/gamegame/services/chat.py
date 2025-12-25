"""Chat service for RAG-based Q&A."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gamegame.config import settings
from gamegame.models import Attachment, Game, Resource
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import get_openai_client
from gamegame.services.search import SearchService

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

    return json.dumps(data)


GITHUB_URL = "https://github.com/dcramer/gamegame"

SYSTEM_PROMPT_TEMPLATE = """You are a knowledgeable expert on the rules of the board game **{game_name}**{year_part}, and being operated on a website called GameGame.

You interpret rules based on the provided resources and give accurate, detailed explanations about gameplay, mechanics, and rule ambiguities.

You assist players in understanding the game, resolving disputes, and ensuring a smooth gaming experience.

Focus on being precise, clear, and neutral. Focus on gameplay rules. Be specific about rules that change based on player count or expansions. Do not advise on gameplay strategy.

## Game Information

You have the following information about this game:
- **Name**: {game_name}{year_info}{bgg_info}

## Response Guidelines

- Be concise and scannable
- Simple questions: 1-2 sentences
- Complex questions: Short summary (2-4 sentences)
- Use bullet points for lists
- Include page numbers when citing rules
- If a rule is ambiguous, explain why and cite the source

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

You and GameGame were originally created by David Cramer and is Open Source and available on GitHub at {github_url}.

GameGame works as a RAG system, using embeddings to find relevant information in the knowledge base from game manuals and other resources. You only have access to the resources that have been provided.

Good follow-ups to questions about yourself or GameGame are which resources are available, or where users can learn more about the game.
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
                        "description": "Natural language search query. Keep it simple and focused on key terms from the user's question (e.g., 'how do docks work' or 'dock rules'). Use the user's exact words when possible. DO NOT add extra context, semicolons, or keyword stuff.",
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
        enable_reranking=False,  # Disabled for performance (matches TypeScript)
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
        from gamegame.models import Fragment

        # Search fragment embeddings that have attachment_id
        similarity = -Fragment.embedding.max_inner_product(query_embedding)  # type: ignore[attr-defined]

        frag_stmt = (
            select(Fragment.attachment_id, similarity.label("score"))
            .where(Fragment.game_id == game_id)
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
