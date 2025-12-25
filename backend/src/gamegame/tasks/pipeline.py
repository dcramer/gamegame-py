"""Pipeline task for processing resources through all stages."""

import logging
import traceback
from typing import Any

from sqlmodel import select

from gamegame.database import async_session_factory
from gamegame.models import Attachment, Resource
from gamegame.models.attachment import AttachmentType
from gamegame.models.resource import ProcessingStage, ResourceStatus
from gamegame.services.pipeline.cleanup import cleanup_markdown
from gamegame.services.pipeline.embed import embed_content
from gamegame.services.pipeline.finalize import finalize_resource, mark_resource_failed
from gamegame.services.pipeline.ingest import ingest_document
from gamegame.services.pipeline.metadata import extract_metadata
from gamegame.services.pipeline.vision import (
    ImageAnalysisContext,
    analyze_images_batch,
)
from gamegame.services.storage import storage
from gamegame.services.workflow_tracking import (
    complete_workflow_run,
    fail_workflow_run,
    get_or_create_workflow_run,
    start_workflow_run,
    update_workflow_progress,
)
from gamegame.tasks.queue import PIPELINE_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# Stage order for pipeline
STAGE_ORDER = [
    ProcessingStage.INGEST,
    ProcessingStage.VISION,
    ProcessingStage.CLEANUP,
    ProcessingStage.METADATA,
    ProcessingStage.EMBED,
    ProcessingStage.FINALIZE,
]


async def process_resource(
    ctx: dict[str, Any],
    resource_id: str,
    start_stage: str | None = None,
) -> dict[str, Any]:
    """Process a resource through the pipeline stages.

    Args:
        ctx: SAQ context (contains job info)
        resource_id: Resource ID to process
        start_stage: Optional stage to start from (for retries)

    Returns:
        Dict with status and details
    """
    # Get job ID from SAQ context
    job = ctx.get("job")
    run_id = job.key if job else f"local-{resource_id}"

    logger.info(f"Starting pipeline for resource {resource_id} (run_id={run_id})")

    async with async_session_factory() as session:
        # Create or get workflow run record
        workflow_run = await get_or_create_workflow_run(
            session,
            run_id=run_id,
            workflow_name="process_resource",
            resource_id=resource_id,
            input_data={"start_stage": start_stage} if start_stage else None,
        )

        # Mark as started
        await start_workflow_run(session, run_id)
        await session.commit()

        try:
            # Lock the resource row to prevent duplicate processing
            stmt = (
                select(Resource)
                .where(Resource.id == resource_id)
                .with_for_update()
            )
            result = await session.execute(stmt)
            resource = result.scalar_one_or_none()

            if not resource:
                await fail_workflow_run(session, run_id, "Resource not found", "NOT_FOUND")
                await session.commit()
                return {"status": "error", "message": "Resource not found"}

            # Update workflow with game_id
            if resource.game_id and workflow_run:
                workflow_run.game_id = resource.game_id
                await session.flush()

            # Check if already completed
            if resource.status == ResourceStatus.COMPLETED and not start_stage:
                await complete_workflow_run(session, run_id, {"skipped": True})
                await session.commit()
                return {"status": "skipped", "message": "Already completed"}

            # Update status to processing and link to workflow run
            resource.status = ResourceStatus.PROCESSING
            resource.current_run_id = run_id
            await session.commit()

            # Determine starting stage
            if start_stage:
                try:
                    current_stage_idx = STAGE_ORDER.index(ProcessingStage(start_stage))
                except ValueError:
                    current_stage_idx = 0
            else:
                current_stage_idx = 0

            # Pipeline state (passed between stages)
            state: dict[str, Any] = {}

            # Load existing state if resuming
            if resource.processing_metadata:
                state = resource.processing_metadata

            # Run stages
            for stage in STAGE_ORDER[current_stage_idx:]:
                logger.info(f"Resource {resource_id}: Running stage {stage.value}")

                # Update current stage and workflow progress
                resource.processing_stage = stage
                await update_workflow_progress(session, run_id, stage.value)
                await session.commit()

                # Run the stage
                state = await _run_stage(session, resource, stage, state)

                # Save state checkpoint
                resource.processing_metadata = state
                await session.commit()

            # Finalize
            await finalize_resource(
                session,
                resource_id,
                page_count=state.get("page_count"),
                word_count=state.get("word_count"),
                image_count=state.get("image_count"),
            )

            # Mark workflow as completed
            await complete_workflow_run(
                session,
                run_id,
                output_data={
                    "page_count": state.get("page_count"),
                    "word_count": state.get("word_count"),
                    "image_count": state.get("image_count"),
                    "fragments_created": state.get("fragments_created"),
                },
            )
            await session.commit()

            logger.info(f"Resource {resource_id}: Pipeline completed successfully")
            return {"status": "completed", "resource_id": resource_id}

        except Exception as e:
            logger.exception(f"Resource {resource_id}: Pipeline failed")
            stack_trace = traceback.format_exc()

            # Capture context about where we failed
            current_stage = resource.processing_stage.value if resource and resource.processing_stage else None
            extra_context = {
                "last_stage": current_stage,
                "state_keys": list(state.keys()) if state else [],
            }

            await mark_resource_failed(session, resource_id, str(e))
            await fail_workflow_run(
                session,
                run_id,
                str(e),
                "PIPELINE_ERROR",
                stack_trace=stack_trace,
                extra_context=extra_context,
            )
            await session.commit()
            return {"status": "error", "message": str(e)}


