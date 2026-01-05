"""Workflow run tracking service."""

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gamegame.models.workflow_run import WorkflowRun

logger = logging.getLogger(__name__)

# Module-level cache for last progress update time (per run_id)
_last_progress_update: dict[str, float] = {}
MIN_UPDATE_INTERVAL_SECONDS = 1.0


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
        status="queued",
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
        workflow_run.status = "running"
        workflow_run.started_at = datetime.now(UTC)
        # Explicitly update timestamp as heartbeat for stall detection
        workflow_run.updated_at = datetime.now(UTC)
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
        # Create a new dict to ensure SQLAlchemy detects the change
        # (in-place mutations of JSON columns may not be detected)
        new_extra = {**(workflow_run.extra_data or {}), "current_stage": stage}
        # Clear item progress when moving to new stage
        new_extra.pop("progress_current", None)
        new_extra.pop("progress_total", None)
        if extra_data:
            new_extra.update(extra_data)
        workflow_run.extra_data = new_extra
        # Explicitly update timestamp as heartbeat for stall detection
        workflow_run.updated_at = datetime.now(UTC)
        await session.flush()

        # Clear timing cache for batching
        clear_item_progress_cache(run_id)

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
        workflow_run.status = "completed"
        workflow_run.completed_at = datetime.now(UTC)
        if output_data:
            workflow_run.output_data = output_data
        await session.flush()

    # Clear progress cache to prevent memory leak
    clear_item_progress_cache(run_id)

    return workflow_run


async def fail_workflow_run(
    session: AsyncSession,
    run_id: str,
    error: str,
    error_code: str | None = None,
    *,
    extra_context: dict[str, Any] | None = None,
) -> WorkflowRun | None:
    """Mark a workflow run as failed.

    This effectively adds the job to a "dead letter queue" - failed jobs
    are persisted with full error context for later inspection and retry.

    Note: Stack traces are not stored as Sentry is used for error tracking.

    Args:
        session: Database session
        run_id: External job ID
        error: Error message
        error_code: Optional error code (e.g., "PIPELINE_ERROR", "API_ERROR")
        extra_context: Optional additional context (e.g., last successful stage)

    Returns:
        Updated WorkflowRun or None if not found
    """
    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow_run = result.scalar_one_or_none()

    if workflow_run:
        workflow_run.status = "failed"
        workflow_run.completed_at = datetime.now(UTC)
        workflow_run.error = error
        workflow_run.error_code = error_code

        # Store additional failure context in extra_data
        # Create a new dict to ensure SQLAlchemy detects the change
        if extra_context:
            new_extra = {**(workflow_run.extra_data or {}), "failure_context": extra_context}
            workflow_run.extra_data = new_extra

        await session.flush()
        logger.warning(
            f"Workflow {run_id} failed: {error_code or 'ERROR'} - {error}",
            extra={"run_id": run_id, "error_code": error_code},
        )

    # Clear progress cache to prevent memory leak
    clear_item_progress_cache(run_id)

    return workflow_run


async def get_failed_workflows(
    session: AsyncSession,
    limit: int = 50,
    workflow_name: str | None = None,
) -> list[WorkflowRun]:
    """Get failed workflow runs for inspection (dead letter queue).

    Args:
        session: Database session
        limit: Maximum number of results
        workflow_name: Optional filter by workflow name

    Returns:
        List of failed WorkflowRun records
    """
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.status == "failed")
        .order_by(WorkflowRun.completed_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )

    if workflow_name:
        stmt = stmt.where(WorkflowRun.workflow_name == workflow_name)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_stalled_workflows(
    session: AsyncSession,
    stall_threshold_seconds: int = 45 * 60,
    limit: int = 100,
) -> list[WorkflowRun]:
    """Get workflow runs that appear to be stalled.

    A workflow is considered stalled if it's been in "running" status
    and hasn't had any activity (progress updates) for longer than the threshold.

    This uses updated_at as a heartbeat - jobs that make progress will update
    this timestamp, preventing them from being marked as stalled.

    Args:
        session: Database session
        stall_threshold_seconds: How long without activity before considered stalled
        limit: Maximum number of results

    Returns:
        List of stalled WorkflowRun records
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=stall_threshold_seconds)

    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.status == "running")
        .where(WorkflowRun.updated_at < cutoff)  # type: ignore[arg-type]
        .order_by(WorkflowRun.updated_at.asc())  # type: ignore[attr-defined]
        .limit(limit)
    )

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_workflow_item_progress(
    session: AsyncSession,
    run_id: str,
    current: int,
    total: int,
    *,
    force: bool = False,
) -> WorkflowRun | None:
    """Update workflow with item-level progress within a stage.

    Batches updates to avoid excessive DB writes. Updates occur:
    - On first item (current == 1)
    - On last item (current == total)
    - At minimum interval (1 second)
    - When force=True

    Args:
        session: Database session
        run_id: External job ID
        current: Current item number (1-based)
        total: Total items to process
        force: Force update regardless of batching rules

    Returns:
        Updated WorkflowRun or None if skipped/not found
    """
    # Determine if we should update
    now = time.monotonic()
    last_update = _last_progress_update.get(run_id, 0)

    should_update = (
        force
        or current == 1  # First item
        or current == total  # Last item
        or (now - last_update) >= MIN_UPDATE_INTERVAL_SECONDS
    )

    if not should_update:
        return None

    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow_run = result.scalar_one_or_none()

    if workflow_run:
        new_extra = {
            **(workflow_run.extra_data or {}),
            "progress_current": current,
            "progress_total": total,
        }
        workflow_run.extra_data = new_extra
        # Explicitly update timestamp as heartbeat for stall detection
        workflow_run.updated_at = datetime.now(UTC)
        await session.flush()
        _last_progress_update[run_id] = now

    return workflow_run


def clear_item_progress_cache(run_id: str) -> None:
    """Clear cached progress timing for a run (call when stage changes)."""
    _last_progress_update.pop(run_id, None)


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
