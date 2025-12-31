"""CLEANUP stage - Clean and normalize markdown from OCR."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

from gamegame.config import settings
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import create_chat_completion

logger = logging.getLogger(__name__)


# Timeout for cleanup LLM calls (seconds) - longer than default since we process
# large chunks (up to 8000 chars) with reasoning models that can take time
CLEANUP_TIMEOUT = 180.0

CLEANUP_PROMPT = """Clean and normalize this markdown extracted from a board game rulebook PDF.

Fix:
- OCR errors and typos
- Inconsistent formatting
- Broken tables (convert to proper markdown tables)
- Remove artifacts like page numbers, headers/footers
- Fix heading hierarchy (use proper # levels)
- Clean up list formatting

Preserve:
- All game rules and content
- Section structure
- Important formatting like bold/italic for emphasis

Return only the cleaned markdown, no explanations.

Input markdown:
\"\"\"
{markdown}
\"\"\"
"""


async def cleanup_markdown(
    markdown: str,
    chunk_size: int = 8000,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    on_checkpoint: Callable[[int, list[str]], Awaitable[None]] | None = None,
    resume_from: int = 0,
    previous_results: list[str] | None = None,
) -> str:
    """Clean and normalize markdown content using LLM.

    Processes chunks sequentially with periodic checkpointing for resumability.

    Args:
        markdown: Raw markdown from OCR
        chunk_size: Max size per LLM call (to stay within context limits)
        on_progress: Optional callback for progress updates (current, total)
        on_checkpoint: Optional callback for checkpointing (cursor, results)
        resume_from: Chunk index to resume from (0 = start fresh)
        previous_results: Already-cleaned chunks from previous run

    Returns:
        Cleaned markdown
    """
    if not markdown.strip():
        return ""

    if not settings.openai_api_key:
        # Return as-is if no API key
        return markdown

    # If content is small enough, clean in one go
    if len(markdown) <= chunk_size:
        return await _cleanup_chunk(markdown)

    # Split into chunks
    # Split on double newlines to preserve paragraph boundaries
    paragraphs = markdown.split("\n\n")
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_size = 0

    for para in paragraphs:
        if current_size + len(para) > chunk_size and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_size = 0
        current_chunk.append(para)
        current_size += len(para) + 2

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    logger.info(f"Cleanup: Processing {len(chunks)} chunks sequentially")

    # Initialize results with previous results if resuming
    cleaned_chunks: list[str] = list(previous_results) if previous_results else []

    if resume_from > 0:
        logger.info(f"Cleanup: Resuming from chunk {resume_from}")

    # Process chunks sequentially with per-item checkpointing
    for idx in range(resume_from, len(chunks)):
        chunk_chars = len(chunks[idx])
        logger.info(f"Cleanup: Processing chunk {idx + 1}/{len(chunks)} ({chunk_chars} chars)")

        # Clean this chunk
        result = await _cleanup_chunk(chunks[idx])
        cleaned_chunks.append(result)

        # Report progress and checkpoint after each item
        if on_progress:
            await on_progress(idx + 1, len(chunks))

        if on_checkpoint:
            await on_checkpoint(idx + 1, cleaned_chunks)

    logger.info(f"Cleanup: Completed {len(chunks)} chunks")
    return "\n\n".join(cleaned_chunks)


async def _cleanup_chunk(markdown: str) -> str:
    """Clean a single chunk of markdown.

    Uses create_chat_completion which includes:
    - Retry logic (3 attempts with exponential backoff)
    - Circuit breaker for OpenAI failures
    - Extended timeout for large chunk processing
    """
    response = await create_chat_completion(
        model=get_model("reasoning"),
        messages=[
            {
                "role": "user",
                "content": CLEANUP_PROMPT.format(markdown=markdown),
            }
        ],
        max_completion_tokens=len(markdown) + 1000,  # Allow some expansion
        temperature=1,  # GPT-5/GPT-4o requires temperature 1
        timeout=CLEANUP_TIMEOUT,
    )

    return response.choices[0].message.content or markdown