async def _run_stage(
    session: Any,
    resource: Resource,
    stage: ProcessingStage,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Run a single pipeline stage.

    Args:
        session: Database session
        resource: Resource being processed
        stage: Stage to run
        state: Current pipeline state

    Returns:
        Updated state
    """
    if stage == ProcessingStage.INGEST:
        return await _stage_ingest(session, resource, state)
    elif stage == ProcessingStage.VISION:
        return await _stage_vision(session, resource, state)
    elif stage == ProcessingStage.CLEANUP:
        return await _stage_cleanup(session, resource, state)
    elif stage == ProcessingStage.METADATA:
        return await _stage_metadata(session, resource, state)
    elif stage == ProcessingStage.EMBED:
        return await _stage_embed(session, resource, state)
    elif stage == ProcessingStage.FINALIZE:
        # Finalize is handled separately
        return state
    else:
        raise ValueError(f"Unknown stage: {stage}")


async def _stage_ingest(
    _session: Any,
    resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """INGEST stage - Extract PDF content."""
    # Download document from storage
    url_path = resource.url.removeprefix("/uploads/")
    doc_bytes = await storage.get_file(url_path)
    if not doc_bytes:
        raise ValueError(f"Document not found: {resource.url}")

    # Determine MIME type
    mime_type = "application/pdf"
    if resource.original_filename:
        if resource.original_filename.lower().endswith(".png"):
            mime_type = "image/png"
        elif resource.original_filename.lower().endswith((".jpg", ".jpeg")):
            mime_type = "image/jpeg"

    # Extract content
    extraction = await ingest_document(doc_bytes, mime_type)

    # Store raw markdown in state
    state["raw_markdown"] = extraction.raw_markdown
    state["page_count"] = extraction.total_pages

    # Collect images for vision stage
    images: list[dict[str, Any]] = [
        {
            "id": img.id,
            "base64": img.base64_data,
            "page_number": img.page_number,
            "bbox": img.bbox,
        }
        for page in extraction.pages
        for img in page.images
    ]

    state["extracted_images"] = images
    state["image_count"] = len(images)

    return state


def _detect_image_mime_type(image_bytes: bytes) -> tuple[str, str]:
    """Detect image MIME type and extension from magic bytes.

    Returns (mime_type, extension) tuple.
    """
    if len(image_bytes) < 12:
        return "image/jpeg", "jpg"

    # PNG: \x89PNG\r\n\x1a\n
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"

    # JPEG: \xFF\xD8\xFF
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"

    # WebP: RIFF....WEBP
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp", "webp"

    # GIF magic bytes
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"

    return "image/jpeg", "jpg"


async def _stage_vision(
    session: Any,
    resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """VISION stage - Analyze extracted images."""
    import base64

    images = state.get("extracted_images", [])

    if not images:
        logger.info(f"Resource {resource.id}: No images to analyze")
        return state

    # Get game name for context
    game_name = None
    if resource.game_id:
        from gamegame.models import Game
        stmt = select(Game).where(Game.id == resource.game_id)
        result = await session.execute(stmt)
        game = result.scalar_one_or_none()
        if game:
            game_name = game.name

    # Prepare images for analysis
    image_inputs: list[tuple[bytes | str, ImageAnalysisContext]] = []
    for img in images:
        context = ImageAnalysisContext(
            page_number=img["page_number"],
            game_name=game_name,
            resource_name=resource.name,
        )
        image_inputs.append((img["base64"], context))

    # Analyze images
    results = await analyze_images_batch(image_inputs)

    # Create attachment records and store images
    for img, analysis in zip(images, results, strict=True):
        # Decode base64 image data
        base64_data = img["base64"]
        image_bytes = base64.b64decode(base64_data)

        # Detect MIME type
        mime_type, extension = _detect_image_mime_type(image_bytes)

        # Upload to storage
        prefix = f"resources/{resource.id}/attachments"
        url, blob_key = await storage.upload_file(
            data=image_bytes,
            prefix=prefix,
            extension=extension,
        )

        attachment = Attachment(
            game_id=resource.game_id,
            resource_id=resource.id,
            type=AttachmentType.IMAGE,
            mime_type=mime_type,
            blob_key=blob_key,
            url=url,
            page_number=img["page_number"],
            description=analysis.description,
            detected_type=analysis.image_type,
            is_good_quality=analysis.quality,
            ocr_text=analysis.ocr_text,
        )
        session.add(attachment)

    await session.flush()

    # Update state with analysis results
    state["images_analyzed"] = len(results)

    return state


async def _stage_cleanup(
    _session: Any,
    _resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """CLEANUP stage - Clean markdown content."""
    raw_markdown = state.get("raw_markdown", "")

    if not raw_markdown:
        state["cleaned_markdown"] = ""
        return state

    cleaned = await cleanup_markdown(raw_markdown)
    state["cleaned_markdown"] = cleaned

    return state


async def _stage_metadata(
    _session: Any,
    resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """METADATA stage - Extract metadata and generate LLM descriptions."""
    from gamegame.services.pipeline.metadata import generate_resource_metadata

    markdown = state.get("cleaned_markdown", state.get("raw_markdown", ""))

    metadata = extract_metadata(
        markdown=markdown,
        page_count=state.get("page_count", 0),
        image_count=state.get("image_count", 0),
    )

    state["word_count"] = metadata.word_count
    state["has_tables"] = metadata.has_tables

    # Generate LLM metadata (name and description)
    generated = await generate_resource_metadata(
        markdown=markdown,
        existing_name=resource.name,
        original_filename=resource.original_filename,
    )

    if generated:
        state["generated_name"] = generated.name
        state["generated_description"] = generated.description
        # Update resource with generated description (keep user's name)
        if not resource.name or resource.name == resource.original_filename:
            resource.name = generated.name
        # Always update description if we generated one
        resource.description = generated.description

    # Also store content for resource
    resource.content = markdown
    resource.page_count = metadata.page_count
    resource.word_count = metadata.word_count
    resource.image_count = metadata.image_count

    return state


async def _stage_embed(
    session: Any,
    resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """EMBED stage - Chunk and embed content."""
    markdown = state.get("cleaned_markdown", state.get("raw_markdown", ""))

    if not markdown:
        state["fragments_created"] = 0
        return state

    fragments_created = await embed_content(
        session=session,
        resource_id=resource.id,
        game_id=resource.game_id,
        markdown=markdown,
        generate_hyde=True,
    )

    state["fragments_created"] = fragments_created

    return state


# Set SAQ job timeout (15 minutes for large PDFs)
process_resource.timeout = PIPELINE_TIMEOUT_SECONDS  # type: ignore[attr-defined]
