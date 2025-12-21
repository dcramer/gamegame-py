"""Resource management CLI commands."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from sqlmodel import func, select

from gamegame.database import get_session_context
from gamegame.models import Fragment, Game, Resource
from gamegame.models.resource import ResourceStatus, ResourceType
from gamegame.services.storage import storage
from gamegame.tasks import queue
from gamegame.tasks.queue import PIPELINE_TIMEOUT_SECONDS

console = Console()
app = typer.Typer(help="Resource management commands")

STAGE_ORDER = ["ingest", "vision", "cleanup", "metadata", "embed", "finalize"]

RESOURCE_TYPE_CHOICES = [rt.value for rt in ResourceType]


def status_style(status: ResourceStatus) -> str:
    """Get Rich style for status."""
    return {
        ResourceStatus.READY: "dim",
        ResourceStatus.QUEUED: "yellow",
        ResourceStatus.PROCESSING: "cyan",
        ResourceStatus.COMPLETED: "green",
        ResourceStatus.FAILED: "red",
    }.get(status, "white")


@app.command("list")
def list_resources(
    game: Annotated[str | None, typer.Option("--game", "-g", help="Filter by game ID or slug")] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum resources to show"),
):
    """List resources with their status."""

    async def _list():
        async with get_session_context() as session:
            stmt = (
                select(Resource, Game.name.label("game_name"))
                .join(Game, Resource.game_id == Game.id)
                .order_by(Resource.created_at.desc())
                .limit(limit)
            )

            # Filter by game
            if game:
                game_stmt = select(Game).where((Game.id == game) | (Game.slug == game))
                result = await session.execute(game_stmt)
                game_obj = result.scalar_one_or_none()
                if not game_obj:
                    console.print(f"[red]Error:[/red] Game '{game}' not found")
                    raise typer.Exit(1)
                stmt = stmt.where(Resource.game_id == game_obj.id)

            # Filter by status
            if status:
                try:
                    status_enum = ResourceStatus(status.lower())
                    stmt = stmt.where(Resource.status == status_enum)
                except ValueError:
                    console.print(f"[red]Error:[/red] Invalid status '{status}'")
                    console.print(f"Valid: {', '.join(s.value for s in ResourceStatus)}")
                    raise typer.Exit(1) from None

            result = await session.execute(stmt)
            rows = result.all()

            table = Table(title="Resources")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Game", style="blue")
            table.add_column("Name", style="green")
            table.add_column("Status")
            table.add_column("Stage", style="dim")
            table.add_column("Pages", justify="right")

            for resource, game_name in rows:
                stage = resource.processing_stage.value if resource.processing_stage else "-"
                status_text = f"[{status_style(resource.status)}]{resource.status.value}[/{status_style(resource.status)}]"
                table.add_row(
                    resource.id,
                    game_name,
                    resource.name[:30] + "..." if len(resource.name) > 30 else resource.name,
                    status_text,
                    stage,
                    str(resource.page_count or "-"),
                )

            console.print(table)
            console.print(f"[dim]Showing {len(rows)} resources[/dim]")

    asyncio.run(_list())


@app.command("add")
def add_resource(
    game: Annotated[str, typer.Argument(help="Game ID or slug")],
    file_path: Annotated[Path, typer.Argument(help="Path to PDF file")],
    name: Annotated[str | None, typer.Option("--name", "-n", help="Resource name (defaults to filename)")] = None,
    resource_type: Annotated[str, typer.Option("--type", "-t", help="Resource type")] = "rulebook",
    process: bool = typer.Option(True, "--process/--no-process", help="Queue for processing after upload"),
):
    """Add a new resource (PDF) to a game."""

    async def _add():
        # Validate file exists
        if not file_path.exists():
            console.print(f"[red]Error:[/red] File not found: {file_path}")
            raise typer.Exit(1)

        if file_path.suffix.lower() != ".pdf":
            console.print("[red]Error:[/red] Only PDF files are supported")
            raise typer.Exit(1)

        # Validate resource type
        try:
            res_type = ResourceType(resource_type.lower())
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid resource type '{resource_type}'")
            console.print(f"Valid types: {', '.join(RESOURCE_TYPE_CHOICES)}")
            raise typer.Exit(1) from None

        async with get_session_context() as session:
            # Find game
            stmt = select(Game).where((Game.id == game) | (Game.slug == game))
            result = await session.execute(stmt)
            game_obj = result.scalar_one_or_none()

            if not game_obj:
                console.print(f"[red]Error:[/red] Game '{game}' not found")
                raise typer.Exit(1)

            # Read and upload file
            console.print(f"[dim]Uploading {file_path.name}...[/dim]")
            content = file_path.read_bytes()
            url, _ = await storage.upload_file(
                data=content,
                prefix="pdfs",
                extension="pdf",
            )

            # Create resource
            resource_name = name or file_path.stem.replace("_", " ").replace("-", " ").title()
            resource = Resource(
                game_id=game_obj.id,
                name=resource_name,
                original_filename=file_path.name,
                url=url,
                resource_type=res_type,
                status=ResourceStatus.QUEUED if process else ResourceStatus.READY,
            )
            session.add(resource)
            await session.commit()
            await session.refresh(resource)

            console.print(f"[green]Created resource:[/green] {resource.name}")
            console.print(f"  ID: {resource.id}")
            console.print(f"  URL: {url}")

            # Queue for processing
            if process:
                await queue.enqueue(
                    "process_resource",
                    resource_id=resource.id,
                    timeout=PIPELINE_TIMEOUT_SECONDS,
                )
                console.print("  [cyan]Queued for processing[/cyan]")

    asyncio.run(_add())


@app.command("status")
def resource_status(
    resource_id: str = typer.Argument(..., help="Resource ID"),
):
    """Check processing status of a resource."""

    async def _status():
        async with get_session_context() as session:
            stmt = (
                select(Resource, Game.name.label("game_name"))
                .join(Game, Resource.game_id == Game.id)
                .where(Resource.id == resource_id)
            )
            result = await session.execute(stmt)
            row = result.one_or_none()

            if not row:
                console.print(f"[red]Error:[/red] Resource '{resource_id}' not found")
                raise typer.Exit(1)

            resource, game_name = row

            # Get fragment count
            fragment_stmt = select(func.count(Fragment.id)).where(Fragment.resource_id == resource_id)
            fragment_result = await session.execute(fragment_stmt)
            fragment_count = fragment_result.scalar() or 0

            # Build status panel
            status_text = f"[{status_style(resource.status)}]{resource.status.value.upper()}[/{status_style(resource.status)}]"

            content = f"""[bold]Status:[/bold] {status_text}
