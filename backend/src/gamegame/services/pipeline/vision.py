"""VISION stage - Analyze images using GPT-4o vision."""

import asyncio
import base64
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from gamegame.config import settings
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import get_openai_client


class ImageType(str, Enum):
    """Detected type of image."""

    DIAGRAM = "diagram"
    TABLE = "table"
    PHOTO = "photo"
    ICON = "icon"
    DECORATIVE = "decorative"


class ImageQuality(str, Enum):
    """Quality assessment of image."""

    GOOD = "good"
    BAD = "bad"


@dataclass
class ImageAnalysisContext:
    """Context for image analysis."""

    page_number: int
    game_name: str | None = None
    resource_name: str | None = None
    section: str | None = None
    surrounding_text: str | None = None


@dataclass
class ImageAnalysisResult:
    """Result of analyzing a single image."""

    description: str
    quality: ImageQuality
    relevant: bool
    image_type: ImageType
    ocr_text: str | None = None


ANALYSIS_PROMPT = """Analyze this image from a board game rulebook.

Context:
{context}

Provide analysis with:
1. **description**: What's visible (2-3 sentences about game elements, text, spatial relationships)
2. **quality**: "good" (clear, readable, useful) or "bad" (blurry, too small, unclear)
3. **relevant**: true if it contains useful gameplay information, false if decorative
4. **type**: One of: diagram, table, photo, icon, decorative
5. **ocrText**: Extract any text visible in tables/diagrams, or null if none

Respond with valid JSON only."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "quality": {"type": "string", "enum": ["good", "bad"]},
        "relevant": {"type": "boolean"},
        "type": {"type": "string", "enum": ["diagram", "table", "photo", "icon", "decorative"]},
        "ocrText": {"type": ["string", "null"]},
    },
    "required": ["description", "quality", "relevant", "type", "ocrText"],
    "additionalProperties": False,
}


def _build_context_string(context: ImageAnalysisContext) -> str:
    """Build context string for the prompt."""
    parts = [f"- Page: {context.page_number}"]
    if context.game_name:
        parts.append(f"- Game: {context.game_name}")
    if context.resource_name:
        parts.append(f"- Resource: {context.resource_name}")
    if context.section:
        parts.append(f"- Section: {context.section}")
    if context.surrounding_text:
        # Limit surrounding text to 500 chars
        text = context.surrounding_text[:500]
        parts.append(f'\nRelevant rulebook text:\n"""{text}"""')
    return "\n".join(parts)


def _detect_mime_type(image_bytes: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if len(image_bytes) < 12:
        return "image/jpeg"

    # PNG: \x89PNG\r\n\x1a\n
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    # JPEG: \xFF\xD8\xFF
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    # WebP: RIFF....WEBP
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"

    # GIF magic bytes
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

    return "image/jpeg"


async def analyze_single_image(
    image_data: bytes | str,
    context: ImageAnalysisContext,
) -> ImageAnalysisResult:
    """Analyze a single image using GPT-4o vision.

    Args:
        image_data: Image bytes or base64 string
        context: Context about the image

    Returns:
        ImageAnalysisResult with description, quality, type, etc.
    """
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    client = get_openai_client()

    # Convert to base64 if bytes
    if isinstance(image_data, bytes):
        mime_type = _detect_mime_type(image_data)
        base64_data = base64.b64encode(image_data).decode("utf-8")
    else:
        # Assume it's already base64
        base64_data = image_data
        mime_type = "image/jpeg"  # Default, will be overridden if data URL

    # Build the prompt
    context_str = _build_context_string(context)
    prompt = ANALYSIS_PROMPT.format(context=context_str)

    # Call vision model with structured output
    response = await client.chat.completions.create(
        model=get_model("vision"),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
                    },
                ],
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "image_analysis",
                "schema": RESPONSE_SCHEMA,
                "strict": True,
            },
        },
        max_tokens=500,
        temperature=1,  # Required for structured outputs
    )

    # Parse response
    import json

    result = json.loads(response.choices[0].message.content or "{}")

    return ImageAnalysisResult(
        description=result.get("description", ""),
        quality=ImageQuality(result.get("quality", "bad")),
        relevant=result.get("relevant", False),
        image_type=ImageType(result.get("type", "decorative")),
        ocr_text=result.get("ocrText"),
    )


async def analyze_images_batch(
    images: list[tuple[bytes | str, ImageAnalysisContext]],
    batch_size: int = 3,
    delay_between_batches: float = 1.0,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[ImageAnalysisResult]:
    """Analyze multiple images in batches to respect rate limits.

    Args:
        images: List of (image_data, context) tuples
        batch_size: Number of concurrent requests per batch
        delay_between_batches: Seconds to wait between batches
        on_progress: Optional callback(completed, total) for progress updates

    Returns:
        List of ImageAnalysisResult in same order as input
    """
    results: list[ImageAnalysisResult] = []
    total = len(images)

    for i in range(0, len(images), batch_size):
        batch = images[i : i + batch_size]

        # Process batch in parallel
        batch_results = await asyncio.gather(
            *[analyze_single_image(img, ctx) for img, ctx in batch],
            return_exceptions=True,
        )

        # Handle results, converting exceptions to "bad" quality fallback
        for result in batch_results:
            if isinstance(result, Exception):
                # Fallback for failed analysis
                results.append(
                    ImageAnalysisResult(
                        description="Analysis failed",
                        quality=ImageQuality.BAD,
                        relevant=False,
                        image_type=ImageType.DECORATIVE,
                        ocr_text=None,
                    )
                )
            else:
                results.append(result)  # type: ignore[arg-type]

        # Progress callback
        completed = min(i + batch_size, total)
        if on_progress:
            on_progress(completed, total)

        # Delay between batches (except for last batch)
        if i + batch_size < len(images):
            await asyncio.sleep(delay_between_batches)

    return results
