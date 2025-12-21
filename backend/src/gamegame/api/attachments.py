"""Attachment CRUD endpoints."""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import select

from gamegame.api.deps import AdminUser, CurrentUserOptional, SessionDep
from gamegame.models import Attachment, Game, Resource
from gamegame.models.attachment import AttachmentRead, AttachmentUpdate, DetectedType

router = APIRouter()

# Nested routers for resources/{id}/attachments and games/{id}/attachments
resource_attachments_router = APIRouter()
game_attachments_router = APIRouter()


def attachment_to_read(attachment: Attachment) -> AttachmentRead:
    """Convert Attachment model to AttachmentRead schema."""
    return AttachmentRead(
        id=attachment.id,
        game_id=attachment.game_id,
        resource_id=attachment.resource_id,
        type=attachment.type,
        mime_type=attachment.mime_type,
        url=attachment.url,
        original_filename=attachment.original_filename,
        page_number=attachment.page_number,
        bbox=attachment.bbox,
        width=attachment.width,
        height=attachment.height,
        caption=attachment.caption,
        description=attachment.description,
        detected_type=attachment.detected_type,
        is_good_quality=attachment.is_good_quality,
        is_relevant=attachment.is_relevant,
        ocr_text=attachment.ocr_text,
    )


@router.get("/by-resource/{resource_id}", response_model=list[AttachmentRead])
async def list_attachments_by_resource(
    resource_id: str,
    session: SessionDep,
    _user: CurrentUserOptional,
    detected_type: DetectedType | None = Query(None, description="Filter by detected type"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List attachments for a resource."""
    # Verify resource exists
    resource_stmt = select(Resource).where(Resource.id == resource_id)
    resource_result = await session.execute(resource_stmt)
    if not resource_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    stmt = (
        select(Attachment)
        .where(Attachment.resource_id == resource_id)
        .order_by(Attachment.page_number, Attachment.id)  # type: ignore[arg-type]
    )

    if detected_type:
        stmt = stmt.where(Attachment.detected_type == detected_type)

    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    attachments = result.scalars().all()

    return [attachment_to_read(a) for a in attachments]


@router.get("/by-game/{game_id}", response_model=list[AttachmentRead])
async def list_attachments_by_game(
    game_id: str,
    session: SessionDep,
    _user: CurrentUserOptional,
    detected_type: DetectedType | None = Query(None, description="Filter by detected type"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List attachments for a game."""
    # Verify game exists
    game_stmt = select(Game).where(Game.id == game_id)
    game_result = await session.execute(game_stmt)
    if not game_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    stmt = (
        select(Attachment)
        .where(Attachment.game_id == game_id)
        .order_by(Attachment.resource_id, Attachment.page_number, Attachment.id)  # type: ignore[arg-type]
    )

    if detected_type:
        stmt = stmt.where(Attachment.detected_type == detected_type)

    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    attachments = result.scalars().all()

    return [attachment_to_read(a) for a in attachments]


@router.get("/{attachment_id}", response_model=AttachmentRead)
async def get_attachment(
    attachment_id: str,
    session: SessionDep,
    _user: CurrentUserOptional,
):
    """Get an attachment by ID."""
    stmt = select(Attachment).where(Attachment.id == attachment_id)
    result = await session.execute(stmt)
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    return attachment_to_read(attachment)


@router.patch("/{attachment_id}", response_model=AttachmentRead)
async def update_attachment(
    attachment_id: str,
    attachment_in: AttachmentUpdate,
    session: SessionDep,
    _user: AdminUser,
):
    """Update an attachment (admin only)."""
    stmt = select(Attachment).where(Attachment.id == attachment_id)
    result = await session.execute(stmt)
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    update_data = attachment_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(attachment, field, value)

    await session.commit()
    await session.refresh(attachment)

    return attachment_to_read(attachment)


class ReprocessResponse(BaseModel):
    """Response for attachment reprocess."""

    success: bool
    message: str
    attachment: AttachmentRead


@router.post("/{attachment_id}/reprocess", response_model=ReprocessResponse)
async def reprocess_attachment(
    attachment_id: str,
    session: SessionDep,
    _user: AdminUser,
):
    """Trigger re-analysis of an attachment with vision model (admin only)."""
    from gamegame.tasks import queue
    from gamegame.tasks.attachments import ATTACHMENT_TIMEOUT_SECONDS

    stmt = select(Attachment).where(Attachment.id == attachment_id)
    result = await session.execute(stmt)
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    # Clear existing analysis
    attachment.description = None
    attachment.detected_type = None
    attachment.is_good_quality = None
    attachment.is_relevant = None
    attachment.ocr_text = None

    await session.commit()
    await session.refresh(attachment)

    # Queue vision analysis task
    await queue.enqueue(
        "analyze_attachment",
        attachment_id=attachment_id,
        timeout=ATTACHMENT_TIMEOUT_SECONDS,
    )

    return ReprocessResponse(
        success=True,
        message="Attachment queued for reprocessing",
        attachment=attachment_to_read(attachment),
    )


# Nested router endpoints for /resources/{resource_id}/attachments
@resource_attachments_router.get("", response_model=list[AttachmentRead])
async def list_resource_attachments(
    resource_id: str,
    session: SessionDep,
    _user: CurrentUserOptional,
    detected_type: DetectedType | None = Query(None, description="Filter by detected type"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List attachments for a resource."""
    # Verify resource exists
    resource_stmt = select(Resource).where(Resource.id == resource_id)
    resource_result = await session.execute(resource_stmt)
    if not resource_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    stmt = (
        select(Attachment)
        .where(Attachment.resource_id == resource_id)
        .order_by(Attachment.page_number, Attachment.id)  # type: ignore[arg-type]
    )

    if detected_type:
        stmt = stmt.where(Attachment.detected_type == detected_type)

    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    attachments = result.scalars().all()

    return [attachment_to_read(a) for a in attachments]


# Nested router endpoints for /games/{game_id_or_slug}/attachments
@game_attachments_router.get("", response_model=list[AttachmentRead])
async def list_game_attachments(
    game_id_or_slug: str,
    session: SessionDep,
    _user: AdminUser,  # Requires admin auth to match TypeScript
    detected_type: DetectedType | None = Query(None, description="Filter by detected type"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List attachments for a game. Requires admin authentication."""
    # Get game by ID first, then try slug
    game_stmt = select(Game).where(Game.id == game_id_or_slug)
    game_result = await session.execute(game_stmt)
    game = game_result.scalar_one_or_none()

    if not game:
        game_stmt = select(Game).where(Game.slug == game_id_or_slug)
        game_result = await session.execute(game_stmt)
        game = game_result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    stmt = (
        select(Attachment)
        .where(Attachment.game_id == game.id)
        .order_by(Attachment.resource_id, Attachment.page_number, Attachment.id)  # type: ignore[arg-type]
    )

    if detected_type:
        stmt = stmt.where(Attachment.detected_type == detected_type)

    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    attachments = result.scalars().all()

    return [attachment_to_read(a) for a in attachments]
