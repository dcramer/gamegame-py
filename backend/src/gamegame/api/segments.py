"""Segment endpoints for viewing document sections."""

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import select

from gamegame.api.deps import CurrentUserOptional, SessionDep
from gamegame.models import Resource
from gamegame.models.segment import Segment, SegmentRead

router = APIRouter()


def segment_to_read(segment: Segment) -> SegmentRead:
    """Convert Segment model to SegmentRead schema."""
    return SegmentRead(
        id=segment.id,
        resource_id=segment.resource_id,
        game_id=segment.game_id,
        title=segment.title,
        hierarchy_path=segment.hierarchy_path,
        level=segment.level,
        order_index=segment.order_index,
        content=segment.content,
        page_start=segment.page_start,
        page_end=segment.page_end,
        word_count=segment.word_count,
        char_count=segment.char_count,
        parent_id=segment.parent_id,
    )


@router.get("/by-resource/{resource_id}", response_model=list[SegmentRead])
async def list_segments_by_resource(
    resource_id: str,
    session: SessionDep,
    _user: CurrentUserOptional,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List segments for a resource."""
    # Verify resource exists
    resource_stmt = select(Resource).where(Resource.id == resource_id)
    resource_result = await session.execute(resource_stmt)
    if not resource_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    stmt = (
        select(Segment)
        .where(Segment.resource_id == resource_id)
        .order_by(Segment.order_index)  # type: ignore[arg-type]
        .offset(offset)
        .limit(limit)
    )

    result = await session.execute(stmt)
    segments = result.scalars().all()

    return [segment_to_read(s) for s in segments]


@router.get("/{segment_id}", response_model=SegmentRead)
async def get_segment(
    segment_id: str,
    session: SessionDep,
    _user: CurrentUserOptional,
):
    """Get a segment by ID."""
    stmt = select(Segment).where(Segment.id == segment_id)
    result = await session.execute(stmt)
    segment = result.scalar_one_or_none()

    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found",
        )

    return segment_to_read(segment)
