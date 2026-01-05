"""Workflow monitoring and management endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import select

from gamegame.api.deps import AdminUser, SessionDep
from gamegame.models import Resource, WorkflowRun
from gamegame.models.resource import ResourceStatus
from gamegame.models.workflow_run import MAX_WORKFLOW_RETRIES, WorkflowRunRead
from gamegame.tasks.queue import PIPELINE_TIMEOUT_SECONDS, enqueue, queue

router = APIRouter()


@router.get("", response_model=list[WorkflowRunRead])
async def list_workflows(
    session: SessionDep,
    _user: AdminUser,
    run_ids: Annotated[list[str] | None, Query(alias="runId")] = None,
    resource_ids: Annotated[list[str] | None, Query(alias="resourceId")] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """List workflow runs (admin only).

    Query parameters:
        runId: Filter by specific run IDs (can be multiple)
        resourceId: Filter by specific resource IDs (can be multiple)
        status: Filter by status
        limit: Maximum number of results (default 20, max 100)
        offset: Offset for pagination
    """
    stmt = select(WorkflowRun)

    # Apply filters
    if run_ids:
        stmt = stmt.where(WorkflowRun.run_id.in_(run_ids))  # type: ignore[attr-defined]

    if resource_ids:
        stmt = stmt.where(WorkflowRun.resource_id.in_(resource_ids))  # type: ignore[attr-defined]

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

    if workflow.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry workflow with status '{workflow.status}'. Only failed workflows can be retried.",
        )

    # Check retry limit
    retry_count = (workflow.extra_data or {}).get("retry_count", 0)
    if retry_count >= MAX_WORKFLOW_RETRIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum retry limit ({MAX_WORKFLOW_RETRIES}) reached for this workflow.",
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

        # Get the stage where it failed from the workflow's extra_data
        # This allows retry to resume from the failed stage instead of restarting
        start_stage = (workflow.extra_data or {}).get("last_stage")

        # Reset resource status but preserve processing_stage for resume
        resource.status = ResourceStatus.QUEUED
        resource.error_message = None
        # Don't reset processing_stage or processing_metadata - they're needed for resume

        await session.commit()

        # Enqueue new processing task with incremented retry count and start_stage
        new_run_id = await enqueue(
            "process_resource",
            resource_id=workflow.resource_id,
            start_stage=start_stage,
            retry_count=retry_count + 1,
            timeout=PIPELINE_TIMEOUT_SECONDS,
        )

        return RetryResponse(
            success=True,
            message=f"Workflow retried from {start_stage}" if start_stage else "Workflow retried",
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

    if workflow.status not in ("queued", "running"):
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
    workflow.status = "cancelled"
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
