"""Background task worker using SAQ."""

import asyncio

from saq import Worker

from gamegame.logging import setup_logging
from gamegame.tasks.queue import get_queue_settings

setup_logging()


def main() -> None:
    """Run the SAQ worker."""
    settings = get_queue_settings()
    worker = Worker(
        queue=settings["queue"],
        functions=settings["functions"],
        concurrency=settings.get("concurrency", 10),
        cron_jobs=settings.get("cron_jobs"),
        startup=settings.get("startup"),
        shutdown=settings.get("shutdown"),
        before_process=settings.get("before_process"),
        after_process=settings.get("after_process"),
    )
    asyncio.run(worker.start())


if __name__ == "__main__":
    main()
