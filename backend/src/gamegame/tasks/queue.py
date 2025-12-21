"""SAQ queue configuration for background tasks."""

from saq import Queue

from gamegame.config import settings

# Main task queue
queue = Queue.from_url(settings.redis_url)

# Job timeout: 30 minutes for PDF processing (can take a while for large docs)
PIPELINE_TIMEOUT_SECONDS = 30 * 60


def get_queue_settings() -> dict:
    """Get SAQ queue settings for the worker."""
    # Import here to avoid circular imports
    from gamegame.tasks.attachments import analyze_attachment
    from gamegame.tasks.maintenance import cleanup_orphaned_blobs, prune_workflow_runs
    from gamegame.tasks.pipeline import process_resource

    return {
        "queue": queue,
        "functions": [
            process_resource,
            analyze_attachment,
            cleanup_orphaned_blobs,
            prune_workflow_runs,
        ],
        "concurrency": 2,  # Number of concurrent tasks
        "startup": startup,
        "shutdown": shutdown,
    }


async def startup(_ctx: dict) -> None:
    """Called when worker starts."""
    pass


async def shutdown(_ctx: dict) -> None:
    """Called when worker shuts down."""
    pass
