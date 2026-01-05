"""Attachment-related background tasks."""

import logging
from typing import Any

from sqlmodel import select

from gamegame.database import get_session_context
from gamegame.models import Attachment, Resource
from gamegame.services.attachment_analysis import (
    build_attachment_context,
    get_attachment_image_data,
    update_attachment_from_analysis,
)
from gamegame.services.pipeline.vision import analyze_single_image
from gamegame.services.workflow_tracking import (
    complete_workflow_run,
    fail_workflow_run,
    get_or_create_workflow_run,
    start_workflow_run,
)

logger = logging.getLogger(__name__)

# Timeout for attachment analysis (5 minutes should be plenty for one image)
ATTACHMENT_TIMEOUT_SECONDS = 5 * 60


async def analyze_attachment(
    ctx: dict[str, Any],
    attachment_id: str,
) -> dict[str, Any]:
    """Analyze a single attachment with vision model.

    Args:
        ctx: SAQ context
        attachment_id: ID of the attachment to analyze

    Returns:
        Dict with success status and analysis results
    """
    # Get job ID from SAQ context
    job = ctx.get("job")
    run_id = job.key if job else f"local-{attachment_id}"

    async with get_session_context() as session:
        # Create workflow run record
        await get_or_create_workflow_run(
            session,
            run_id=run_id,
            workflow_name="analyze_attachment",
            attachment_id=attachment_id,
        )
        await start_workflow_run(session, run_id)
        await session.commit()
        try:
            # Get the attachment
            stmt = select(Attachment).where(Attachment.id == attachment_id)
            result = await session.execute(stmt)
            attachment = result.scalar_one_or_none()

            if not attachment:
                error = f"Attachment {attachment_id} not found"
                await fail_workflow_run(session, run_id, error, "NOT_FOUND")
                await session.commit()
                return {"success": False, "error": error}

            # Get resource content for context extraction
            resource_content = None
            if attachment.resource_id:
                resource_stmt = select(Resource.content).where(Resource.id == attachment.resource_id)
                resource_result = await session.execute(resource_stmt)
                resource_content = resource_result.scalar_one_or_none()

            # Build context using shared function
            context = await build_attachment_context(
                session, attachment, resource_content=resource_content
            )

            # Read the image data from storage
            try:
                image_data = await get_attachment_image_data(attachment)
            except ValueError as e:
                error = str(e)
                logger.error(f"Failed to read attachment {attachment_id}: {e}")
                await fail_workflow_run(session, run_id, error, "READ_ERROR")
                await session.commit()
                return {"success": False, "error": error}

            # Analyze the image
            try:
                analysis = await analyze_single_image(image_data, context)
            except Exception as e:
                error = f"Vision analysis failed: {e}"
                logger.error(f"Failed to analyze attachment {attachment_id}: {e}")
                await fail_workflow_run(session, run_id, error, "VISION_ERROR")
                await session.commit()
                return {"success": False, "error": error}

            # Update the attachment with results using shared function
            update_attachment_from_analysis(attachment, analysis)

            # Mark workflow as completed
            output_data = {
                "description": analysis.description,
                "detected_type": analysis.image_type.value,
                "is_good_quality": analysis.quality.value == "good",
                "is_relevant": analysis.relevant,
            }
            await complete_workflow_run(session, run_id, output_data)
            await session.commit()

            logger.info(f"Analyzed attachment {attachment_id}: type={analysis.image_type.value}, quality={analysis.quality.value}")

            return {
                "success": True,
                "attachment_id": attachment_id,
                **output_data,
            }

        except Exception as e:
            # Catch any unexpected errors
            error = f"Unexpected error: {e}"
            logger.exception(f"Unexpected error analyzing attachment {attachment_id}")
            await session.rollback()
            async with session.begin():
                await fail_workflow_run(session, run_id, error, "UNEXPECTED_ERROR")
            return {"success": False, "error": error}


# Set SAQ job timeout
analyze_attachment.timeout = ATTACHMENT_TIMEOUT_SECONDS  # type: ignore[attr-defined]
