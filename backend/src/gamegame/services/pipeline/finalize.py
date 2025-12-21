"""FINALIZE stage - Mark resource as completed."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gamegame.models import Resource
from gamegame.models.resource import ResourceStatus


async def finalize_resource(
    session: AsyncSession,
    resource_id: str,
    page_count: int | None = None,
    word_count: int | None = None,
    image_count: int | None = None,
) -> Resource:
    """Mark a resource as completed after processing.

    Args:
        session: Database session
        resource_id: Resource ID to finalize
        page_count: Number of pages (optional update)
        word_count: Word count (optional update)
        image_count: Image count (optional update)

    Returns:
        Updated Resource
    """
    stmt = select(Resource).where(Resource.id == resource_id)
    result = await session.execute(stmt)
    resource = result.scalar_one()

    # Update status and timestamp
    resource.status = ResourceStatus.COMPLETED
    resource.processed_at = datetime.now(UTC).isoformat()
    resource.processing_stage = None
    resource.error_message = None

    # Update counts if provided
    if page_count is not None:
        resource.page_count = page_count
    if word_count is not None:
        resource.word_count = word_count
    if image_count is not None:
        resource.image_count = image_count

    await session.commit()
    await session.refresh(resource)

    return resource


async def mark_resource_failed(
    session: AsyncSession,
    resource_id: str,
    error_message: str,
) -> Resource:
    """Mark a resource as failed.

    Args:
        session: Database session
        resource_id: Resource ID
        error_message: Error description

    Returns:
        Updated Resource
    """
    stmt = select(Resource).where(Resource.id == resource_id)
    result = await session.execute(stmt)
    resource = result.scalar_one()

    resource.status = ResourceStatus.FAILED
    resource.error_message = error_message

    await session.commit()
    await session.refresh(resource)

    return resource
