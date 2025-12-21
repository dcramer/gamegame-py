"""Workflow run tracking service."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gamegame.models.workflow_run import WorkflowRun, WorkflowStatus

logger = logging.getLogger(__name__)


async def create_workflow_run(
    session: AsyncSession,
    run_id: str,
    workflow_name: str,
    *,
    resource_id: str | None = None,
    attachment_id: str | None = None,
    game_id: str | None = None,
    input_data: dict[str, Any] | None = None,
) -> WorkflowRun:
    """Create a new workflow run record.

    Args:
        session: Database session
        run_id: External job ID (from SAQ)
        workflow_name: Name of the workflow
        resource_id: Optional related resource ID
        attachment_id: Optional related attachment ID
        game_id: Optional related game ID
        input_data: Optional input parameters

    Returns:
        Created WorkflowRun
    """
    workflow_run = WorkflowRun(
        run_id=run_id,
        workflow_name=workflow_name,
        status=WorkflowStatus.QUEUED,
        resource_id=resource_id,
        attachment_id=attachment_id,
        game_id=game_id,
        input_data=input_data,
    )
    session.add(workflow_run)
    await session.flush()
    return workflow_run


async def start_workflow_run(
    session: AsyncSession,
    run_id: str,
) -> WorkflowRun | None:
    """Mark a workflow run as started.

    Args:
        session: Database session
        run_id: External job ID

    Returns:
        Updated WorkflowRun or None if not found
    """
    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow_run = result.scalar_one_or_none()

    if workflow_run:
        workflow_run.status = WorkflowStatus.RUNNING
        workflow_run.started_at = datetime.now(UTC)
        await session.flush()

    return workflow_run


async def update_workflow_progress(
    session: AsyncSession,
    run_id: str,
    stage: str,
    extra_data: dict[str, Any] | None = None,
) -> WorkflowRun | None:
    """Update workflow progress with current stage.

    Args:
        session: Database session
        run_id: External job ID
        stage: Current processing stage
        extra_data: Additional data to merge into extra_data

    Returns:
        Updated WorkflowRun or None if not found
    """
    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow_run = result.scalar_one_or_none()

    if workflow_run:
        current_extra = workflow_run.extra_data or {}
        current_extra["current_stage"] = stage
        if extra_data:
            current_extra.update(extra_data)
        workflow_run.extra_data = current_extra
        await session.flush()

    return workflow_run


async def complete_workflow_run(
    session: AsyncSession,
    run_id: str,
    output_data: dict[str, Any] | None = None,
) -> WorkflowRun | None:
    """Mark a workflow run as completed.

    Args:
        session: Database session
        run_id: External job ID
        output_data: Optional output data

    Returns:
        Updated WorkflowRun or None if not found
    """
    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow_run = result.scalar_one_or_none()

    if workflow_run:
        workflow_run.status = WorkflowStatus.COMPLETED
        workflow_run.completed_at = datetime.now(UTC)
        if output_data:
            workflow_run.output_data = output_data
        await session.flush()

    return workflow_run


async def fail_workflow_run(
    session: AsyncSession,
    run_id: str,
    error: str,
    error_code: str | None = None,
) -> WorkflowRun | None:
    """Mark a workflow run as failed.

    Args:
        session: Database session
        run_id: External job ID
        error: Error message
        error_code: Optional error code

    Returns:
        Updated WorkflowRun or None if not found
    """
    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow_run = result.scalar_one_or_none()

    if workflow_run:
        workflow_run.status = WorkflowStatus.FAILED
        workflow_run.completed_at = datetime.now(UTC)
        workflow_run.error = error
        workflow_run.error_code = error_code
        await session.flush()

    return workflow_run


async def get_or_create_workflow_run(
    session: AsyncSession,
    run_id: str,
    workflow_name: str,
    **kwargs: Any,
) -> WorkflowRun:
    """Get an existing workflow run or create a new one.

    This is useful for idempotent job handling.

    Args:
        session: Database session
        run_id: External job ID
        workflow_name: Name of the workflow
        **kwargs: Additional fields for creation

    Returns:
        Existing or new WorkflowRun
    """
    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow_run = result.scalar_one_or_none()

    if workflow_run:
        return workflow_run

    return await create_workflow_run(
        session,
        run_id=run_id,
        workflow_name=workflow_name,
        **kwargs,
    )
