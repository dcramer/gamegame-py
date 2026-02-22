"""Resource CRUD endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlmodel import select

from gamegame.api.deps import AdminUser, CurrentUserOptional, SessionDep
from gamegame.api.utils import get_game_by_id_or_slug
from gamegame.models import Attachment, Fragment, Resource, Segment
from gamegame.models.resource import (
    ProcessingStage,
    ResourceRead,
    ResourceStatus,
    ResourceType,
    ResourceUpdate,
)
from gamegame.services.storage import storage
from gamegame.tasks import queue
from gamegame.tasks.queue import PIPELINE_TIMEOUT_SECONDS

MAX_PDF_SIZE = 100 * 1024 * 1024  # 100MB

logger = logging.getLogger(__name__)

router = APIRouter()


def resource_to_read(
    resource: Resource, segment_count: int = 0, fragment_count: int = 0
) -> ResourceRead:
    """Convert Resource model to ResourceRead schema with counts."""
    return ResourceRead(
        id=resource.id,
        game_id=resource.game_id,
        name=resource.name,
        original_filename=resource.original_filename,
        url=resource.url,
        description=resource.description,
        status=resource.status,
        resource_type=resource.resource_type,
        author=resource.author,
        attribution_url=resource.attribution_url,
        language=resource.language,
        edition=resource.edition,
        is_official=resource.is_official,
        processing_stage=resource.processing_stage,
        page_count=resource.page_count,
        image_count=resource.image_count,
        word_count=resource.word_count,
        segment_count=segment_count,
        fragment_count=fragment_count,
    )


async def get_resource_with_counts(
    session: SessionDep, resource_id: str
) -> tuple[Resource, int, int] | None:
    """Get a resource with segment and fragment counts in a single query.

    Returns (resource, segment_count, fragment_count) or None if not found.
    """
    segment_count_subq = (
        select(func.count(1))
        .where(Segment.resource_id == resource_id)
        .correlate(Resource)
        .scalar_subquery()
    )
    fragment_count_subq = (
        select(func.count(1))
        .where(Fragment.resource_id == resource_id)
        .correlate(Resource)
        .scalar_subquery()
    )

    stmt = select(
        Resource,
        segment_count_subq.label("segment_count"),
        fragment_count_subq.label("fragment_count"),
    ).where(Resource.id == resource_id)

    result = await session.execute(stmt)
    row = result.one_or_none()

    if not row:
        return None

    return row.Resource, row.segment_count or 0, row.fragment_count or 0


# Nested routes under /games/{game_id_or_slug}/resources
game_resources_router = APIRouter()


@game_resources_router.get("", response_model=list[ResourceRead])
async def list_game_resources(
    game_id_or_slug: str,
    session: SessionDep,
    _user: CurrentUserOptional,
):
    """List all resources for a game."""
    game = await get_game_by_id_or_slug(game_id_or_slug, session)

    # Get resources with segment and fragment counts using subqueries
    segment_count_subq = (
        select(
            Segment.resource_id,
            func.count(1).label("segment_count"),
        )
        .group_by(Segment.resource_id)
        .subquery()
    )
    fragment_count_subq = (
        select(
            Fragment.resource_id,
            func.count(1).label("fragment_count"),
        )
        .group_by(Fragment.resource_id)
        .subquery()
    )

    stmt = (
        select(
            Resource,
            func.coalesce(segment_count_subq.c.segment_count, 0).label("segment_count"),
            func.coalesce(fragment_count_subq.c.fragment_count, 0).label("fragment_count"),
        )
        .outerjoin(
            segment_count_subq,
            Resource.id == segment_count_subq.c.resource_id,  # type: ignore[arg-type]
        )
        .outerjoin(
            fragment_count_subq,
            Resource.id == fragment_count_subq.c.resource_id,  # type: ignore[arg-type]
        )
        .where(Resource.game_id == game.id)
        .order_by(Resource.name)
    )
    result = await session.execute(stmt)
    rows = result.all()

    return [
        resource_to_read(resource, segment_count, fragment_count)
        for resource, segment_count, fragment_count in rows
    ]


@game_resources_router.post("", response_model=ResourceRead, status_code=status.HTTP_201_CREATED)
async def upload_game_resource(
    game_id_or_slug: str,
    session: SessionDep,
    _user: AdminUser,
    file: Annotated[UploadFile, File()],
):
    """Upload a PDF resource for a game (admin only).

    This uploads the file, creates a Resource record, and queues
    it for processing.
    """
    game = await get_game_by_id_or_slug(game_id_or_slug, session)

    # Validate file type
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type: {file.content_type}. Only PDF files are allowed.",
        )

    # Read file content
    content = await file.read()

    # Validate size
    if len(content) > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {MAX_PDF_SIZE // (1024 * 1024)}MB",
        )

    # Upload to storage
    url, _blob_key = await storage.upload_file(
        data=content,
        prefix="pdfs",
        extension="pdf",
    )

    # Derive resource name from filename
    original_filename = file.filename or "document.pdf"
    name = original_filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()

    # Create resource record
    resource = Resource(
        game_id=game.id,
        name=name,
        original_filename=original_filename,
        url=url,
        resource_type=ResourceType.RULEBOOK,  # Default to rulebook
        status=ResourceStatus.QUEUED,
    )
    session.add(resource)
    await session.commit()
    await session.refresh(resource)

    # Enqueue processing task
    await queue.enqueue(
        "process_resource",
        resource_id=resource.id,
        timeout=PIPELINE_TIMEOUT_SECONDS,
    )

    logger.info(f"Created resource {resource.id} for game {game.id}, queued for processing")

    return resource_to_read(resource, 0)


# Standalone routes under /resources/{resource_id}
@router.get("/{resource_id}", response_model=ResourceRead)
async def get_resource(
    resource_id: str,
    session: SessionDep,
    _user: CurrentUserOptional,
):
    """Get a resource by ID."""
    result = await get_resource_with_counts(session, resource_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    resource, segment_count, fragment_count = result
    return resource_to_read(resource, segment_count, fragment_count)


@router.patch("/{resource_id}", response_model=ResourceRead)
async def update_resource(
    resource_id: str,
    resource_in: ResourceUpdate,
    session: SessionDep,
    _user: AdminUser,
):
    """Update a resource (admin only)."""
    stmt = select(Resource).where(Resource.id == resource_id)
    result = await session.execute(stmt)
    resource = result.scalar_one_or_none()

    if not resource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    update_data = resource_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(resource, field, value)

    await session.commit()

    # Refetch with counts in one query
    result = await get_resource_with_counts(session, resource_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    resource, segment_count, fragment_count = result
    return resource_to_read(resource, segment_count, fragment_count)


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
    resource_id: str,
    session: SessionDep,
    _user: AdminUser,
):
    """Delete a resource (admin only).

    This will cascade delete all fragments, embeddings, and attachments.
    Also cleans up blob storage files.
    """
    stmt = select(Resource).where(Resource.id == resource_id)
    result = await session.execute(stmt)
    resource = result.scalar_one_or_none()

    if not resource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    # Delete attachment blobs from storage
    attachment_stmt = select(Attachment.blob_key).where(
        Attachment.resource_id == resource_id
    )
    attachment_result = await session.execute(attachment_stmt)
    for (blob_key,) in attachment_result:
        if blob_key:
            try:
                await storage.delete_file(blob_key)
            except Exception as e:
                logger.warning(f"Failed to delete attachment blob {blob_key}: {e}")

    # Delete resource blob from storage (extract key from URL)
    if resource.url and resource.url.startswith("/uploads/"):
        resource_blob_key = resource.url.removeprefix("/uploads/")
        try:
            await storage.delete_file(resource_blob_key)
        except Exception as e:
            logger.warning(f"Failed to delete resource blob {resource_blob_key}: {e}")

    await session.delete(resource)
    await session.commit()


@router.post("/{resource_id}/reprocess", response_model=ResourceRead)
async def reprocess_resource(
    resource_id: str,
    session: SessionDep,
    _user: AdminUser,
    start_stage: Annotated[
        ProcessingStage | None,
        Query(description="Stage to start from"),
    ] = None,
):
    """Trigger reprocessing of a resource (admin only).

    By default, resumes from the stage where processing failed.
    Optionally specify a start_stage to start from a specific stage:
    - ingest, vision, cleanup, metadata, segment, embed, finalize

    Use start_stage=ingest to force a full reprocess from the beginning.
    """
    stmt = select(Resource).where(Resource.id == resource_id)
    result = await session.execute(stmt)
    resource = result.scalar_one_or_none()

    if not resource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    # Determine which stage to start from:
    # - If start_stage is explicitly provided, use that
    # - Otherwise, resume from the stage where it failed (if any)
    effective_start_stage = start_stage.value if start_stage else None
    if effective_start_stage is None and resource.processing_stage is not None:
        effective_start_stage = resource.processing_stage.value

    # Update status to queued for reprocessing
    resource.status = ResourceStatus.QUEUED
    resource.error_message = None
    # Don't clear processing_stage - it's used for resume and will be
    # updated by the pipeline as it progresses

    await session.commit()

    # Enqueue processing task
    await queue.enqueue(
        "process_resource",
        resource_id=resource_id,
        start_stage=effective_start_stage,
        timeout=PIPELINE_TIMEOUT_SECONDS,
    )

    # Refetch with counts in one query
    result = await get_resource_with_counts(session, resource_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    resource, segment_count, fragment_count = result
    return resource_to_read(resource, segment_count, fragment_count)
