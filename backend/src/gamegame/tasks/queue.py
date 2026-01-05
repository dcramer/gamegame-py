"""SAQ queue configuration for background tasks."""

import logging
from typing import Any

from saq import CronJob, Queue

from gamegame.config import settings

logger = logging.getLogger(__name__)

# Main task queue
queue = Queue.from_url(settings.redis_url)

# No hard job timeout - rely on heartbeat-based stall detection instead.
# Jobs checkpoint their progress and can resume after deploys or failures.
# Setting to None means no SAQ timeout; stall detection handles stuck jobs.
PIPELINE_TIMEOUT_SECONDS: int | None = None

# Track if we're shutting down gracefully
_shutting_down = False


def get_queue_settings() -> dict:
    """Get SAQ queue settings for the worker."""
    # Import here to avoid circular imports
    from gamegame.tasks.attachments import analyze_attachment
    from gamegame.tasks.maintenance import (
        cleanup_bgg_cache,
        cleanup_orphaned_blobs,
        prune_workflow_runs,
        recover_stalled_workflows,
    )
    from gamegame.tasks.pipeline import process_resource

    # Cron jobs for periodic maintenance
    cron_jobs = [
        # Check for stalled workflows every 10 minutes
        CronJob(recover_stalled_workflows, cron="*/10 * * * *"),
        # Prune old workflow runs daily at 3am
        CronJob(prune_workflow_runs, cron="0 3 * * *"),
        # Clean up orphaned blobs weekly on Sunday at 4am
        CronJob(cleanup_orphaned_blobs, cron="0 4 * * 0"),
        # Clean up stale BGG cache entries weekly on Sunday at 5am
        CronJob(cleanup_bgg_cache, cron="0 5 * * 0"),
    ]

    return {
        "queue": queue,
        "functions": [
            process_resource,
            analyze_attachment,
            cleanup_orphaned_blobs,
            cleanup_bgg_cache,
            prune_workflow_runs,
            recover_stalled_workflows,
        ],
        "cron_jobs": cron_jobs,
        "concurrency": 2,  # Number of concurrent tasks
        "startup": startup,
        "shutdown": shutdown,
        "before_process": before_process,
        "after_process": after_process,
    }


async def startup(ctx: dict) -> None:
    """Called when worker starts.

    Initialize connections and resources needed by tasks.
    """
    logger.info("Worker starting up...")

    # Initialize Sentry for error tracking in worker
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.1,
        )
        logger.info("Sentry initialized for worker")

    # Verify Redis connection
    try:
        redis = queue.redis  # type: ignore[attr-defined]
        if redis:
            await redis.ping()
            logger.info("Redis connection verified")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise

    # Store shared resources in context
    ctx["started_at"] = __import__("time").time()
    logger.info("Worker startup complete")


async def shutdown(ctx: dict) -> None:
    """Called when worker shuts down.

    Clean up connections and resources.
    """
    global _shutting_down  # noqa: PLW0603
    _shutting_down = True

    logger.info("Worker shutting down...")

    # Log uptime
    started_at = ctx.get("started_at")
    if started_at:
        uptime = __import__("time").time() - started_at
        logger.info(f"Worker uptime: {uptime:.1f} seconds")

    # Close database connections if any were opened
    try:
        from gamegame.database import close_db

        await close_db()
        logger.info("Database connections closed")
    except Exception as e:
        logger.warning(f"Error closing database: {e}")

    logger.info("Worker shutdown complete")


async def before_process(ctx: dict) -> None:
    """Called before each task is processed."""
    job = ctx.get("job")
    if job:
        logger.info(f"Starting task: {job.function} (id={job.id})")


async def after_process(ctx: dict) -> None:
    """Called after each task is processed."""
    job = ctx.get("job")
    if job:
        status = "completed" if job.status == "complete" else job.status
        logger.info(f"Finished task: {job.function} (id={job.id}, status={status})")


def is_shutting_down() -> bool:
    """Check if worker is in shutdown state.

    Tasks can check this to abort gracefully during shutdown.
    """
    return _shutting_down


async def enqueue(
    function_name: str,
    timeout: int | None = None,
    key: str | None = None,
    **kwargs: Any,
) -> str:
    """Enqueue a task for background processing.

    Args:
        function_name: Name of the registered task function
        timeout: Optional timeout in seconds
        key: Optional job key (for preserving run_id on resume)
        **kwargs: Arguments to pass to the task

    Returns:
        Job key (used as run_id for workflow tracking)
    """
    import uuid

    # Generate a unique key if not provided - SAQ needs an explicit key
    # for us to track the workflow run_id properly
    if key is None:
        key = str(uuid.uuid4())

    job = await queue.enqueue(function_name, timeout=timeout, key=key, **kwargs)
    if job is None:
        raise RuntimeError(f"Failed to enqueue task: {function_name}")
    logger.info(f"Enqueued task: {function_name} (id={job.id})")
    # Return the key, not job.id, since pipeline uses job.key for run_id
    return key
