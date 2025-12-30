"""Shared attachment analysis utilities.

This module provides common functions for analyzing attachments across:
- CLI commands (analyze, reanalyze, reanalyze-failed)
- Background tasks (analyze_attachment)
- Pipeline VISION stage
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gamegame.models import Attachment, Game, Resource
from gamegame.models.attachment import DetectedType, QualityRating
from gamegame.services.pipeline.vision import (
    ImageAnalysisContext,
    ImageAnalysisResult,
    extract_image_context,
)
from gamegame.services.storage import storage


async def build_attachment_context(
    session: AsyncSession,
    attachment: Attachment,
    resource_content: str | None = None,
) -> ImageAnalysisContext:
    """Build analysis context for an attachment.

    Args:
        session: Database session
        attachment: The attachment to build context for
        resource_content: Optional resource content (cleaned markdown) for
            extracting section and surrounding text. If provided, will search
            for attachment:// URL references.

    Returns:
        ImageAnalysisContext with game name, resource name, and optionally
        section and surrounding text.
    """
    # Resolve game name
    game_name = None
    if attachment.game_id:
        stmt = select(Game.name).where(Game.id == attachment.game_id)
        result = await session.execute(stmt)
        game_name = result.scalar_one_or_none()

    # Resolve resource name
    resource_name = None
    if attachment.resource_id:
        stmt = select(Resource.name).where(Resource.id == attachment.resource_id)
        result = await session.execute(stmt)
        resource_name = result.scalar_one_or_none()

    # Extract section and surrounding text from resource content
    section = None
    surrounding_text = None
    if resource_content and attachment.id:
        section, surrounding_text = extract_image_context(
            image_id=attachment.id,
            markdown=resource_content,
            use_attachment_url=True,
        )

    return ImageAnalysisContext(
        page_number=attachment.page_number or 1,
        game_name=game_name,
        resource_name=resource_name,
        section=section,
        surrounding_text=surrounding_text,
    )


def update_attachment_from_analysis(
    attachment: Attachment,
    analysis: ImageAnalysisResult,
) -> None:
    """Update attachment fields from analysis result.

    Handles proper enum conversion from vision types to model types:
    - ImageType -> DetectedType
    - ImageQuality -> QualityRating

    Args:
        attachment: The attachment to update
        analysis: The analysis result from vision model
    """
    attachment.description = analysis.description
    attachment.detected_type = DetectedType(analysis.image_type.value)
    attachment.is_good_quality = QualityRating(analysis.quality.value)
    attachment.is_relevant = analysis.relevant
    attachment.ocr_text = analysis.ocr_text


async def get_attachment_image_data(attachment: Attachment) -> bytes:
    """Load image data from storage for an attachment.

    Args:
        attachment: The attachment to load image data for

    Returns:
        Image bytes

    Raises:
        ValueError: If attachment has no blob_key or file not found
    """
    if not attachment.blob_key:
        raise ValueError(f"Attachment {attachment.id} has no blob_key")

    image_data = await storage.get_file(attachment.blob_key)
    if image_data is None:
        raise ValueError(f"Image file not found: {attachment.blob_key}")

    return image_data
