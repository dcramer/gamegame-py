"""Maintenance background tasks for cleanup operations."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import delete, select

from gamegame.database import get_session_context
from gamegame.models import Attachment, Resource
from gamegame.models.bgg_game import BGGGame
from gamegame.models.workflow_run import WorkflowRun
from gamegame.services.storage import storage
from gamegame.services.workflow_tracking import (
    complete_workflow_run,
    fail_workflow_run,
    get_or_create_workflow_run,
    get_stalled_workflows,
    start_workflow_run,
)
from gamegame.tasks.queue import enqueue

logger = logging.getLogger(__name__)

# Timeout for maintenance tasks (10 minutes)
MAINTENANCE_TIMEOUT_SECONDS = 10 * 60

# Default retention for workflow runs (30 days)
WORKFLOW_RUN_RETENTION_DAYS = 30

# Default retention for BGG cache (30 days)
BGG_CACHE_RETENTION_DAYS = 30


async def cleanup_orphaned_blobs(
    ctx: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Find and delete blobs that are not referenced in the database.

    Args:
        ctx: SAQ context
        dry_run: If True, only report what would be deleted

    Returns:
        Dict with cleanup results
    """
    job = ctx.get("job")
    run_id = job.key if job else f"local-cleanup-{datetime.now(UTC).isoformat()}"

    async with get_session_context() as session:
        # Create workflow run record
        await get_or_create_workflow_run(
            session,
            run_id=run_id,
            workflow_name="cleanup_orphaned_blobs",
            input_data={"dry_run": dry_run},
        )
        await start_workflow_run(session, run_id)
        await session.commit()

        try:
            # Step 1: Collect all blob references from database
            db_blob_keys: set[str] = set()

            # Get resource URLs and extract keys
            resource_stmt = select(Resource.url)
            resource_result = await session.execute(resource_stmt)
            for (url,) in resource_result:
                if url and url.startswith("/uploads/"):
                    key = url.removeprefix("/uploads/")
                    db_blob_keys.add(key)

            # Get attachment blob keys
            attachment_stmt = select(Attachment.blob_key)
            attachment_result = await session.execute(attachment_stmt)
            for (blob_key,) in attachment_result:
                if blob_key:
                    db_blob_keys.add(blob_key)

            logger.info(f"Found {len(db_blob_keys)} blob references in database")

            # Step 2: List all blobs in storage
            all_blobs = await storage.list_files()
            logger.info(f"Found {len(all_blobs)} blobs in storage")

            # Step 3: Find orphaned blobs
            orphaned_blobs = [b for b in all_blobs if b not in db_blob_keys]
            logger.info(f"Found {len(orphaned_blobs)} orphaned blobs")

            # Step 4: Delete orphaned blobs (unless dry run)
            deleted_count = 0
            failed_deletions: list[str] = []

            if not dry_run:
                for blob_key in orphaned_blobs:
                    try:
                        success = await storage.delete_file(blob_key)
                        if success:
                            deleted_count += 1
                            logger.debug(f"Deleted orphaned blob: {blob_key}")
                        else:
                            failed_deletions.append(blob_key)
                    except Exception as e:
                        logger.error(f"Failed to delete blob {blob_key}: {e}")
                        failed_deletions.append(blob_key)

            output_data = {
                "dry_run": dry_run,
                "db_references": len(db_blob_keys),
                "storage_blobs": len(all_blobs),
                "orphaned_count": len(orphaned_blobs),
                "deleted_count": deleted_count,
                "failed_deletions": failed_deletions,
            }

            await complete_workflow_run(session, run_id, output_data)
            await session.commit()

            logger.info(
                f"Blob cleanup complete: {len(orphaned_blobs)} orphaned, "
                f"{deleted_count} deleted, {len(failed_deletions)} failed"
            )

            return {
                "success": len(failed_deletions) == 0,
                **output_data,
            }

        except Exception as e:
            error = f"Blob cleanup failed: {e}"
            logger.exception(error)
            await session.rollback()
            async with session.begin():
                await fail_workflow_run(session, run_id, error, "CLEANUP_ERROR")
            return {"success": False, "error": error}


