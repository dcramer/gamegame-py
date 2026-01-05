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
from gamegame.models import Fragment, Game, Resource, Segment
from gamegame.models.resource import ResourceStatus, ResourceType
from gamegame.services.storage import storage
from gamegame.tasks import queue
from gamegame.tasks.queue import PIPELINE_TIMEOUT_SECONDS

console = Console()
app = typer.Typer(help="Resource management commands")

STAGE_ORDER = ["ingest", "vision", "cleanup", "metadata", "segment", "embed", "finalize"]

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
                select(Resource, Game.name.label("game_name"))  # type: ignore[attr-defined]
                .join(Game, Resource.game_id == Game.id)
                .order_by(Resource.created_at.desc())  # type: ignore[attr-defined]
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
                select(Resource, Game.name.label("game_name"))  # type: ignore[attr-defined]
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

            # Get segment count (for parent document retrieval)
            segment_stmt = select(func.count(Segment.id)).where(Segment.resource_id == resource_id)
            segment_result = await session.execute(segment_stmt)
            segment_count = segment_result.scalar() or 0

            # Build status panel
            status_text = f"[{status_style(resource.status)}]{resource.status.value.upper()}[/{status_style(resource.status)}]"

            content = f"""[bold]Status:[/bold] {status_text}
[bold]Game:[/bold] {game_name}
[bold]Name:[/bold] {resource.name}
[bold]Type:[/bold] {resource.resource_type.value}

[bold]Processing Stage:[/bold] {resource.processing_stage.value if resource.processing_stage else 'Not started'}
[bold]PDF Pages:[/bold] {resource.page_count or '-'}
[bold]Segments:[/bold] {segment_count}
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


@app.command("run-stage")
def run_stage(
    resource_id: str = typer.Argument(..., help="Resource ID"),
    stage: str = typer.Argument(..., help="Stage to run (ingest, vision, cleanup, metadata, segment, embed, finalize)"),
):
    """Run a single pipeline stage synchronously (for debugging)."""

    async def _run_stage():
        from gamegame.models.resource import ProcessingStage
        from gamegame.tasks.pipeline import _run_stage as pipeline_run_stage

        # Validate stage
        stage_lower = stage.lower()
        if stage_lower not in STAGE_ORDER:
            console.print(f"[red]Error:[/red] Invalid stage '{stage}'")
            console.print(f"Valid stages: {', '.join(STAGE_ORDER)}")
            raise typer.Exit(1)

        async with get_session_context() as session:
            stmt = select(Resource).where(Resource.id == resource_id)
            result = await session.execute(stmt)
            resource = result.scalar_one_or_none()

            if not resource:
                console.print(f"[red]Error:[/red] Resource '{resource_id}' not found")
                raise typer.Exit(1)

            console.print(f"[bold]Resource:[/bold] {resource.name}")
            console.print(f"[bold]Current stage:[/bold] {resource.processing_stage.value if resource.processing_stage else 'None'}")
            console.print(f"[bold]Running stage:[/bold] {stage_lower}")
            console.print()

            # Load existing state
            state: dict = resource.processing_metadata or {}

            # Show state keys for context
            if state:
                console.print(f"[dim]State keys: {', '.join(state.keys())}[/dim]")
            else:
                console.print("[yellow]Warning:[/yellow] No existing state - stage may fail if it depends on prior stages")

            try:
                stage_enum = ProcessingStage(stage_lower)
                new_state = await pipeline_run_stage(session, resource, stage_enum, state)

                # Update resource
                resource.processing_metadata = new_state
                resource.processing_stage = stage_enum
                await session.commit()

                console.print()
                console.print(f"[green]Stage '{stage_lower}' completed successfully[/green]")

                # Show relevant results
                if stage_lower == "metadata":
                    console.print(f"[bold]Name:[/bold] {resource.name}")
                    console.print(f"[bold]Description:[/bold] {resource.description or '[none]'}")
                elif stage_lower == "segment":
                    console.print(f"[bold]Segments created:[/bold] {new_state.get('segments_created', 'unknown')}")
                elif stage_lower == "embed":
                    console.print(f"[bold]Fragments created:[/bold] {new_state.get('fragments_created', 'unknown')}")
                elif stage_lower == "ingest":
                    console.print(f"[bold]Pages:[/bold] {new_state.get('page_count', 'unknown')}")
                    console.print(f"[bold]Images:[/bold] {len(new_state.get('extracted_images', []))}")

            except Exception as e:
                console.print(f"[red]Stage failed:[/red] {e}")
                raise typer.Exit(1) from None

    asyncio.run(_run_stage())


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


@app.command("extract-segments")
def extract_segments(
    resource_id: str = typer.Argument(..., help="Resource ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show results without saving"),
):
    """Re-run segment extraction for a resource.

    This command extracts semantic segments from the resource's markdown content
    using the LLM, without running the full pipeline.
    """
    from gamegame.config import settings

    if not settings.openai_api_key:
        console.print("[red]Error:[/red] OPENAI_API_KEY not configured")
        raise typer.Exit(1)

    async def _extract():
        from gamegame.models import Segment
        from gamegame.services.pipeline.segments import extract_segments_llm

        async with get_session_context() as session:
            stmt = select(Resource).where(Resource.id == resource_id)
            result = await session.execute(stmt)
            resource = result.scalar_one_or_none()

            if not resource:
                console.print(f"[red]Error:[/red] Resource '{resource_id}' not found")
                raise typer.Exit(1)

            if not resource.content:
                console.print("[red]Error:[/red] Resource has no content. Run the pipeline first.")
                raise typer.Exit(1)

            console.print(f"[bold]Resource:[/bold] {resource.name}")
            console.print(f"[dim]Content length: {len(resource.content)} chars[/dim]")
            console.print()

            # Get page boundaries from metadata if available
            page_boundaries = None
            if resource.processing_metadata:
                page_boundaries = resource.processing_metadata.get("page_boundaries")

            console.print("[cyan]Extracting segments...[/cyan]")

            try:
                segments = await extract_segments_llm(
                    resource.content,
                    page_boundaries=page_boundaries,
                    resource_name=resource.name,
                )

                console.print(f"\n[green]Extracted {len(segments)} segments:[/green]")

                # Build a simple table
                table = Table(title="Segments")
                table.add_column("Order", justify="right", style="cyan")
                table.add_column("Level", justify="right")
                table.add_column("Title", style="green")
                table.add_column("Pages")
                table.add_column("Words", justify="right")

                for seg in segments:
                    pages = f"{seg.page_start}-{seg.page_end}" if seg.page_start and seg.page_end else "-"
                    table.add_row(
                        str(seg.order_index),
                        str(seg.level),
                        seg.title[:40] + "..." if len(seg.title) > 40 else seg.title,
                        pages,
                        str(seg.word_count),
                    )

                console.print(table)

                if dry_run:
                    console.print("\n[yellow]Dry run - not saving changes[/yellow]")
                else:
                    # Delete existing segments (must clear fragment references first)
                    from sqlalchemy import delete, update

                    from gamegame.models import Fragment

                    # Clear segment_id on fragments to avoid FK violation
                    await session.execute(
                        update(Fragment)
                        .where(Fragment.resource_id == resource.id)  # type: ignore[arg-type]
                        .values(segment_id=None)
                    )
                    await session.execute(
                        delete(Segment).where(Segment.resource_id == resource.id)  # type: ignore[arg-type]
                    )

                    # Create new segments
                    for seg_data in segments:
                        segment = Segment(
                            resource_id=resource.id,
                            game_id=resource.game_id,
                            title=seg_data.title,
                            hierarchy_path=seg_data.hierarchy_path,
                            level=seg_data.level,
                            order_index=seg_data.order_index,
                            content=seg_data.content,
                            page_start=seg_data.page_start,
                            page_end=seg_data.page_end,
                            word_count=seg_data.word_count,
                            char_count=seg_data.char_count,
                            parent_id=seg_data.parent_id,
                        )
                        session.add(segment)

                    await session.commit()
                    console.print(f"\n[green]Saved {len(segments)} segments to database[/green]")

            except Exception as e:
                console.print(f"[red]Extraction failed:[/red] {e}")
                raise typer.Exit(1) from None

    asyncio.run(_extract())


@app.command("embed-segment")
def embed_segment(
    segment_id: str = typer.Argument(..., help="Segment ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show results without saving"),
):
    """Re-embed a single segment's fragments.

    This command chunks a segment and generates embeddings for each fragment,
    without running the full pipeline.
    """
    from gamegame.config import settings

    if not settings.openai_api_key:
        console.print("[red]Error:[/red] OPENAI_API_KEY not configured")
        raise typer.Exit(1)

    async def _embed():
        from sqlalchemy import delete

        from gamegame.models import Embedding, Fragment, Segment
        from gamegame.services.pipeline.embed import chunk_segments, generate_embeddings
        from gamegame.services.pipeline.segments import SegmentData

        async with get_session_context() as session:
            stmt = select(Segment).where(Segment.id == segment_id)
            result = await session.execute(stmt)
            segment = result.scalar_one_or_none()

            if not segment:
                console.print(f"[red]Error:[/red] Segment '{segment_id}' not found")
                raise typer.Exit(1)

            # Get the resource for context
            resource_stmt = select(Resource).where(Resource.id == segment.resource_id)
            resource_result = await session.execute(resource_stmt)
            resource = resource_result.scalar_one()

            console.print(f"[bold]Segment:[/bold] {segment.title}")
            console.print(f"[bold]Resource:[/bold] {resource.name}")
            console.print(f"[dim]Content length: {len(segment.content)} chars[/dim]")
            console.print()

            # Convert to SegmentData for chunking
            segment_data = SegmentData(
                title=segment.title,
                hierarchy_path=segment.hierarchy_path or "",
                level=segment.level,
                order_index=segment.order_index,
                content=segment.content,
                page_start=segment.page_start,
                page_end=segment.page_end,
                word_count=segment.word_count or 0,
                char_count=segment.char_count or 0,
                parent_id=segment.parent_id,
            )

            console.print("[cyan]Chunking segment...[/cyan]")
            chunks = chunk_segments([segment_data])

            console.print(f"Created {len(chunks)} fragments")

            if not chunks:
                console.print("[yellow]No fragments created - segment may be too small[/yellow]")
                return

            console.print("[cyan]Generating embeddings...[/cyan]")

            try:
                # Generate embeddings for all fragments
                texts = [chunk.content for chunk in chunks]
                embeddings = await generate_embeddings(texts)

                console.print(f"Generated {len(embeddings)} embeddings")

                if dry_run:
                    console.print("\n[yellow]Dry run - not saving changes[/yellow]")
                    for i, chunk in enumerate(chunks):
                        preview = chunk.content[:60].replace("\n", " ")
                        console.print(f"  [{i+1}] {preview}...")
                else:
                    # Delete existing fragments for this segment
                    existing_frags_stmt = select(Fragment.id).where(
                        Fragment.segment_id == segment.id  # type: ignore[arg-type]
                    )
                    existing_result = await session.execute(existing_frags_stmt)
                    existing_ids = [row[0] for row in existing_result.all()]

                    if existing_ids:
                        await session.execute(
                            delete(Embedding).where(Embedding.fragment_id.in_(existing_ids))  # type: ignore[arg-type]
                        )
                        await session.execute(
                            delete(Fragment).where(Fragment.id.in_(existing_ids))  # type: ignore[arg-type]
                        )
                        console.print(f"[dim]Deleted {len(existing_ids)} existing fragments[/dim]")

                    # Create new fragments
                    for i, chunk in enumerate(chunks):
                        # Get page range from chunk
                        page_start = chunk.page_range[0] if chunk.page_range else chunk.page_number
                        page_end = chunk.page_range[-1] if chunk.page_range else chunk.page_number

                        fragment = Fragment(
                            resource_id=resource.id,
                            game_id=resource.game_id,
                            segment_id=segment.id,
                            content=chunk.content,
                            segment_title=segment.title,
                            page_start=page_start,
                            page_end=page_end,
                            embedding=embeddings[i],
                        )
                        session.add(fragment)
                        await session.flush()

                        # Create content embedding
                        content_emb = Embedding(
                            fragment_id=fragment.id,
                            embedding_type="content",
                            text=fragment.content,
                            embedding=embeddings[i],
                        )
                        session.add(content_emb)

                    await session.commit()
                    console.print(f"\n[green]Saved {len(chunks)} fragments with embeddings[/green]")

            except Exception as e:
                console.print(f"[red]Embedding failed:[/red] {e}")
                raise typer.Exit(1) from None

    asyncio.run(_embed())
