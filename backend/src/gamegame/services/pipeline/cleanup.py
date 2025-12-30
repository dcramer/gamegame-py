"""CLEANUP stage - Clean and normalize markdown from OCR."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from gamegame.config import settings
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import create_chat_completion

logger = logging.getLogger(__name__)

# Batch size for resumable processing
CLEANUP_BATCH_SIZE = 15

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
    max_concurrency: int = 3,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    on_checkpoint: Callable[[int, list[str]], Awaitable[None]] | None = None,
    resume_from: int = 0,
    previous_results: list[str] | None = None,
) -> str:
    """Clean and normalize markdown content using LLM.

    Processes chunks in batches for resumability. Each batch processes
    in parallel (up to max_concurrency) then checkpoints.

    Args:
        markdown: Raw markdown from OCR
        chunk_size: Max size per LLM call (to stay within context limits)
        max_concurrency: Maximum concurrent API calls (to avoid rate limits)
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

    logger.info(f"Cleanup: Processing {len(chunks)} chunks with max concurrency {max_concurrency}")

    # Initialize results with previous results if resuming
    cleaned_chunks: list[str | None] = list(previous_results) if previous_results else []
    # Pad with None for chunks not yet processed
    while len(cleaned_chunks) < len(chunks):
        cleaned_chunks.append(None)

    if resume_from > 0:
        logger.info(f"Cleanup: Resuming from chunk {resume_from}")

    # Process chunks in batches for checkpointing
    completed_count = resume_from

    for batch_start in range(resume_from, len(chunks), CLEANUP_BATCH_SIZE):
        batch_end = min(batch_start + CLEANUP_BATCH_SIZE, len(chunks))
        batch_indices = list(range(batch_start, batch_end))

        logger.info(f"Cleanup: Processing batch {batch_start}-{batch_end} of {len(chunks)}")

        # Process this batch in parallel with limited concurrency
        semaphore = asyncio.Semaphore(max_concurrency)

        async def cleanup_with_semaphore(idx: int, chunk: str) -> tuple[int, str]:
            async with semaphore:
                logger.debug(f"Cleanup: Processing chunk {idx + 1}/{len(chunks)}")
                return idx, await _cleanup_chunk(chunk)

        # Create tasks for this batch only
        tasks = [
            cleanup_with_semaphore(idx, chunks[idx])
            for idx in batch_indices
        ]
        batch_results = await asyncio.gather(*tasks)

        # Store results in correct positions
        for idx, result in batch_results:
            cleaned_chunks[idx] = result
            completed_count += 1

            # Report progress
            if on_progress:
                await on_progress(completed_count, len(chunks))

        # Checkpoint after each batch
        if on_checkpoint:
            # Only include non-None results up to current position
            results_so_far = [c for c in cleaned_chunks[:batch_end] if c is not None]
            await on_checkpoint(batch_end, results_so_far)

        logger.info(f"Cleanup: Completed batch, {completed_count}/{len(chunks)} chunks processed")

    # Filter out any None values (shouldn't happen, but safety check)
    final_results = [c for c in cleaned_chunks if c is not None]

    logger.info(f"Cleanup: Completed {len(chunks)} chunks")
    return "\n\n".join(final_results)


async def _cleanup_chunk(markdown: str) -> str:
    """Clean a single chunk of markdown.

    Uses create_chat_completion which includes:
    - Retry logic (3 attempts with exponential backoff)
    - Circuit breaker for OpenAI failures
    - Configurable timeout from settings
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
    )

    return response.choices[0].message.content or markdown
