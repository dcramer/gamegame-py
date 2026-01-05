"""Pipeline task for processing resources through all stages."""

import logging
from typing import Any

import httpx
from openai import APIConnectionError, APITimeoutError, RateLimitError
from sqlalchemy import delete
from sqlmodel import select

from gamegame.config import settings
from gamegame.database import async_session_factory
from gamegame.models import Attachment, Embedding, Fragment, Resource, Segment
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
from gamegame.services.resilience import CircuitOpenError
from gamegame.services.storage import storage
from gamegame.services.workflow_tracking import (
    complete_workflow_run,
    fail_workflow_run,
    get_or_create_workflow_run,
    start_workflow_run,
    update_workflow_item_progress,
    update_workflow_progress,
)
from gamegame.utils.image import (
    detect_mime_type_with_extension,
    get_image_dimensions,
    strip_data_url_prefix,
)


def _classify_error(e: Exception) -> tuple[str, str, str]:
    """Classify an exception into error code, user message, and suggestion.

    Returns:
        Tuple of (error_code, user_message, suggestion)
    """
    # OpenAI-specific errors
    if isinstance(e, APITimeoutError) or isinstance(e, httpx.ReadTimeout):
        return (
            "AI_TIMEOUT",
            "AI service timed out while processing",
            "The document may be complex. Try again - retries will resume from where it stopped.",
        )
    if isinstance(e, RateLimitError):
        return (
            "RATE_LIMIT",
            "AI service rate limit reached",
            "Wait a few minutes before retrying.",
        )
    if isinstance(e, APIConnectionError):
        return (
            "AI_CONNECTION",
            "Could not connect to AI service",
            "Check your internet connection and try again.",
        )
    if isinstance(e, CircuitOpenError):
        return (
            "AI_UNAVAILABLE",
            "AI service temporarily unavailable",
            "The service is experiencing issues. Wait a few minutes before retrying.",
        )

    # HTTP errors
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 401:
            return ("AUTH_ERROR", "Authentication failed", "Check API credentials.")
        if status == 403:
            return ("PERMISSION_ERROR", "Permission denied", "Check API permissions.")
        if status == 429:
            return ("RATE_LIMIT", "Rate limit exceeded", "Wait before retrying.")
        if status >= 500:
            return (
                "SERVICE_ERROR",
                f"External service error (HTTP {status})",
                "Try again later.",
            )
        return ("HTTP_ERROR", f"HTTP error {status}", "Check the request and try again.")

    if isinstance(e, httpx.ConnectError):
        return (
            "CONNECTION_ERROR",
            "Could not connect to external service",
            "Check your internet connection.",
        )

    # Configuration and validation errors
    if isinstance(e, ValueError):
        error_str = str(e)
        if "API_KEY" in error_str or "not configured" in error_str.lower():
            return (
                "CONFIG_ERROR",
                "Missing API configuration",
                "Check that all required API keys are set in environment variables.",
            )
        if "missing required state keys" in error_str.lower():
            return (
                "STATE_ERROR",
                "Pipeline state corrupted or incomplete",
                "Try reprocessing from the beginning.",
            )
        return ("VALIDATION_ERROR", str(e), "Check input data and try again.")

    # JSON parsing errors (from LLM responses)
    from json import JSONDecodeError

    if isinstance(e, JSONDecodeError):
        return (
            "PARSE_ERROR",
            "Failed to parse AI response",
            "The AI returned an invalid response. Try again.",
        )

    # Generic fallback
    return ("PIPELINE_ERROR", str(e), "Try again or contact support.")

logger = logging.getLogger(__name__)

# Stage order for pipeline
STAGE_ORDER = [
    ProcessingStage.INGEST,
    ProcessingStage.VISION,
    ProcessingStage.CLEANUP,
    ProcessingStage.METADATA,
    ProcessingStage.SEGMENT,
    ProcessingStage.EMBED,
    ProcessingStage.FINALIZE,
]

