"""Workflow monitoring and management endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import select

from gamegame.api.deps import AdminUser, SessionDep
from gamegame.models import Resource, WorkflowRun, WorkflowStatus
from gamegame.models.resource import ResourceStatus
from gamegame.models.workflow_run import WorkflowRunRead
from gamegame.tasks import queue
from gamegame.tasks.queue import PIPELINE_TIMEOUT_SECONDS

router = APIRouter()


@router.get("", response_model=list[WorkflowRunRead])
async def list_workflows(
    session: SessionDep,
    _user: AdminUser,
    run_ids: Annotated[list[str] | None, Query(alias="runId")] = None,
    status_filter: Annotated[WorkflowStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """List workflow runs (admin only).

    Query parameters:
        runId: Filter by specific run IDs (can be multiple)
        status: Filter by status
        limit: Maximum number of results (default 20, max 100)
        offset: Offset for pagination
    """
    stmt = select(WorkflowRun)

    # Apply filters
    if run_ids:
        stmt = stmt.where(WorkflowRun.run_id.in_(run_ids))  # type: ignore[attr-defined]

    if status_filter:
        stmt = stmt.where(WorkflowRun.status == status_filter)

    # Order by created_at descending (newest first)
    stmt = stmt.order_by(WorkflowRun.created_at.desc())  # type: ignore[attr-defined]
    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    workflows = result.scalars().all()

    return [WorkflowRunRead.model_validate(w) for w in workflows]


@router.get("/{run_id}", response_model=WorkflowRunRead)
async def get_workflow(
    run_id: str,
    session: SessionDep,
    _user: AdminUser,
):
    """Get a workflow run by ID (admin only)."""
    # Try by run_id first
    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow = result.scalar_one_or_none()

    # If not found by run_id, try by local id (nanoid string)
    if not workflow:
        stmt = select(WorkflowRun).where(WorkflowRun.id == run_id)
        result = await session.execute(stmt)
        workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run '{run_id}' not found",
        )

    return WorkflowRunRead.model_validate(workflow)


class RetryResponse(BaseModel):
    """Response for workflow retry."""

    success: bool
    message: str
    run_id: str | None = None


@router.post("/{run_id}/retry", response_model=RetryResponse)
async def retry_workflow(
    run_id: str,
    session: SessionDep,
    _user: AdminUser,
):
    """Retry a failed workflow (admin only).

    Only failed workflows can be retried. For process-resource workflows,
    this will trigger reprocessing of the associated resource.
    """
    # Find the workflow
    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run '{run_id}' not found",
        )

    if workflow.status != WorkflowStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry workflow with status '{workflow.status}'. Only failed workflows can be retried.",
        )

    # Handle retry based on workflow type
    if workflow.workflow_name == "process_resource" and workflow.resource_id:
        # Get the resource
        resource_stmt = select(Resource).where(Resource.id == workflow.resource_id)
        resource_result = await session.execute(resource_stmt)
        resource = resource_result.scalar_one_or_none()

        if not resource:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Associated resource not found",
            )

        # Reset resource status and trigger reprocessing
        resource.status = ResourceStatus.QUEUED
        resource.processing_stage = None
        resource.error_message = None

        await session.commit()

        # Enqueue new processing task
        job = await queue.enqueue(
            "process_resource",
            resource_id=workflow.resource_id,
            timeout=PIPELINE_TIMEOUT_SECONDS,
        )

        new_run_id = job.id if job else None

        return RetryResponse(
            success=True,
            message="Workflow retried",
            run_id=new_run_id,
        )

    # Unsupported workflow type
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Retry not implemented for workflow type '{workflow.workflow_name}'",
    )


@router.delete("/{run_id}", response_model=RetryResponse)
async def cancel_workflow(
    run_id: str,
    session: SessionDep,
    _user: AdminUser,
):
    """Cancel an active workflow (admin only).

    Only queued or running workflows can be cancelled.
    """
    # Find the workflow
    stmt = select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    result = await session.execute(stmt)
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run '{run_id}' not found",
        )

    if workflow.status not in (WorkflowStatus.QUEUED, WorkflowStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel workflow with status '{workflow.status}'",
        )

    # Try to abort the SAQ job
    try:
        job = await queue.job(run_id)
        if job:
            await job.abort("Cancelled by admin")
    except Exception:
        # Job may not exist in queue anymore
        pass

    # Update workflow status
    workflow.status = WorkflowStatus.CANCELLED
    workflow.extra_data = {**(workflow.extra_data or {}), "cancelled_by": "admin"}

    # If processing resource, reset to ready
    if workflow.workflow_name == "process_resource" and workflow.resource_id:
        resource_stmt = select(Resource).where(Resource.id == workflow.resource_id)
        resource_result = await session.execute(resource_stmt)
        resource = resource_result.scalar_one_or_none()

        if resource and resource.status == ResourceStatus.PROCESSING:
            resource.status = ResourceStatus.READY
            resource.processing_stage = None
            resource.current_run_id = None

    await session.commit()

    return RetryResponse(
        success=True,
        message="Workflow cancelled",
        run_id=run_id,
    )
