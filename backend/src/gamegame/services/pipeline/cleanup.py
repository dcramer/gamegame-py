"""CLEANUP stage - Clean and normalize markdown from OCR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gamegame.config import settings
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import get_openai_client

if TYPE_CHECKING:
    from openai import AsyncOpenAI

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
) -> str:
    """Clean and normalize markdown content using LLM.

    Args:
        markdown: Raw markdown from OCR
        chunk_size: Max size per LLM call (to stay within context limits)

    Returns:
        Cleaned markdown
    """
    if not markdown.strip():
        return ""

    if not settings.openai_api_key:
        # Return as-is if no API key
        return markdown

    client = get_openai_client()

    # If content is small enough, clean in one go
    if len(markdown) <= chunk_size:
        return await _cleanup_chunk(client, markdown)

    # Split into chunks and clean each
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

    # Clean each chunk
    cleaned_chunks: list[str] = []
    for chunk in chunks:
        cleaned = await _cleanup_chunk(client, chunk)
        cleaned_chunks.append(cleaned)

    return "\n\n".join(cleaned_chunks)


async def _cleanup_chunk(client: AsyncOpenAI, markdown: str) -> str:
    """Clean a single chunk of markdown."""
    response = await client.chat.completions.create(
        model=get_model("reasoning"),
        messages=[
            {
                "role": "user",
                "content": CLEANUP_PROMPT.format(markdown=markdown),
            }
        ],
        max_tokens=len(markdown) + 1000,  # Allow some expansion
        temperature=0.3,  # Low temp for consistent cleanup
    )

    return response.choices[0].message.content or markdown
