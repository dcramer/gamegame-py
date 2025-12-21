"""INGEST stage - Extract PDF content using Mistral OCR API."""

import base64
from dataclasses import dataclass, field

from mistralai import Mistral

from gamegame.config import settings


@dataclass
class ExtractedImage:
    """An image extracted from a document."""

    id: str
    base64_data: str
    page_number: int
    bbox: dict | None = None  # {x1, y1, x2, y2}
    caption: str | None = None


@dataclass
class ExtractedPage:
    """A page extracted from a document."""

    page_number: int
    markdown: str
    images: list[ExtractedImage] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Result of document extraction."""

    pages: list[ExtractedPage]
    total_pages: int
    raw_markdown: str  # Combined markdown from all pages


async def ingest_document(
    document_bytes: bytes,
    mime_type: str = "application/pdf",
) -> ExtractionResult:
    """Extract text and images from a document using Mistral OCR.

    Args:
        document_bytes: Raw document bytes
        mime_type: MIME type of the document

    Returns:
        ExtractionResult with pages, images, and combined markdown
    """
    if not settings.mistral_api_key:
        raise ValueError("MISTRAL_API_KEY not configured")

    client = Mistral(api_key=settings.mistral_api_key)

    # Encode document as base64 data URL
    base64_doc = base64.b64encode(document_bytes).decode("utf-8")
    document_url = f"data:{mime_type};base64,{base64_doc}"

    # Call Mistral OCR API
    result = await client.ocr.process_async(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": document_url,
        },
        include_image_base64=True,
    )

    # Parse response into our data structures
    pages: list[ExtractedPage] = []
    all_markdown: list[str] = []

    for page_data in result.pages:
        page_number = page_data.index + 1
        markdown = page_data.markdown or ""

        # Extract images from this page
        images: list[ExtractedImage] = [
            ExtractedImage(
                id=img.id,
                base64_data=img.image_base64 or "",
                page_number=page_number,
                bbox=getattr(img, "bbox", None),
                caption=None,  # Mistral doesn't provide captions
            )
            for img in (page_data.images or [])
        ]

        pages.append(
            ExtractedPage(
                page_number=page_number,
                markdown=markdown,
                images=images,
            )
        )
        all_markdown.append(markdown)

    return ExtractionResult(
        pages=pages,
        total_pages=len(pages),
        raw_markdown="\n\n".join(all_markdown),
    )


def get_supported_mime_types() -> set[str]:
    """Get MIME types supported by Mistral OCR."""
    return {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    }
