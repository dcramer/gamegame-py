"""VISION stage - Analyze images using GPT-4o vision."""

import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

from gamegame.config import settings
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import create_chat_completion
from gamegame.utils.image import detect_mime_type, strip_data_url_prefix


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


ANALYSIS_PROMPT = """Analyze this image from a board game rulebook for searchability.

Context:
{context}

Your description should help players FIND this image when searching for related game concepts.

Provide analysis with:
1. **description**: ALWAYS write a description (2-4 sentences), even for decorative or low-quality images. Include:
   - What the image shows (components, scenes, visual elements)
   - Any game concepts, rules, or mechanics it illustrates
   - Key game terms and component names visible or implied
   - For decorative images: describe the artwork/illustration theme
   - Do NOT start with "Photograph of", "Image of", "Diagram of", etc. — just describe the content directly.
2. **quality**: "good" (clear, readable, useful) or "bad" (blurry, too small, unclear)
3. **relevant**: true if it contains useful gameplay information, false if purely decorative
4. **type**: One of: diagram, table, photo, icon, decorative
5. **ocrText**: Extract any text visible in tables/diagrams, or null if none

Example descriptions:
- "A special card that awards victory points for achieving a specific milestone. Shows the point value, conditions to earn it, and how it can be lost to another player."
- "Setup diagram showing initial board placement with labeled positions A, B, and C. Arrows indicate valid placement locations for player pieces along edges and intersections."
- "Resource trading reference table listing exchange rates between different resource types and the bank."

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


def extract_image_context(
    image_id: str,
    markdown: str,
    chars_before: int = 300,
    chars_after: int = 200,
    use_attachment_url: bool = False,
) -> tuple[str | None, str | None]:
    """Extract section and surrounding text for an image from markdown.

    Args:
        image_id: The image ID to find in the markdown
        markdown: The full markdown content
        chars_before: Characters to extract before the image
        chars_after: Characters to extract after the image
        use_attachment_url: If True, search for attachment://image_id pattern
            (used for processed content). If False, search for raw image_id
            (used during pipeline processing with Mistral IDs).

    Returns:
        Tuple of (section_header, surrounding_text)
    """
    import re

    # Find the image reference in markdown
    # Pipeline uses: ![description](mistral_id)
    # Processed content uses: ![description](attachment://attachment_id)
    if use_attachment_url:
        pattern = rf"!\[[^\]]*\]\(attachment://{re.escape(image_id)}\)"
    else:
        pattern = rf"!\[[^\]]*\]\({re.escape(image_id)}\)"
    match = re.search(pattern, markdown)

    if not match:
        return None, None

    img_pos = match.start()

    # Extract surrounding text
    start = max(0, img_pos - chars_before)
    end = min(len(markdown), match.end() + chars_after)

    # Get text before and after, excluding the image reference itself
    text_before = markdown[start:img_pos].strip()
    text_after = markdown[match.end():end].strip()

    # Clean up the surrounding text - remove other image references
    text_before = re.sub(r"!\[[^\]]*\]\([^)]+\)", "[image]", text_before)
    text_after = re.sub(r"!\[[^\]]*\]\([^)]+\)", "[image]", text_after)

    surrounding = f"{text_before} [...image...] {text_after}".strip()

    # Find the nearest section header above the image
    section_header = None
    text_before_image = markdown[:img_pos]

    # Look for markdown headers (# Header, ## Header, etc.)
    header_matches = list(re.finditer(r"^(#{1,4})\s+(.+)$", text_before_image, re.MULTILINE))
    if header_matches:
        # Get the last (nearest) header
        last_header = header_matches[-1]
        section_header = last_header.group(2).strip()

    return section_header, surrounding


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
        # Limit surrounding text to 600 chars
        text = context.surrounding_text[:600]
        parts.append(f'\nSurrounding rulebook text (where this image appears):\n"""{text}"""')
    return "\n".join(parts)


# Note: detect_mime_type and strip_data_url_prefix are imported from gamegame.utils.image


async def analyze_single_image(
    image_data: bytes | str,
    context: ImageAnalysisContext,
) -> ImageAnalysisResult:
    """Analyze a single image using GPT-4o vision.

    Args:
        image_data: Image bytes or base64 string (may include data URL prefix)
        context: Context about the image

    Returns:
        ImageAnalysisResult with description, quality, type, etc.
    """
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    # Convert to bytes if base64 string, stripping data URL prefix if present
    if isinstance(image_data, bytes):
        image_bytes = image_data
    else:
        base64_str = strip_data_url_prefix(image_data)
        image_bytes = base64.b64decode(base64_str)

    mime_type = detect_mime_type(image_bytes)

    # Check if the format is supported by OpenAI Vision API
    supported_formats = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    if mime_type not in supported_formats:
        raise ValueError(
            f"Unsupported image format: {mime_type}. "
            f"OpenAI Vision API only supports: {', '.join(sorted(supported_formats))}"
        )

    base64_data = base64.b64encode(image_bytes).decode("utf-8")

    # Build the prompt
    context_str = _build_context_string(context)
    prompt = ANALYSIS_PROMPT.format(context=context_str)

    # Call vision model with structured output (using wrapper with retry logic)
    response = await create_chat_completion(
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
        max_completion_tokens=2500,
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
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list[ImageAnalysisResult]:
    """Analyze multiple images sequentially.

    Args:
        images: List of (image_data, context) tuples
        on_progress: Optional async callback(completed, total) for progress updates

    Returns:
        List of ImageAnalysisResult in same order as input
    """
    import logging

    logger = logging.getLogger(__name__)

    results: list[ImageAnalysisResult] = []
    total = len(images)

    logger.info(f"Starting image analysis: {total} images")

    for idx, (img_data, ctx) in enumerate(images):
        page_num = ctx.page_number

        try:
            result = await analyze_single_image(img_data, ctx)
            logger.info(
                f"Image {idx + 1}/{total} (page {page_num}): "
                f"type={result.image_type.value}, quality={result.quality.value}"
            )
            results.append(result)
        except Exception as e:
            logger.warning(f"Image {idx + 1}/{total} (page {page_num}) analysis failed: {e}")
            results.append(
                ImageAnalysisResult(
                    description="Analysis failed",
                    quality=ImageQuality.BAD,
                    relevant=False,
                    image_type=ImageType.DECORATIVE,
                    ocr_text=None,
                )
            )

        # Progress callback
        if on_progress:
            await on_progress(idx + 1, total)

    logger.info(f"Completed image analysis: {total} images processed")
    return results
