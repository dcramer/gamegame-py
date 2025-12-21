"""Maintenance background tasks for cleanup operations."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import delete, select

from gamegame.database import get_session_context
from gamegame.models import Attachment, Resource
from gamegame.models.workflow_run import WorkflowRun, WorkflowStatus
from gamegame.services.storage import storage
from gamegame.services.workflow_tracking import (
    complete_workflow_run,
    fail_workflow_run,
    get_or_create_workflow_run,
    start_workflow_run,
)

logger = logging.getLogger(__name__)

# Timeout for maintenance tasks (10 minutes)
MAINTENANCE_TIMEOUT_SECONDS = 10 * 60

# Default retention for workflow runs (30 days)
WORKFLOW_RUN_RETENTION_DAYS = 30


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
            await fail_workflow_run(session, run_id, error, "CLEANUP_ERROR")
            await session.commit()
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
                .where(WorkflowRun.created_at < cutoff_date)
                .where(
                    WorkflowRun.status.in_(
                        [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]
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
                    .where(WorkflowRun.created_at < cutoff_date)
                    .where(
                        WorkflowRun.status.in_(
                            [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]
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
            await fail_workflow_run(session, run_id, error, "PRUNE_ERROR")
            await session.commit()
            return {"success": False, "error": error}


# Set SAQ job timeouts
cleanup_orphaned_blobs.timeout = MAINTENANCE_TIMEOUT_SECONDS
prune_workflow_runs.timeout = MAINTENANCE_TIMEOUT_SECONDS
