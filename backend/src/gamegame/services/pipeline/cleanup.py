"""CLEANUP stage - Clean and normalize markdown from OCR."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

from gamegame.config import settings
from gamegame.models.model_config import get_model, get_model_config
from gamegame.services.openai_client import create_chat_completion

logger = logging.getLogger(__name__)


@dataclass
class CleanupChunk:
    """A chunk of content to be cleaned."""

    content: str
    start_page: int  # 1-indexed, or chunk index if no page info
    end_page: int  # 1-indexed, or chunk index if no page info


# Timeout for cleanup LLM calls (seconds) - 10 minutes to handle large chunks
# with reasoning models that can take time (default chunk size is 20k chars)
CLEANUP_TIMEOUT = 600.0

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


def _chunk_by_pages(
    markdown: str,
    page_boundaries: list[tuple[int, int]],
    max_size: int,
) -> list[CleanupChunk]:
    """Group consecutive pages into chunks without exceeding max_size.

    Args:
        markdown: Full document markdown
        page_boundaries: List of (start_char, end_char) for each page
        max_size: Maximum characters per chunk

    Returns:
        List of CleanupChunk with page ranges
    """
    chunks: list[CleanupChunk] = []
    current_pages: list[tuple[str, int]] = []  # (content, page_num)
    current_size = 0

    for page_num, (start, end) in enumerate(page_boundaries, 1):
        page_content = markdown[start:end]
        page_size = len(page_content)

        # If single page exceeds max, it gets its own chunk
        if page_size > max_size:
            # Finalize current chunk first
            if current_pages:
                combined = "\n\n".join(content for content, _ in current_pages)
                start_pg = current_pages[0][1]
                end_pg = current_pages[-1][1]
                chunks.append(CleanupChunk(combined, start_pg, end_pg))
                current_pages = []
                current_size = 0
            # Add oversized page as its own chunk
            chunks.append(CleanupChunk(page_content, page_num, page_num))
            continue

        # If adding this page would exceed max, finalize current chunk
        if current_size + page_size > max_size and current_pages:
            combined = "\n\n".join(content for content, _ in current_pages)
            start_pg = current_pages[0][1]
            end_pg = current_pages[-1][1]
            chunks.append(CleanupChunk(combined, start_pg, end_pg))
            current_pages = []
            current_size = 0

        current_pages.append((page_content, page_num))
        current_size += page_size + 2  # +2 for \n\n separator

    # Finalize remaining pages
    if current_pages:
        combined = "\n\n".join(content for content, _ in current_pages)
        start_pg = current_pages[0][1]
        end_pg = current_pages[-1][1]
        chunks.append(CleanupChunk(combined, start_pg, end_pg))

    return chunks


def _chunk_by_paragraphs(
    markdown: str,
    max_size: int,
) -> list[CleanupChunk]:
    """Split markdown into chunks at paragraph boundaries.

    Fallback when page boundaries are not available.

    Args:
        markdown: Full document markdown
        max_size: Maximum characters per chunk

    Returns:
        List of CleanupChunk (using chunk index as page numbers)
    """
    paragraphs = markdown.split("\n\n")
    chunks: list[CleanupChunk] = []
    current_paragraphs: list[str] = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)

        # If adding this paragraph would exceed max, finalize current chunk
        if current_size + para_size > max_size and current_paragraphs:
            chunk_idx = len(chunks) + 1
            chunks.append(CleanupChunk(
                "\n\n".join(current_paragraphs),
                chunk_idx,
                chunk_idx,
            ))
            current_paragraphs = []
            current_size = 0

        current_paragraphs.append(para)
        current_size += para_size + 2  # +2 for \n\n separator

    # Finalize remaining paragraphs
    if current_paragraphs:
        chunk_idx = len(chunks) + 1
        chunks.append(CleanupChunk(
            "\n\n".join(current_paragraphs),
            chunk_idx,
            chunk_idx,
        ))

    return chunks


async def cleanup_markdown(
    markdown: str,
    page_boundaries: list[tuple[int, int]] | None = None,
    chunk_size: int | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    on_checkpoint: Callable[[int, list[str]], Awaitable[None]] | None = None,
    resume_from: int = 0,
    previous_results: list[str] | None = None,
) -> str:
    """Clean and normalize markdown content using LLM.

    Processes chunks sequentially with periodic checkpointing for resumability.
    When page_boundaries is provided, chunks are aligned to page boundaries
    for better context coherence.

    Args:
        markdown: Raw markdown from OCR
        page_boundaries: Optional list of (start_char, end_char) for each page.
            When provided, chunking respects page boundaries.
        chunk_size: Max size per LLM call. If None, uses model config default.
        on_progress: Optional callback for progress updates (current, total)
        on_checkpoint: Optional callback for checkpointing (cursor, results).
            Cursor is the last completed end_page (or chunk index if no pages).
        resume_from: Last completed end_page/chunk to resume from (0 = start fresh)
        previous_results: Already-cleaned chunks from previous run

    Returns:
        Cleaned markdown
    """
    # Use configured chunk size if not explicitly provided
    if chunk_size is None:
        chunk_size = get_model_config().cleanup_chunk_size

    if not markdown.strip():
        return ""

    if not settings.openai_api_key:
        # Return as-is if no API key
        return markdown

    # If content is small enough, clean in one go
    if len(markdown) <= chunk_size:
        return await _cleanup_chunk(markdown)

    # Create chunks - prefer page-aware if boundaries available
    if page_boundaries:
        chunks = _chunk_by_pages(markdown, page_boundaries, chunk_size)
        total_pages = len(page_boundaries)
        logger.info(
            f"Cleanup: Processing {len(chunks)} page-aligned chunks "
            f"({total_pages} pages total)"
        )
    else:
        chunks = _chunk_by_paragraphs(markdown, chunk_size)
        logger.info(f"Cleanup: Processing {len(chunks)} paragraph-based chunks")

    # Initialize results with previous results if resuming
    cleaned_chunks: list[str] = list(previous_results) if previous_results else []

    # Find starting index based on resume_from (which is the last completed end_page)
    start_idx = 0
    if resume_from > 0:
        # Find the first chunk whose end_page > resume_from
        for i, chunk in enumerate(chunks):
            if chunk.end_page > resume_from:
                start_idx = i
                break
        else:
            # All chunks already done
            start_idx = len(chunks)

        if page_boundaries:
            logger.info(f"Cleanup: Resuming after page {resume_from}")
        else:
            logger.info(f"Cleanup: Resuming from chunk {start_idx + 1}")

    # Process chunks sequentially with per-item checkpointing
    for idx in range(start_idx, len(chunks)):
        chunk = chunks[idx]

        if page_boundaries:
            if chunk.start_page == chunk.end_page:
                page_info = f"page {chunk.start_page}"
            else:
                page_info = f"pages {chunk.start_page}-{chunk.end_page}"
            logger.info(
                f"Cleanup: Processing chunk {idx + 1}/{len(chunks)} "
                f"({page_info}, {len(chunk.content)} chars)"
            )
        else:
            logger.info(
                f"Cleanup: Processing chunk {idx + 1}/{len(chunks)} "
                f"({len(chunk.content)} chars)"
            )

        # Clean this chunk
        result = await _cleanup_chunk(chunk.content)
        cleaned_chunks.append(result)

        # Report progress and checkpoint after each item
        if on_progress:
            await on_progress(idx + 1, len(chunks))

        if on_checkpoint:
            # Checkpoint with the end_page of this chunk
            await on_checkpoint(chunk.end_page, cleaned_chunks)

    if page_boundaries:
        logger.info(f"Cleanup: Completed {len(chunks)} chunks ({total_pages} pages)")
    else:
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
