"""CLI commands using Typer."""

import typer

from gamegame.cli.ask import app as ask_app
from gamegame.cli.attachments import app as attachments_app
from gamegame.cli.bgg import app as bgg_app
from gamegame.cli.db import app as db_app
from gamegame.cli.evals import app as evals_app
from gamegame.cli.games import app as games_app
from gamegame.cli.maintenance import app as maintenance_app
from gamegame.cli.resources import app as resources_app
from gamegame.cli.users import app as users_app
from gamegame.cli.workflows import app as workflows_app

app = typer.Typer(name="gamegame", help="GameGame CLI")

# Register sub-apps
app.add_typer(db_app, name="db")
app.add_typer(users_app, name="users")
app.add_typer(games_app, name="games")
app.add_typer(resources_app, name="resources")
app.add_typer(attachments_app, name="attachments")
app.add_typer(bgg_app, name="bgg")
app.add_typer(workflows_app, name="workflows")
app.add_typer(ask_app, name="ask")
app.add_typer(maintenance_app, name="maintenance")
app.add_typer(evals_app, name="evals")


@app.command()
def version():
    """Show version information."""
    from gamegame import __version__

    typer.echo(f"GameGame v{__version__}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
):
    """Run the development server."""
    import uvicorn

    uvicorn.run(
        "gamegame.main:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def worker(
    concurrency: int = typer.Option(2, help="Number of concurrent tasks"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Run the background task worker."""
    import asyncio
    import logging

    from saq import Worker

    from gamegame.tasks import get_queue_settings

    # Configure logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    settings = get_queue_settings()

    typer.echo(f"Starting worker with concurrency={concurrency}")

    async def run_worker():
        w = Worker(
            queue=settings["queue"],
            functions=settings["functions"],
            concurrency=concurrency,
            startup=settings.get("startup"),
            shutdown=settings.get("shutdown"),
        )
        await w.start()

    asyncio.run(run_worker())


if __name__ == "__main__":
    app()