# Required state keys for each stage (validated before stage execution)
STAGE_REQUIRED_STATE: dict[ProcessingStage, list[str]] = {
    # INGEST creates initial state, no requirements
    ProcessingStage.INGEST: [],
    # VISION needs raw markdown and page boundaries from INGEST
    ProcessingStage.VISION: ["raw_markdown", "page_boundaries"],
    # CLEANUP needs raw markdown (may be modified by VISION)
    ProcessingStage.CLEANUP: ["raw_markdown"],
    # METADATA needs cleaned markdown from CLEANUP
    ProcessingStage.METADATA: ["cleaned_markdown"],
    # SEGMENT needs cleaned markdown
    ProcessingStage.SEGMENT: ["cleaned_markdown"],
    # EMBED needs cleaned markdown (and segment_id_mapping if segments exist)
    ProcessingStage.EMBED: ["cleaned_markdown"],
    # FINALIZE has no specific requirements
    ProcessingStage.FINALIZE: [],
}


def _validate_state_for_stage(state: dict[str, Any], stage: ProcessingStage) -> None:
    """Validate that state contains required keys for the given stage.

    Args:
        state: Current pipeline state dict
        stage: Stage about to be executed

    Raises:
        ValueError: If required keys are missing
    """
    required = STAGE_REQUIRED_STATE.get(stage, [])
    missing = [key for key in required if key not in state]
    if missing:
        raise ValueError(
            f"Cannot run stage {stage.value}: missing required state keys: {missing}. "
            f"Available keys: {list(state.keys())}"
        )


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

            # Capture original status before updating (for auto-resume detection)
            original_status = resource.status

            # Update status to processing and link to workflow run
            resource.status = ResourceStatus.PROCESSING
            resource.current_run_id = run_id
            await session.commit()

            # Determine starting stage and load state
            state: dict[str, Any] = {}
            # Track current stage for error reporting (avoid lazy loading after rollback)
            current_stage_name: str | None = None

            if start_stage:
                # Explicit start stage provided (manual reprocess or stall recovery)
                try:
                    current_stage_idx = STAGE_ORDER.index(ProcessingStage(start_stage))
                except ValueError:
                    current_stage_idx = 0
                # Load existing state if available
                if resource.processing_metadata:
                    state = resource.processing_metadata
                current_stage_name = start_stage
            elif (
                resource.processing_stage is not None
                and original_status == ResourceStatus.PROCESSING
            ):
                # Auto-resume: resource was mid-processing when server crashed/restarted
                # SAQ re-delivered the job, so we resume from the last checkpoint
                current_stage_idx = STAGE_ORDER.index(resource.processing_stage)
                state = resource.processing_metadata or {}
                current_stage_name = resource.processing_stage.value
                logger.info(
                    f"Resource {resource_id}: Auto-resuming from stage "
                    f"{current_stage_name}"
                )
            else:
                # Fresh start
                current_stage_idx = 0

            # Run stages
            for stage in STAGE_ORDER[current_stage_idx:]:
                # Track stage name for error reporting (before any DB operations)
                current_stage_name = stage.value
                logger.info(f"Resource {resource_id}: Running stage {current_stage_name}")

                # Update current stage and workflow progress
                resource.processing_stage = stage
                await update_workflow_progress(session, run_id, current_stage_name)
                await session.commit()

                # Validate state has required keys for this stage
                _validate_state_for_stage(state, stage)

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
            logger.exception(f"Resource {resource_id}: Pipeline failed at stage {current_stage_name}")

            # Classify the error for better user feedback
            error_code, user_message, suggestion = _classify_error(e)

            # Use cached current_stage_name instead of accessing ORM object
            # (after rollback, ORM objects are expired and lazy loading fails)
            extra_context = {
                "last_stage": current_stage_name,
                "state_keys": list(state.keys()) if state else [],
                "suggestion": suggestion,
            }

            # Rollback any aborted transaction, then record failure in a clean transaction
            await session.rollback()
            async with session.begin():
                await mark_resource_failed(session, resource_id, user_message)
                await fail_workflow_run(
                    session,
                    run_id,
                    user_message,
                    error_code,
                    extra_context=extra_context,
                )
            return {"status": "error", "message": user_message}


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
    elif stage == ProcessingStage.SEGMENT:
        return await _stage_segment(session, resource, state)
    elif stage == ProcessingStage.EMBED:
        return await _stage_embed(session, resource, state)
    elif stage == ProcessingStage.FINALIZE:
        # Finalize is handled separately
        return state
    else:
        raise ValueError(f"Unknown stage: {stage}")