async def prune_workflow_runs(
    ctx: dict[str, Any],
    retention_days: int = WORKFLOW_RUN_RETENTION_DAYS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete old completed/failed workflow runs.

    Args:
        ctx: SAQ context
        retention_days: Keep runs newer than this many days
        dry_run: If True, only report what would be deleted

    Returns:
        Dict with pruning results
    """
    job = ctx.get("job")
    run_id = job.key if job else f"local-prune-{datetime.now(UTC).isoformat()}"

    async with get_session_context() as session:
        # Create workflow run record
        await get_or_create_workflow_run(
            session,
            run_id=run_id,
            workflow_name="prune_workflow_runs",
            input_data={"retention_days": retention_days, "dry_run": dry_run},
        )
        await start_workflow_run(session, run_id)
        await session.commit()

        try:
            cutoff_date = datetime.now(UTC) - timedelta(days=retention_days)

            # Count runs that would be deleted
            count_stmt = (
                select(WorkflowRun)
                .where(WorkflowRun.created_at < cutoff_date)  # type: ignore[arg-type]
                .where(
                    WorkflowRun.status.in_(  # type: ignore[attr-defined]
                        ["completed", "failed", "cancelled"]
                    )
                )
            )
            count_result = await session.execute(count_stmt)
            runs_to_delete = list(count_result.scalars())
            delete_count = len(runs_to_delete)

            logger.info(f"Found {delete_count} workflow runs older than {retention_days} days")

            # Delete if not dry run
            if not dry_run and delete_count > 0:
                delete_stmt = (
                    delete(WorkflowRun)
                    .where(WorkflowRun.created_at < cutoff_date)  # type: ignore[arg-type]
                    .where(
                        WorkflowRun.status.in_(  # type: ignore[attr-defined]
                            ["completed", "failed", "cancelled"]
                        )
                    )
                )
                await session.execute(delete_stmt)

            output_data = {
                "dry_run": dry_run,
                "retention_days": retention_days,
                "cutoff_date": cutoff_date.isoformat(),
                "runs_deleted": delete_count if not dry_run else 0,
                "runs_would_delete": delete_count,
            }

            await complete_workflow_run(session, run_id, output_data)
            await session.commit()

            logger.info(
                f"Workflow run prune complete: {delete_count} runs "
                f"{'would be' if dry_run else ''} deleted"
            )

            return {"success": True, **output_data}

        except Exception as e:
            error = f"Workflow run prune failed: {e}"
            logger.exception(error)
            await session.rollback()
            async with session.begin():
                await fail_workflow_run(session, run_id, error, "PRUNE_ERROR")
            return {"success": False, "error": error}


# Default stall threshold (45 minutes - slightly longer than pipeline timeout)
STALL_THRESHOLD_SECONDS = 45 * 60


async def recover_stalled_workflows(
    ctx: dict[str, Any],
    stall_threshold_seconds: int = STALL_THRESHOLD_SECONDS,
    dry_run: bool = False,
    auto_resume: bool = True,
) -> dict[str, Any]:
    """Find and recover workflows that appear to be stalled.

    A stalled workflow is one that's been in "running" status for longer
    than the threshold. This typically happens when:
    - The worker crashed or was killed
    - The task hit an unhandled exception that didn't properly fail the workflow
    - The Redis connection was lost during processing

    When auto_resume is enabled (default), stalled pipeline jobs are re-enqueued
    to continue from their last checkpoint. Otherwise, they are marked as failed.

    Args:
        ctx: SAQ context
        stall_threshold_seconds: How long before a running job is considered stalled
        dry_run: If True, only report what would be recovered
        auto_resume: If True, re-enqueue stalled jobs instead of failing them

    Returns:
        Dict with recovery results
    """
    job = ctx.get("job")
    run_id = job.key if job else f"local-recover-{datetime.now(UTC).isoformat()}"

    async with get_session_context() as session:
        # Create workflow run record for this maintenance task
        await get_or_create_workflow_run(
            session,
            run_id=run_id,
            workflow_name="recover_stalled_workflows",
            input_data={
                "stall_threshold_seconds": stall_threshold_seconds,
                "dry_run": dry_run,
            },
        )
        await start_workflow_run(session, run_id)
        await session.commit()

        try:
            # Find stalled workflows
            stalled = await get_stalled_workflows(
                session,
                stall_threshold_seconds=stall_threshold_seconds,
            )

            logger.info(f"Found {len(stalled)} stalled workflows")

            recovered_count = 0
            resumed_count = 0
            failed_recoveries: list[dict[str, str]] = []

            for workflow in stalled:
                try:
                    # Calculate how long since last activity (heartbeat)
                    stall_duration = datetime.now(UTC) - workflow.updated_at  # type: ignore[operator]
                    stall_minutes = int(stall_duration.total_seconds() / 60)
                    total_runtime = datetime.now(UTC) - workflow.started_at if workflow.started_at else stall_duration  # type: ignore[operator]
                    total_minutes = int(total_runtime.total_seconds() / 60)

                    # Check if this is a resumable pipeline job
                    can_resume = (
                        auto_resume
                        and workflow.workflow_name == "process_resource"
                        and workflow.resource_id
                    )

                    if can_resume and not dry_run:
                        # Get the resource to check its state
                        stmt = select(Resource).where(Resource.id == workflow.resource_id)
                        result = await session.execute(stmt)
                        resource = result.scalar_one_or_none()

                        if resource and resource.processing_stage:
                            # Re-enqueue to continue from last checkpoint
                            # Use a new key since the old job is stalled
                            new_key = f"{workflow.run_id}-resume-{datetime.now(UTC).timestamp()}"
                            await enqueue(
                                "process_resource",
                                key=new_key,
                                resource_id=resource.id,
                                start_stage=resource.processing_stage.value,
                                retry_count=(workflow.extra_data or {}).get("retry_count", 0) + 1,
                            )

                            # Update the resource to point to the new workflow run
                            # This ensures stall detection tracks the new job
                            resource.current_run_id = new_key

                            # Update the old workflow run to indicate it was resumed
                            workflow.status = "cancelled"
                            workflow.completed_at = datetime.now(UTC)
                            workflow.error = (
                                f"Workflow stalled after {stall_minutes} minutes without activity. "
                                "Automatically resumed with new job."
                            )
                            workflow.error_code = "RESUMED"
                            workflow.extra_data = {
                                **(workflow.extra_data or {}),
                                "resumed_at": datetime.now(UTC).isoformat(),
                                "resumed_with_key": new_key,
                                "stall_duration_seconds": stall_duration.total_seconds(),
                            }

                            resumed_count += 1
                            logger.info(
                                f"Resumed stalled workflow: {workflow.run_id} -> {new_key} "
                                f"(resource={resource.id}, stage={resource.processing_stage.value})"
                            )
                            continue

                    # Fall back to marking as failed
                    if not dry_run:
                        workflow.status = "failed"
                        workflow.completed_at = datetime.now(UTC)
                        workflow.error = (
                            f"Workflow stalled - no activity for {stall_minutes} minutes "
                            f"(total runtime: {total_minutes} minutes). "
                            "Marked as failed by automatic recovery."
                        )
                        workflow.error_code = "STALLED"

                        workflow.extra_data = {
                            **(workflow.extra_data or {}),
                            "recovered_at": datetime.now(UTC).isoformat(),
                            "stall_duration_seconds": stall_duration.total_seconds(),
                            "total_runtime_seconds": total_runtime.total_seconds(),
                        }

                        # Reset associated resource to failed
                        if workflow.resource_id:
                            stmt = select(Resource).where(Resource.id == workflow.resource_id)
                            result = await session.execute(stmt)
                            resource = result.scalar_one_or_none()
                            if resource and resource.status == "processing":
                                resource.status = "failed"
                                resource.error_message = (
                                    f"Processing stalled - no activity for {stall_minutes} minutes"
                                )
                                logger.info(
                                    f"Reset resource {resource.id} to failed status"
                                )

                    recovered_count += 1
                    logger.info(
                        f"{'Would mark as failed' if dry_run else 'Marked as failed'} stalled workflow: "
                        f"{workflow.run_id} ({workflow.workflow_name})"
                    )

                except Exception as e:
                    logger.error(f"Failed to recover workflow {workflow.run_id}: {e}")
                    failed_recoveries.append({
                        "run_id": workflow.run_id,
                        "error": str(e),
                    })

            output_data = {
                "dry_run": dry_run,
                "auto_resume": auto_resume,
                "stall_threshold_seconds": stall_threshold_seconds,
                "stalled_count": len(stalled),
                "recovered_count": recovered_count,
                "resumed_count": resumed_count,
                "failed_recoveries": failed_recoveries,
            }

            await complete_workflow_run(session, run_id, output_data)
            await session.commit()

            logger.info(
                f"Stalled workflow recovery complete: {len(stalled)} stalled, "
                f"{resumed_count} resumed, {recovered_count} marked failed, "
                f"{len(failed_recoveries)} errors"
            )

            return {"success": len(failed_recoveries) == 0, **output_data}

        except Exception as e:
            error = f"Stalled workflow recovery failed: {e}"
            logger.exception(error)
            await session.rollback()
            async with session.begin():
                await fail_workflow_run(session, run_id, error, "RECOVERY_ERROR")
            return {"success": False, "error": error}


async def cleanup_bgg_cache(
    ctx: dict[str, Any],
    retention_days: int = BGG_CACHE_RETENTION_DAYS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete stale BGG game cache entries.

    BGG cache entries that haven't been refreshed in retention_days are
    considered stale and can be safely deleted. Games that are actively
    used will be re-fetched from BGG as needed.

    Args:
        ctx: SAQ context
        retention_days: Keep entries newer than this many days
        dry_run: If True, only report what would be deleted

    Returns:
        Dict with cleanup results
    """
    job = ctx.get("job")
    run_id = job.key if job else f"local-bgg-cleanup-{datetime.now(UTC).isoformat()}"

    async with get_session_context() as session:
        # Create workflow run record
        await get_or_create_workflow_run(
            session,
            run_id=run_id,
            workflow_name="cleanup_bgg_cache",
            input_data={"retention_days": retention_days, "dry_run": dry_run},
        )
        await start_workflow_run(session, run_id)
        await session.commit()

        try:
            # Calculate cutoff timestamp in milliseconds
            cutoff_date = datetime.now(UTC) - timedelta(days=retention_days)
            cutoff_ms = int(cutoff_date.timestamp() * 1000)

            # Count entries that would be deleted
            count_stmt = select(BGGGame).where(BGGGame.cached_at < cutoff_ms)  # type: ignore[arg-type]
            count_result = await session.execute(count_stmt)
            stale_entries = list(count_result.scalars())
            delete_count = len(stale_entries)

            logger.info(f"Found {delete_count} BGG cache entries older than {retention_days} days")

            # Delete if not dry run
            if not dry_run and delete_count > 0:
                delete_stmt = delete(BGGGame).where(BGGGame.cached_at < cutoff_ms)  # type: ignore[arg-type]
                await session.execute(delete_stmt)

            output_data = {
                "dry_run": dry_run,
                "retention_days": retention_days,
                "cutoff_date": cutoff_date.isoformat(),
                "entries_deleted": delete_count if not dry_run else 0,
                "entries_would_delete": delete_count,
            }

            await complete_workflow_run(session, run_id, output_data)
            await session.commit()

            logger.info(
                f"BGG cache cleanup complete: {delete_count} entries "
                f"{'would be' if dry_run else ''} deleted"
            )

            return {"success": True, **output_data}

        except Exception as e:
            error = f"BGG cache cleanup failed: {e}"
            logger.exception(error)
            await session.rollback()
            async with session.begin():
                await fail_workflow_run(session, run_id, error, "BGG_CLEANUP_ERROR")
            return {"success": False, "error": error}


# Set SAQ job timeouts
cleanup_orphaned_blobs.timeout = MAINTENANCE_TIMEOUT_SECONDS  # type: ignore[attr-defined]
prune_workflow_runs.timeout = MAINTENANCE_TIMEOUT_SECONDS  # type: ignore[attr-defined]
recover_stalled_workflows.timeout = MAINTENANCE_TIMEOUT_SECONDS  # type: ignore[attr-defined]
cleanup_bgg_cache.timeout = MAINTENANCE_TIMEOUT_SECONDS  # type: ignore[attr-defined]
