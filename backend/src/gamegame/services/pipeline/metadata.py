"""METADATA stage - Extract metadata from processed content."""

import json
import re
from dataclasses import dataclass

from gamegame.config import settings
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import get_openai_client


@dataclass
class ResourceMetadata:
    """Extracted metadata about a resource."""

    page_count: int
    word_count: int
    image_count: int
    has_tables: bool
    estimated_reading_time_minutes: int


@dataclass
class GeneratedMetadata:
    """LLM-generated metadata for a resource."""

    name: str
    description: str


def count_words(text: str) -> int:
    """Count words in text."""
    # Remove markdown formatting
    text = re.sub(r"[#*_`\[\]()]", " ", text)
    # Split on whitespace
    words = text.split()
    return len(words)


def has_tables(markdown: str) -> bool:
    """Check if markdown contains tables."""
    # Look for pipe characters that indicate tables
    # Pattern: | text | text |
    table_pattern = r"\|[^|]+\|"
    return bool(re.search(table_pattern, markdown))


def extract_metadata(
    markdown: str,
    page_count: int,
    image_count: int,
) -> ResourceMetadata:
    """Extract metadata from processed content.

    Args:
        markdown: Cleaned markdown content
        page_count: Number of pages from extraction
        image_count: Number of images extracted

    Returns:
        ResourceMetadata with counts and flags
    """
    word_count = count_words(markdown)

    # Estimate reading time (average 200 words per minute)
    reading_time = max(1, word_count // 200)

    return ResourceMetadata(
        page_count=page_count,
        word_count=word_count,
        image_count=image_count,
        has_tables=has_tables(markdown),
        estimated_reading_time_minutes=reading_time,
    )


async def generate_resource_metadata(
    markdown: str,
    existing_name: str | None = None,
    original_filename: str | None = None,
    max_content_length: int = 12000,
) -> GeneratedMetadata | None:
    """Generate resource name and description using LLM.

    Args:
        markdown: The markdown content to analyze
        existing_name: Existing resource name (hint)
        original_filename: Original filename (hint)
        max_content_length: Max chars of content to send to LLM

    Returns:
        GeneratedMetadata with name and description, or None on failure
    """
    if not settings.openai_api_key:
        return None

    markdown = markdown.strip()
    if not markdown:
        return None

    # Truncate content if too long
    if len(markdown) > max_content_length:
        markdown = markdown[:max_content_length] + "\n\n..."

    # Build hints
    hints: list[str] = []
    if existing_name:
        hints.append(f"Existing title: {existing_name}")
    if original_filename:
        hints.append(f"Original filename: {original_filename}")

    prompt = f"""Extract metadata for the following board game rulebook markdown.
{('Hints:\\n' + '\\n'.join(hints)) if hints else ''}

Markdown content:
\"\"\"
{markdown}
\"\"\"

Return a JSON object with:
- "name": A short human-friendly document title (e.g., "Core Rulebook", "Player Reference Guide")
- "description": A 2-3 sentence summary highlighting scope, edition, and notable sections

Keep the original document language. If the content does not describe rules, fall back to a neutral generic title."""

    try:
        client = get_openai_client()

        response = await client.chat.completions.create(
            model=get_model("reasoning"),
            messages=[
                {
                    "role": "system",
                    "content": """You extract metadata from board game rulebooks. Be concise and precise.
Return ONLY valid JSON (no markdown, no code fences) with keys "name" and "description".
- name: A short human friendly document title
- description: A 2-3 sentence summary""",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=500,
        )

        content = response.choices[0].message.content
        if not content:
            return None

        # Parse JSON response
        parsed = json.loads(content)

        name = parsed.get("name", "").strip()
        description = parsed.get("description", "").strip()

        if not name or not description:
            return None

        return GeneratedMetadata(name=name, description=description)

    except Exception:
        return None