async def _stage_ingest(
    session: Any,
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

    # Track page boundaries for segment extraction
    # Each entry is (start_char, end_char) position in combined markdown
    page_boundaries: list[tuple[int, int]] = []
    current_pos = 0
    for page in extraction.pages:
        page_len = len(page.markdown)
        page_boundaries.append((current_pos, current_pos + page_len))
        current_pos += page_len + 2  # +2 for \n\n between pages
    state["page_boundaries"] = page_boundaries
    logger.info(f"Resource {resource.id}: Tracked {len(page_boundaries)} page boundaries")

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


# Note: strip_data_url_prefix, get_image_dimensions, and detect_mime_type_with_extension
# are imported from gamegame.utils.image


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


# Vision batch size is configured via settings.pipeline_vision_batch_size


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
    batch_size = settings.pipeline_vision_batch_size
    for batch_start in range(resume_from, len(images), batch_size):
        batch_end = min(batch_start + batch_size, len(images))
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
            original_id = img["id"]

            # Skip bad quality images entirely - don't create attachments for them
            if analysis.quality.value != "good":
                skipped_count += 1
                continue

            # Decode base64 image data
            base64_data = strip_data_url_prefix(img["base64"])
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
                    attachment.width, attachment.height = get_image_dimensions(image_bytes)
                reused_count += 1
            else:
                # New image
                mime_type, extension = detect_mime_type_with_extension(image_bytes)
                width, height = get_image_dimensions(image_bytes)

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
            image_id_mapping[original_id] = attachment.id

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
        # Pattern handles nested brackets in alt text like ![Image with [note]](id)
        for original_id, attachment_id in image_id_mapping.items():
            # Match ![...](original_id) where ... can contain nested brackets
            # Uses a pattern that matches balanced brackets up to 2 levels deep
            pattern = rf"(!\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\]]*\])*\])*\])\({re.escape(original_id)}\)"
            replacement = rf"\1(attachment://{attachment_id})"
            updated_markdown = re.sub(pattern, replacement, updated_markdown)

        # Remove bad quality image references
        bad_quality_ids = all_original_ids - set(image_id_mapping.keys())
        for original_id in bad_quality_ids:
            # Same pattern for matching, then remove the entire image reference
            pattern = rf"!\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\]]*\])*\])*\]\({re.escape(original_id)}\)\n?"
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
    page_boundaries = state.get("page_boundaries")

    if not raw_markdown:
        state["cleaned_markdown"] = ""
        return state

    # Check for cursor to resume from
    cursor_data = state.get("stage_cursor", {})
    if cursor_data.get("stage") == "cleanup":
        resume_from = cursor_data.get("cursor", 0)
        previous_results = cursor_data.get("partial_results", [])
        if page_boundaries:
            logger.info(f"Resource {resource.id}: Resuming cleanup after page {resume_from}")
        else:
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
        page_boundaries=page_boundaries,
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
    session: Any,
    resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """METADATA stage - Extract metadata and generate name/description.

    This stage:
    1. Extracts basic metadata (word count, page count, etc.)
    2. Generates LLM-based name/description for the resource
    3. Stores content and stats on the resource
    """
    from gamegame.services.pipeline.metadata import generate_resource_metadata

    markdown = state.get("cleaned_markdown", state.get("raw_markdown", ""))

    if not markdown:
        return state

    # Extract basic metadata
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
        resource.name = generated.name
        resource.description = generated.description

    # Store content stats on resource
    resource.content = markdown
    resource.page_count = metadata.page_count
    resource.word_count = metadata.word_count
    resource.image_count = metadata.image_count

    return state


async def _cleanup_segments(session: Any, resource_id: str) -> int:
    """Delete all existing segments for a resource.

    Also clears segment references from fragments to avoid FK violations.
    Returns number of segments deleted.
    """
    from sqlalchemy import update

    # First, clear segment_id on fragments to avoid FK violation
    # (fragments reference segments via segment_id)
    clear_fragment_refs = (
        update(Fragment)
        .where(Fragment.resource_id == resource_id)  # type: ignore[arg-type]
        .values(segment_id=None)
    )
    await session.execute(clear_fragment_refs)

    # Now delete segments
    delete_segments = delete(Segment).where(Segment.resource_id == resource_id)  # type: ignore[arg-type]
    result = await session.execute(delete_segments)
    deleted_count = result.rowcount

    if deleted_count > 0:
        logger.info(f"Resource {resource_id}: Deleted {deleted_count} existing segments")

    return deleted_count


async def _stage_segment(
    session: Any,
    resource: Resource,
    state: dict[str, Any],
) -> dict[str, Any]:
    """SEGMENT stage - Extract semantic segments from the document.

    This stage:
    1. Extracts semantic segments from the document using LLM
    2. Stores segments in the database
    """
    from gamegame.services.pipeline.segments import extract_segments_llm

    markdown = state.get("cleaned_markdown", state.get("raw_markdown", ""))

    if not markdown:
        state["segments_created"] = 0
        return state

    # Clean up existing segments (in case of reprocessing)
    await _cleanup_segments(session, resource.id)

    # Create progress callback
    async def report_segment_progress(current: int, total: int) -> None:
        if resource.current_run_id:
            await update_workflow_item_progress(
                session, resource.current_run_id, current, total
            )

    # Extract segments using LLM
    page_boundaries = state.get("page_boundaries")
    segments = await extract_segments_llm(
        markdown,
        page_boundaries=page_boundaries,
        resource_name=resource.name,
        on_progress=report_segment_progress,
    )
    logger.info(f"Resource {resource.id}: LLM extracted {len(segments)} segments")

    # Store segments in DB
    segment_id_mapping: dict[int, str] = {}  # order_index -> segment.id
    for segment_data in segments:
        segment = Segment(
            resource_id=resource.id,
            game_id=resource.game_id,
            title=segment_data.title,
            hierarchy_path=segment_data.hierarchy_path,
            level=segment_data.level,
            order_index=segment_data.order_index,
            content=segment_data.content,
            page_start=segment_data.page_start,
            page_end=segment_data.page_end,
            word_count=segment_data.word_count,
            char_count=segment_data.char_count,
            parent_id=segment_data.parent_id,
        )
        session.add(segment)
        await session.flush()
        segment_data.id = segment.id
        segment_id_mapping[segment_data.order_index] = segment.id

    logger.info(f"Resource {resource.id}: Stored {len(segments)} segments in DB")

    state["segments_created"] = len(segments)
    state["segment_id_mapping"] = segment_id_mapping

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
    """EMBED stage - Chunk segments and generate embeddings.

    This stage reads segments from the database (created in SEGMENT stage)
    and chunks them into fragments with embeddings.

    Supports resumability via cursor in processing_metadata.
    """
    from gamegame.services.pipeline.segments import SegmentData

    markdown = state.get("cleaned_markdown", state.get("raw_markdown", ""))

    # Check for cursor to resume from
    cursor_data = state.get("stage_cursor", {})
    if cursor_data.get("stage") == "embed":
        resume_from = cursor_data.get("cursor", 0)
        logger.info(f"Resource {resource.id}: Resuming embed from chunk {resume_from}")
    else:
        resume_from = 0
        # Only clean up fragments if starting fresh (not resuming)
        # Segments are preserved - they were created in SEGMENT stage
        await _cleanup_fragments(session, resource.id)

    # Read segments from database (created in SEGMENT stage)
    segments_stmt = (
        select(Segment)
        .where(Segment.resource_id == resource.id)  # type: ignore[arg-type]
        .order_by(Segment.order_index)  # type: ignore[arg-type]
    )
    segments_result = await session.execute(segments_stmt)
    db_segments = segments_result.scalars().all()

    if not db_segments:
        logger.warning(f"Resource {resource.id}: No segments found in database")
        state["fragments_created"] = 0
        return state

    # Convert DB segments to SegmentData for embed_content
    segments = [
        SegmentData(
            id=seg.id,
            level=seg.level,
            title=seg.title,
            hierarchy_path=seg.hierarchy_path,
            content=seg.content,
            order_index=seg.order_index,
            page_start=seg.page_start,
            page_end=seg.page_end,
            word_count=seg.word_count,
            char_count=seg.char_count,
            parent_id=seg.parent_id,
        )
        for seg in db_segments
    ]

    logger.info(f"Resource {resource.id}: Read {len(segments)} segments from DB")

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
        segments=segments,
        generate_hyde=True,
        on_progress=report_embed_progress,
        on_checkpoint=checkpoint_embed,
        resume_from=resume_from,
    )

    # Clear cursor on completion
    state.pop("stage_cursor", None)
    state["fragments_created"] = fragments_created

    return state
