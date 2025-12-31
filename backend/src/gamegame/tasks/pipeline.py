"""Pipeline task for processing resources through all stages."""

import logging
from typing import Any

from sqlalchemy import delete
from sqlmodel import select

from gamegame.database import async_session_factory
from gamegame.models import Attachment, Embedding, Fragment, Resource
from gamegame.models.attachment import AttachmentType, DetectedType, QualityRating
from gamegame.models.resource import ProcessingStage, ResourceStatus
from gamegame.services.pipeline.cleanup import cleanup_markdown
from gamegame.services.pipeline.embed import embed_content
from gamegame.services.pipeline.finalize import finalize_resource, mark_resource_failed
from gamegame.services.pipeline.ingest import ingest_document
from gamegame.services.pipeline.metadata import extract_metadata
from gamegame.services.pipeline.vision import (
    ImageAnalysisContext,
    analyze_images_batch,
    extract_image_context,
)
from gamegame.services.storage import storage
from gamegame.services.workflow_tracking import (
    complete_workflow_run,
    fail_workflow_run,
    get_or_create_workflow_run,
    start_workflow_run,
    update_workflow_item_progress,
    update_workflow_progress,
)

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
    retry_count: int = 0,
) -> dict[str, Any]:
    """Process a resource through the pipeline stages.

    Args:
        ctx: SAQ context (contains job info)
        resource_id: Resource ID to process
        start_stage: Optional stage to start from (for retries)
        retry_count: Number of retry attempts (for tracking)

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

            # Update workflow with game_id, resource name, and retry count
            if workflow_run:
                if resource.game_id:
                    workflow_run.game_id = resource.game_id
                # Store resource name and retry count in extra_data
                workflow_run.extra_data = {
                    **(workflow_run.extra_data or {}),
                    "resource_name": resource.name,
                    "retry_count": retry_count,
                }
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

            # Capture context about where we failed (stack traces go to Sentry)
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


def _strip_data_url_prefix(base64_data: str) -> str:
    """Strip data URL prefix from base64 string if present.

    Mistral OCR returns base64 data with format: data:image/jpeg;base64,/9j/4AAQ...
    This strips the prefix to get just the base64 content.

    Args:
        base64_data: Base64 string, possibly with data URL prefix

    Returns:
        Pure base64 string without prefix
    """
    if base64_data.startswith("data:"):
        # Format: data:image/jpeg;base64,/9j/4AAQ...
        return base64_data.split(",", 1)[1]
    return base64_data


def _get_image_dimensions(image_bytes: bytes) -> tuple[int | None, int | None]:
    """Extract image dimensions from bytes.

    Returns (width, height) tuple, or (None, None) if unable to determine.
    """
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return img.width, img.height
    except Exception:
        return None, None


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


async def _load_existing_attachments(session: Any, resource_id: str) -> dict[str, Attachment]:
    """Load existing attachments indexed by content_hash.

    Returns dict mapping content_hash -> Attachment for attachments that have a hash.
    """
    stmt = select(Attachment).where(Attachment.resource_id == resource_id)
    result = await session.execute(stmt)
    attachments = result.scalars().all()

    # Index by content_hash for quick lookup
    by_hash: dict[str, Attachment] = {}
    for attachment in attachments:
        if attachment.content_hash:
            by_hash[attachment.content_hash] = attachment

    return by_hash


async def _cleanup_attachments(
    session: Any,
    resource_id: str,
) -> int:
    """Delete all attachments for a resource.

    Used for full reprocessing when starting fresh.

    Args:
        session: Database session
        resource_id: Resource ID

    Returns:
        Number of attachments deleted
    """
    stmt = select(Attachment).where(Attachment.resource_id == resource_id)
    result = await session.execute(stmt)
    attachments = result.scalars().all()

    deleted_count = 0
    for attachment in attachments:
        # Delete blob file if exists
        if attachment.blob_key:
            try:
                await storage.delete_file(attachment.blob_key)
            except Exception as e:
                logger.warning(f"Failed to delete attachment file {attachment.blob_key}: {e}")

        await session.delete(attachment)
        deleted_count += 1

    # Flush to actually delete the records
    if deleted_count > 0:
        await session.flush()
        logger.info(f"Resource {resource_id}: Deleted {deleted_count} attachments")

    return deleted_count


async def _cleanup_orphaned_attachments(
    session: Any,
    resource_id: str,
    keep_hashes: set[str],
) -> int:
    """Delete attachments that are no longer in the extracted images.

    Args:
        session: Database session
        resource_id: Resource ID
        keep_hashes: Set of content hashes to keep

    Returns:
        Number of attachments deleted
    """
    stmt = select(Attachment).where(Attachment.resource_id == resource_id)
    result = await session.execute(stmt)
    attachments = result.scalars().all()

    deleted_count = 0
    for attachment in attachments:
        # Keep if hash matches or if it has no hash (legacy)
        if attachment.content_hash and attachment.content_hash in keep_hashes:
            continue

        # Delete orphaned attachment
        if attachment.blob_key:
            try:
                await storage.delete_file(attachment.blob_key)
            except Exception as e:
                logger.warning(f"Failed to delete attachment file {attachment.blob_key}: {e}")

        await session.delete(attachment)
        deleted_count += 1

    if deleted_count > 0:
        logger.info(f"Resource {resource_id}: Deleted {deleted_count} orphaned attachments")

    return deleted_count


# Batch size for vision stage checkpointing
VISION_BATCH_SIZE = 15


async def _stage_vision(
    session: Any,
    resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """VISION stage - Analyze extracted images.

    Supports resumability via cursor in processing_metadata.
    Processes images in batches, checkpointing after each batch.
    """
    import base64
    import hashlib
    import re

    # Load existing attachments indexed by content hash
    existing_by_hash = await _load_existing_attachments(session, resource.id)
    logger.info(f"Resource {resource.id}: Found {len(existing_by_hash)} existing attachments with hashes")

    images = state.get("extracted_images", [])

    if not images:
        logger.info(f"Resource {resource.id}: No images to analyze")
        return state

    # Check for cursor to resume from
    cursor_data = state.get("stage_cursor", {})
    if cursor_data.get("stage") == "vision":
        resume_from = cursor_data.get("cursor", 0)
        # Restore previously created image_id_mapping
        image_id_mapping: dict[str, str] = cursor_data.get("image_id_mapping", {})
        current_hashes: set[str] = set(cursor_data.get("current_hashes", []))
        logger.info(f"Resource {resource.id}: Resuming vision from image {resume_from}")
    else:
        resume_from = 0
        image_id_mapping = {}
        current_hashes = set()

    # Get game name for context
    game_name = None
    if resource.game_id:
        from gamegame.models import Game
        stmt = select(Game).where(Game.id == resource.game_id)
        result = await session.execute(stmt)
        game = result.scalar_one_or_none()
        if game:
            game_name = game.name

    # Get raw markdown for context extraction
    raw_markdown = state.get("raw_markdown", "")

    # Track statistics
    reused_count = 0
    created_count = 0
    skipped_count = 0

    # Process images in batches
    for batch_start in range(resume_from, len(images), VISION_BATCH_SIZE):
        batch_end = min(batch_start + VISION_BATCH_SIZE, len(images))
        batch_images = images[batch_start:batch_end]

        logger.info(
            f"Resource {resource.id}: Processing vision batch {batch_start}-{batch_end} "
            f"of {len(images)} images"
        )

        # Prepare batch for analysis
        batch_inputs: list[tuple[bytes | str, ImageAnalysisContext]] = []
        for img in batch_images:
            section, surrounding_text = extract_image_context(
                image_id=img["id"],
                markdown=raw_markdown,
            )

            context = ImageAnalysisContext(
                page_number=img["page_number"],
                game_name=game_name,
                resource_name=resource.name,
                section=section,
                surrounding_text=surrounding_text,
            )
            batch_inputs.append((img["base64"], context))

        # Create progress callback
        async def report_vision_progress(current: int, total: int) -> None:
            if resource.current_run_id:
                # Adjust progress to reflect overall position
                overall_current = batch_start + current
                await update_workflow_item_progress(
                    session, resource.current_run_id, overall_current, len(images)
                )

        # Analyze this batch
        batch_results = await analyze_images_batch(
            batch_inputs, on_progress=report_vision_progress
        )

        # Create attachments for this batch
        for img, analysis in zip(batch_images, batch_results, strict=True):
            # Decode base64 image data
            base64_data = _strip_data_url_prefix(img["base64"])
            image_bytes = base64.b64decode(base64_data)

            # Compute content hash
            content_hash = hashlib.sha256(image_bytes).hexdigest()
            current_hashes.add(content_hash)

            # Check if we already have this exact image
            existing = existing_by_hash.get(content_hash)

            if existing:
                # Reuse existing attachment
                attachment = existing
                attachment.page_number = img["page_number"]
                attachment.description = analysis.description
                attachment.detected_type = DetectedType(analysis.image_type.value)
                attachment.is_good_quality = QualityRating(analysis.quality.value)
                attachment.is_relevant = analysis.relevant
                attachment.ocr_text = analysis.ocr_text
                if not attachment.width or not attachment.height:
                    attachment.width, attachment.height = _get_image_dimensions(image_bytes)
                reused_count += 1
            else:
                # New image
                mime_type, extension = _detect_image_mime_type(image_bytes)
                width, height = _get_image_dimensions(image_bytes)

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
                    content_hash=content_hash,
                    page_number=img["page_number"],
                    width=width,
                    height=height,
                    description=analysis.description,
                    detected_type=DetectedType(analysis.image_type.value),
                    is_good_quality=QualityRating(analysis.quality.value),
                    is_relevant=analysis.relevant,
                    ocr_text=analysis.ocr_text,
                )
                session.add(attachment)
                await session.flush()
                created_count += 1

            # Track mapping for markdown update
            original_id = img["id"]
            if analysis.quality.value == "good":
                image_id_mapping[original_id] = attachment.id
            else:
                skipped_count += 1

        # Checkpoint after each batch
        state["stage_cursor"] = {
            "stage": "vision",
            "cursor": batch_end,
            "image_id_mapping": image_id_mapping,
            "current_hashes": list(current_hashes),
        }
        resource.processing_metadata = state
        await session.commit()

        logger.info(
            f"Resource {resource.id}: Completed vision batch, "
            f"{batch_end}/{len(images)} images processed"
        )

    # Clean up orphaned attachments
    await _cleanup_orphaned_attachments(session, resource.id, current_hashes)

    logger.info(
        f"Resource {resource.id}: {reused_count} reused, {created_count} created, "
        f"{skipped_count} low-quality filtered from markdown"
    )

    # Update markdown with attachment references
    raw_markdown = state.get("raw_markdown", "")
    if raw_markdown:
        updated_markdown = raw_markdown
        all_original_ids = {img["id"] for img in images}

        # Replace good quality image references
        for original_id, attachment_id in image_id_mapping.items():
            pattern = rf"(\!\[[^\]]*\])\({re.escape(original_id)}\)"
            replacement = rf"\1(attachment://{attachment_id})"
            updated_markdown = re.sub(pattern, replacement, updated_markdown)

        # Remove bad quality image references
        bad_quality_ids = all_original_ids - set(image_id_mapping.keys())
        for original_id in bad_quality_ids:
            pattern = rf"\!\[[^\]]*\]\({re.escape(original_id)}\)\n?"
            updated_markdown = re.sub(pattern, "", updated_markdown)

        state["raw_markdown"] = updated_markdown
        logger.info(
            f"Resource {resource.id}: Updated {len(image_id_mapping)} image references, "
            f"removed {len(bad_quality_ids)} bad quality references"
        )

    # Clear cursor and update state
    state.pop("stage_cursor", None)
    state["images_analyzed"] = len(images)

    return state


async def _stage_cleanup(
    session: Any,
    resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """CLEANUP stage - Clean markdown content.

    Supports resumability via cursor in processing_metadata.
    """
    raw_markdown = state.get("raw_markdown", "")

    if not raw_markdown:
        state["cleaned_markdown"] = ""
        return state

    # Check for cursor to resume from
    cursor_data = state.get("stage_cursor", {})
    if cursor_data.get("stage") == "cleanup":
        resume_from = cursor_data.get("cursor", 0)
        previous_results = cursor_data.get("partial_results", [])
        logger.info(f"Resource {resource.id}: Resuming cleanup from chunk {resume_from}")
    else:
        resume_from = 0
        previous_results = None

    # Create progress callback using resource's current run_id
    async def report_cleanup_progress(current: int, total: int) -> None:
        if resource.current_run_id:
            await update_workflow_item_progress(session, resource.current_run_id, current, total)

    # Create checkpoint callback to save cursor and partial results
    async def checkpoint_cleanup(cursor: int, results: list[str]) -> None:
        state["stage_cursor"] = {
            "stage": "cleanup",
            "cursor": cursor,
            "partial_results": results,
        }
        resource.processing_metadata = state
        await session.commit()

    cleaned = await cleanup_markdown(
        raw_markdown,
        on_progress=report_cleanup_progress,
        on_checkpoint=checkpoint_cleanup,
        resume_from=resume_from,
        previous_results=previous_results,
    )

    # Clear cursor on completion
    state.pop("stage_cursor", None)
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
        # Always use LLM-generated name (it's better than filename-derived names)
        # Users can override via PATCH if needed
        resource.name = generated.name
        resource.description = generated.description

    # Also store content for resource
    resource.content = markdown
    resource.page_count = metadata.page_count
    resource.word_count = metadata.word_count
    resource.image_count = metadata.image_count

    return state


async def _cleanup_fragments(session: Any, resource_id: str) -> int:
    """Delete all existing fragments and embeddings for a resource.

    Returns number of fragments deleted.
    """
    # Delete embeddings first (foreign key constraint)
    delete_embeddings = delete(Embedding).where(Embedding.resource_id == resource_id)  # type: ignore[arg-type]
    await session.execute(delete_embeddings)

    # Delete fragments
    delete_fragments = delete(Fragment).where(Fragment.resource_id == resource_id)  # type: ignore[arg-type]
    result = await session.execute(delete_fragments)
    deleted_count = result.rowcount

    if deleted_count > 0:
        logger.info(f"Resource {resource_id}: Deleted {deleted_count} existing fragments")

    return deleted_count


async def _stage_embed(
    session: Any,
    resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """EMBED stage - Chunk and embed content.

    Supports resumability via cursor in processing_metadata.
    """
    markdown = state.get("cleaned_markdown", state.get("raw_markdown", ""))

    if not markdown:
        state["fragments_created"] = 0
        return state

    # Check for cursor to resume from
    cursor_data = state.get("stage_cursor", {})
    if cursor_data.get("stage") == "embed":
        resume_from = cursor_data.get("cursor", 0)
        logger.info(f"Resource {resource.id}: Resuming embed from chunk {resume_from}")
    else:
        resume_from = 0
        # Only clean up fragments if starting fresh (not resuming)
        await _cleanup_fragments(session, resource.id)

    # Create progress callback using resource's current run_id
    async def report_embed_progress(current: int, total: int) -> None:
        if resource.current_run_id:
            await update_workflow_item_progress(session, resource.current_run_id, current, total)

    # Create checkpoint callback to save cursor
    async def checkpoint_embed(cursor: int) -> None:
        state["stage_cursor"] = {
            "stage": "embed",
            "cursor": cursor,
        }
        resource.processing_metadata = state
        await session.commit()

    fragments_created = await embed_content(
        session=session,
        resource_id=resource.id,
        game_id=resource.game_id,
        markdown=markdown,
        generate_hyde=True,
        on_progress=report_embed_progress,
        on_checkpoint=checkpoint_embed,
        resume_from=resume_from,
    )

    # Clear cursor on completion
    state.pop("stage_cursor", None)
    state["fragments_created"] = fragments_created

    return state