[bold]Game:[/bold] {game_name}
[bold]Name:[/bold] {resource.name}
[bold]Type:[/bold] {resource.resource_type.value}

[bold]Processing Stage:[/bold] {resource.processing_stage.value if resource.processing_stage else 'Not started'}
[bold]Pages:[/bold] {resource.page_count or '-'}
[bold]Images:[/bold] {resource.image_count or '-'}
[bold]Words:[/bold] {resource.word_count or '-'}
[bold]Fragments:[/bold] {fragment_count}"""

            if resource.error_message:
                content += f"\n\n[bold red]Error:[/bold red] {resource.error_message}"

            if resource.current_run_id:
                content += f"\n[bold]Run ID:[/bold] {resource.current_run_id}"

            console.print(Panel(content, title=f"Resource: {resource_id}"))

            # Show progress through stages
            if resource.status in (ResourceStatus.PROCESSING, ResourceStatus.COMPLETED):
                current_idx = STAGE_ORDER.index(resource.processing_stage.value) if resource.processing_stage else -1
                progress_line = ""
                for i, stage in enumerate(STAGE_ORDER):
                    if i < current_idx:
                        progress_line += f"[green]{stage}[/green] > "
                    elif i == current_idx:
                        if resource.status == ResourceStatus.COMPLETED:
                            progress_line += f"[green]{stage}[/green]"
                        else:
                            progress_line += f"[cyan bold]{stage}[/cyan bold] > "
                    else:
                        progress_line += f"[dim]{stage}[/dim] > "
                console.print(f"\n[bold]Progress:[/bold] {progress_line.removesuffix(' > ')}")

    asyncio.run(_status())


@app.command("reprocess")
def reprocess_resource(
    resource_id: str = typer.Argument(..., help="Resource ID to reprocess"),
    from_stage: Annotated[str | None, typer.Option("--from", "-f", help="Stage to start from")] = None,
):
    """Reprocess a resource from a specific stage."""

    async def _reprocess():
        async with get_session_context() as session:
            stmt = select(Resource).where(Resource.id == resource_id)
            result = await session.execute(stmt)
            resource = result.scalar_one_or_none()

            if not resource:
                console.print(f"[red]Error:[/red] Resource '{resource_id}' not found")
                raise typer.Exit(1)

            # Validate stage
            if from_stage and from_stage.lower() not in STAGE_ORDER:
                console.print(f"[red]Error:[/red] Invalid stage '{from_stage}'")
                console.print(f"Valid stages: {', '.join(STAGE_ORDER)}")
                raise typer.Exit(1)

            # Update status
            resource.status = ResourceStatus.QUEUED
            resource.processing_stage = None
            resource.error_message = None

            await session.commit()

            # Enqueue task
            await queue.enqueue(
                "process_resource",
                resource_id=resource_id,
                start_stage=from_stage.lower() if from_stage else None,
                timeout=PIPELINE_TIMEOUT_SECONDS,
            )

            stage_msg = f" from stage '{from_stage}'" if from_stage else ""
            console.print(f"[green]Queued reprocessing[/green] for {resource.name}{stage_msg}")

    asyncio.run(_reprocess())


@app.command("reprocess-all")
def reprocess_all(
    game: Annotated[str | None, typer.Option("--game", "-g", help="Filter by game ID or slug")] = None,
    failed_only: bool = typer.Option(False, "--failed", help="Only reprocess failed resources"),
    from_stage: Annotated[str | None, typer.Option("--from", "-f", help="Stage to start from")] = None,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be reprocessed without doing it"),
):
    """Batch reprocess resources."""

    async def _reprocess_all():
        async with get_session_context() as session:
            stmt = select(Resource)

            # Filter by game
            if game:
                game_stmt = select(Game).where((Game.id == game) | (Game.slug == game))
                result = await session.execute(game_stmt)
                game_obj = result.scalar_one_or_none()
                if not game_obj:
                    console.print(f"[red]Error:[/red] Game '{game}' not found")
                    raise typer.Exit(1)
                stmt = stmt.where(Resource.game_id == game_obj.id)

            # Filter by status
            if failed_only:
                stmt = stmt.where(Resource.status == ResourceStatus.FAILED)

            # Validate stage
            if from_stage and from_stage.lower() not in STAGE_ORDER:
                console.print(f"[red]Error:[/red] Invalid stage '{from_stage}'")
                console.print(f"Valid stages: {', '.join(STAGE_ORDER)}")
                raise typer.Exit(1)

            result = await session.execute(stmt)
            resources = result.scalars().all()

            if not resources:
                console.print("[yellow]No resources match the criteria[/yellow]")
                return

            if dry_run:
                console.print(f"[yellow]Dry run:[/yellow] Would reprocess {len(resources)} resources:")
                for r in resources[:10]:
                    console.print(f"  - {r.id}: {r.name}")
                if len(resources) > 10:
                    console.print(f"  ... and {len(resources) - 10} more")
                return

            # Confirm
            if not typer.confirm(f"Reprocess {len(resources)} resources?"):
                console.print("[dim]Cancelled[/dim]")
                return

            # Reprocess each
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Queueing resources...", total=len(resources))

                for resource in resources:
                    resource.status = ResourceStatus.QUEUED
                    resource.processing_stage = None
                    resource.error_message = None

                    await queue.enqueue(
                        "process_resource",
                        resource_id=resource.id,
                        start_stage=from_stage.lower() if from_stage else None,
                        timeout=PIPELINE_TIMEOUT_SECONDS,
                    )
                    progress.advance(task)

                await session.commit()

            console.print(f"[green]Queued {len(resources)} resources for reprocessing[/green]")

    asyncio.run(_reprocess_all())
