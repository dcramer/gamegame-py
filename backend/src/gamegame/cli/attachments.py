"""Attachment management CLI commands."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlmodel import select

from gamegame.database import get_session_context
from gamegame.models import Attachment, Game, Resource
from gamegame.models.attachment import QualityRating
from gamegame.services.attachment_analysis import (
    build_attachment_context,
    get_attachment_image_data,
    update_attachment_from_analysis,
)

console = Console()
app = typer.Typer(help="Attachment management commands")


@app.command("list")
def list_attachments(
    resource: Annotated[str | None, typer.Option("--resource", "-r", help="Filter by resource ID")] = None,
    game: Annotated[str | None, typer.Option("--game", "-g", help="Filter by game ID or slug")] = None,
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum attachments to show"),
):
    """List attachments."""

    async def _list():
        async with get_session_context() as session:
            stmt = (
                select(Attachment)
                .order_by(Attachment.created_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )

            if resource:
                stmt = stmt.where(Attachment.resource_id == resource)

            if game:
                game_stmt = select(Game).where((Game.id == game) | (Game.slug == game))
                result = await session.execute(game_stmt)
                game_obj = result.scalar_one_or_none()
                if not game_obj:
                    console.print(f"[red]Error:[/red] Game '{game}' not found")
                    raise typer.Exit(1)
                stmt = stmt.where(Attachment.game_id == game_obj.id)

            result = await session.execute(stmt)
            attachments = result.scalars().all()

            table = Table(title="Attachments")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Type", style="blue")
            table.add_column("MIME", style="dim")
            table.add_column("Page", justify="right")
            table.add_column("Quality")
            table.add_column("Description")

            for att in attachments:
                quality = "✓" if att.is_good_quality else "✗" if att.is_good_quality is False else "-"
                quality_style = "green" if att.is_good_quality else "red" if att.is_good_quality is False else "dim"
                desc = (att.description or "-")[:40]
                if len(att.description or "") > 40:
                    desc += "..."

                table.add_row(
                    att.id,
                    att.detected_type or att.type.value,
                    att.mime_type,
                    str(att.page_number or "-"),
                    f"[{quality_style}]{quality}[/{quality_style}]",
                    desc,
                )

            console.print(table)
            console.print(f"[dim]Showing {len(attachments)} attachments[/dim]")

    asyncio.run(_list())


@app.command("show")
def show_attachment(
    attachment_id: str = typer.Argument(..., help="Attachment ID"),
):
    """Show detailed attachment info."""

    async def _show():
        async with get_session_context() as session:
            stmt = select(Attachment).where(Attachment.id == attachment_id)
            result = await session.execute(stmt)
            attachment = result.scalar_one_or_none()

            if not attachment:
                console.print(f"[red]Error:[/red] Attachment '{attachment_id}' not found")
                raise typer.Exit(1)

            if attachment.is_good_quality == QualityRating.GOOD:
                quality_text, quality_style = "Good", "green"
            elif attachment.is_good_quality == QualityRating.BAD:
                quality_text, quality_style = "Bad", "red"
            else:
                quality_text, quality_style = "Unknown", "yellow"

            content = f"""[bold]ID:[/bold] {attachment.id}
[bold]Type:[/bold] {attachment.type.value}
[bold]Detected Type:[/bold] {attachment.detected_type.value if attachment.detected_type else '-'}
[bold]MIME Type:[/bold] {attachment.mime_type}
[bold]Page:[/bold] {attachment.page_number or '-'}
[bold]Quality:[/bold] [{quality_style}]{quality_text}[/{quality_style}]
[bold]URL:[/bold] {attachment.url}
[bold]Blob Key:[/bold] {attachment.blob_key}

[bold]Description:[/bold]
{attachment.description or '[dim]No description[/dim]'}"""

            if attachment.ocr_text:
                content += f"\n\n[bold]OCR Text:[/bold]\n{attachment.ocr_text}"

            console.print(Panel(content, title=f"Attachment: {attachment_id}"))

    asyncio.run(_show())


@app.command("analyze")
def analyze_attachment(
    target: str = typer.Argument(..., help="Attachment ID or file path to analyze"),
    game_name: Annotated[str | None, typer.Option("--game", "-g", help="Game name for context")] = None,
    resource_name: Annotated[str | None, typer.Option("--resource", "-r", help="Resource name for context")] = None,
    page: int = typer.Option(1, "--page", "-p", help="Page number for context"),
):
    """Analyze an image using the vision model.

    This is useful for testing that image analysis is working correctly.
    You can pass either an attachment ID or a local file path.
    """
    from gamegame.config import settings

    if not settings.openai_api_key:
        console.print("[red]Error:[/red] OPENAI_API_KEY not configured")
        raise typer.Exit(1)

    async def _analyze():
        from gamegame.services.pipeline.vision import (
            ImageAnalysisContext,
            analyze_single_image,
        )

        # Determine if target is a file path or attachment ID
        target_path = Path(target)
        if target_path.exists():
            # It's a file path - use basic context
            console.print(f"[dim]Reading image from file: {target_path}[/dim]")
            image_data = target_path.read_bytes()
            context = ImageAnalysisContext(
                page_number=page,
                game_name=game_name,
                resource_name=resource_name,
            )
        else:
            # Try to find attachment
            async with get_session_context() as session:
                stmt = select(Attachment).where(Attachment.id == target)
                result = await session.execute(stmt)
                attachment = result.scalar_one_or_none()

                if not attachment:
                    console.print(f"[red]Error:[/red] '{target}' is not a valid file path or attachment ID")
                    raise typer.Exit(1)

                console.print(f"[dim]Loading attachment: {attachment.id}[/dim]")

                # Get the image data using shared function
                try:
                    image_data = await get_attachment_image_data(attachment)
                except ValueError as e:
                    console.print(f"[red]Error:[/red] {e}")
                    raise typer.Exit(1) from None

                # Get resource content for context extraction
                resource_content = None
                if attachment.resource_id:
                    resource_stmt = select(Resource.content).where(Resource.id == attachment.resource_id)
                    resource_result = await session.execute(resource_stmt)
                    resource_content = resource_result.scalar_one_or_none()

                # Build context using shared function (with markdown context)
                context = await build_attachment_context(
                    session, attachment, resource_content=resource_content
                )

                # Override with CLI args if provided
                if game_name:
                    context.game_name = game_name
                if resource_name:
                    context.resource_name = resource_name

        # Analyze the image
        console.print("[cyan]Analyzing image...[/cyan]")

        try:
            result = await analyze_single_image(image_data, context)

            quality_style = "green" if result.quality.value == "good" else "red"

            content = f"""[bold]Quality:[/bold] [{quality_style}]{result.quality.value.upper()}[/{quality_style}]
[bold]Type:[/bold] {result.image_type.value}
[bold]Relevant:[/bold] {"Yes" if result.relevant else "No"}

[bold]Description:[/bold]
{result.description}"""

            if result.ocr_text:
                content += f"\n\n[bold]OCR Text:[/bold]\n{result.ocr_text}"

            console.print(Panel(content, title="Analysis Result"))

        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None
        except Exception as e:
            console.print(f"[red]Analysis failed:[/red] {e}")
            raise typer.Exit(1) from None

    asyncio.run(_analyze())


@app.command("reanalyze")
def reanalyze_attachment(
    attachment_id: str = typer.Argument(..., help="Attachment ID to reanalyze"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show result without saving"),
):
    """Reanalyze an existing attachment and update its metadata."""
    from gamegame.config import settings

    if not settings.openai_api_key:
        console.print("[red]Error:[/red] OPENAI_API_KEY not configured")
        raise typer.Exit(1)

    async def _reanalyze():
        from gamegame.services.pipeline.vision import analyze_single_image

        async with get_session_context() as session:
            stmt = select(Attachment).where(Attachment.id == attachment_id)
            result = await session.execute(stmt)
            attachment = result.scalar_one_or_none()

            if not attachment:
                console.print(f"[red]Error:[/red] Attachment '{attachment_id}' not found")
                raise typer.Exit(1)

            # Get resource content for context extraction
            resource_content = None
            if attachment.resource_id:
                resource_stmt = select(Resource.content).where(Resource.id == attachment.resource_id)
                resource_result = await session.execute(resource_stmt)
                resource_content = resource_result.scalar_one_or_none()

            # Build context using shared function
            context = await build_attachment_context(
                session, attachment, resource_content=resource_content
            )

            # Load image data
            console.print(f"[dim]Loading attachment: {attachment.id}[/dim]")
            try:
                image_data = await get_attachment_image_data(attachment)
            except ValueError as e:
                console.print(f"[red]Error:[/red] {e}")
                raise typer.Exit(1) from None

            # Analyze
            console.print("[cyan]Analyzing image...[/cyan]")

            try:
                analysis = await analyze_single_image(image_data, context)

                quality_style = "green" if analysis.quality.value == "good" else "red"

                content = f"""[bold]Quality:[/bold] [{quality_style}]{analysis.quality.value.upper()}[/{quality_style}]
[bold]Type:[/bold] {analysis.image_type.value}
[bold]Relevant:[/bold] {"Yes" if analysis.relevant else "No"}

[bold]Description:[/bold]
{analysis.description}"""

                if analysis.ocr_text:
                    content += f"\n\n[bold]OCR Text:[/bold]\n{analysis.ocr_text}"

                console.print(Panel(content, title="Analysis Result"))

                if dry_run:
                    console.print("\n[yellow]Dry run - not saving changes[/yellow]")
                else:
                    # Update attachment using shared function
                    update_attachment_from_analysis(attachment, analysis)
                    await session.commit()
                    console.print("\n[green]Attachment updated[/green]")

            except ValueError as e:
                console.print(f"[red]Error:[/red] {e}")
                raise typer.Exit(1) from None
            except Exception as e:
                console.print(f"[red]Analysis failed:[/red] {e}")
                raise typer.Exit(1) from None

    asyncio.run(_reanalyze())


@app.command("reanalyze-failed")
def reanalyze_failed(
    resource: Annotated[str | None, typer.Option("--resource", "-r", help="Filter by resource ID")] = None,
    game: Annotated[str | None, typer.Option("--game", "-g", help="Filter by game ID or slug")] = None,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be reanalyzed without doing it"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum attachments to process"),
):
    """Reanalyze all attachments that have 'Analysis failed' description."""
    from gamegame.config import settings

    if not settings.openai_api_key:
        console.print("[red]Error:[/red] OPENAI_API_KEY not configured")
        raise typer.Exit(1)

    async def _reanalyze_failed():
        from gamegame.services.pipeline.vision import analyze_single_image

        async with get_session_context() as session:
            # Build query for failed attachments
            stmt = (
                select(Attachment)
                .where(Attachment.description == "Analysis failed")
                .order_by(Attachment.created_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )

            if resource:
                stmt = stmt.where(Attachment.resource_id == resource)

            if game:
                game_stmt = select(Game).where((Game.id == game) | (Game.slug == game))
                result = await session.execute(game_stmt)
                game_obj = result.scalar_one_or_none()
                if not game_obj:
                    console.print(f"[red]Error:[/red] Game '{game}' not found")
                    raise typer.Exit(1)
                stmt = stmt.where(Attachment.game_id == game_obj.id)

            result = await session.execute(stmt)
            attachments = list(result.scalars().all())

            if not attachments:
                console.print("[green]No failed attachments found[/green]")
                return

            console.print(f"Found {len(attachments)} attachments with 'Analysis failed'")

            if dry_run:
                console.print("[yellow]Dry run - not making changes[/yellow]")
                for att in attachments[:10]:
                    console.print(f"  - {att.id} (page {att.page_number})")
                if len(attachments) > 10:
                    console.print(f"  ... and {len(attachments) - 10} more")
                return

            # Cache resource content by resource_id to avoid repeated queries
            resource_content_cache: dict[str, str | None] = {}

            # Process each attachment
            success_count = 0
            fail_count = 0

            for i, attachment in enumerate(attachments):
                console.print(f"[dim][{i+1}/{len(attachments)}] Processing {attachment.id}...[/dim]")

                try:
                    # Get resource content for context (with caching)
                    resource_content = None
                    if attachment.resource_id:
                        if attachment.resource_id not in resource_content_cache:
                            resource_stmt = select(Resource.content).where(
                                Resource.id == attachment.resource_id
                            )
                            resource_result = await session.execute(resource_stmt)
                            resource_content_cache[attachment.resource_id] = (
                                resource_result.scalar_one_or_none()
                            )
                        resource_content = resource_content_cache[attachment.resource_id]

                    # Build context using shared function
                    context = await build_attachment_context(
                        session, attachment, resource_content=resource_content
                    )

                    # Load image data
                    try:
                        image_data = await get_attachment_image_data(attachment)
                    except ValueError:
                        console.print("  [red]Could not load image data[/red]")
                        fail_count += 1
                        continue

                    # Analyze
                    analysis = await analyze_single_image(image_data, context)

                    # Update attachment using shared function
                    update_attachment_from_analysis(attachment, analysis)

                    quality_icon = "✓" if analysis.quality.value == "good" else "✗"
                    desc = analysis.description[:50] if analysis.description else "(no description)"
                    console.print(f"  [{quality_icon}] {analysis.image_type.value}: {desc}...")
                    success_count += 1

                except Exception as e:
                    console.print(f"  [red]Error: {e}[/red]")
                    fail_count += 1

            await session.commit()

            console.print(f"\n[green]Completed:[/green] {success_count} updated, {fail_count} failed")

    asyncio.run(_reanalyze_failed())


@app.command("update-dimensions")
def update_dimensions(
    resource: Annotated[str | None, typer.Option("--resource", "-r", help="Filter by resource ID")] = None,
    game: Annotated[str | None, typer.Option("--game", "-g", help="Filter by game ID or slug")] = None,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be updated without doing it"),
    limit: int = typer.Option(500, "--limit", "-l", help="Maximum attachments to process"),
):
    """Update dimensions for attachments that are missing width/height."""
    import io

    from PIL import Image

    async def _update_dimensions():
        async with get_session_context() as session:
            # Build query for attachments missing dimensions
            stmt = (
                select(Attachment)
                .where((Attachment.width.is_(None)) | (Attachment.height.is_(None)))  # type: ignore[union-attr]
                .order_by(Attachment.created_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )

            if resource:
                stmt = stmt.where(Attachment.resource_id == resource)

            if game:
                game_stmt = select(Game).where((Game.id == game) | (Game.slug == game))
                result = await session.execute(game_stmt)
                game_obj = result.scalar_one_or_none()
                if not game_obj:
                    console.print(f"[red]Error:[/red] Game '{game}' not found")
                    raise typer.Exit(1)
                stmt = stmt.where(Attachment.game_id == game_obj.id)

            result = await session.execute(stmt)
            attachments = list(result.scalars().all())

            if not attachments:
                console.print("[green]No attachments missing dimensions[/green]")
                return

            console.print(f"Found {len(attachments)} attachments missing dimensions")

            if dry_run:
                console.print("[yellow]Dry run - not making changes[/yellow]")
                for att in attachments[:10]:
                    console.print(f"  - {att.id}")
                if len(attachments) > 10:
                    console.print(f"  ... and {len(attachments) - 10} more")
                return

            success_count = 0
            fail_count = 0

            for i, attachment in enumerate(attachments):
                try:
                    image_data = await get_attachment_image_data(attachment)
                    with Image.open(io.BytesIO(image_data)) as img:
                        attachment.width = img.width
                        attachment.height = img.height
                    success_count += 1

                    if (i + 1) % 50 == 0:
                        console.print(f"[dim]Processed {i + 1}/{len(attachments)}...[/dim]")

                except Exception as e:
                    console.print(f"[red]Error processing {attachment.id}: {e}[/red]")
                    fail_count += 1

            await session.commit()
            console.print(f"\n[green]Completed:[/green] {success_count} updated, {fail_count} failed")

    asyncio.run(_update_dimensions())


@app.command("update-hashes")
def update_hashes(
    resource: Annotated[str | None, typer.Option("--resource", "-r", help="Filter by resource ID")] = None,
    game: Annotated[str | None, typer.Option("--game", "-g", help="Filter by game ID or slug")] = None,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be updated without doing it"),
    limit: int = typer.Option(500, "--limit", "-l", help="Maximum attachments to process"),
):
    """Update content_hash for attachments that are missing it.

    This is used to backfill hashes for existing attachments, enabling
    hash-based deduplication during resource reprocessing.
    """
    import hashlib

    async def _update_hashes():
        async with get_session_context() as session:
            # Build query for attachments missing content_hash
            stmt = (
                select(Attachment)
                .where(Attachment.content_hash.is_(None))  # type: ignore[union-attr]
                .order_by(Attachment.created_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )

            if resource:
                stmt = stmt.where(Attachment.resource_id == resource)

            if game:
                game_stmt = select(Game).where((Game.id == game) | (Game.slug == game))
                result = await session.execute(game_stmt)
                game_obj = result.scalar_one_or_none()
                if not game_obj:
                    console.print(f"[red]Error:[/red] Game '{game}' not found")
                    raise typer.Exit(1)
                stmt = stmt.where(Attachment.game_id == game_obj.id)

            result = await session.execute(stmt)
            attachments = list(result.scalars().all())

            if not attachments:
                console.print("[green]No attachments missing content_hash[/green]")
                return

            console.print(f"Found {len(attachments)} attachments missing content_hash")

            if dry_run:
                console.print("[yellow]Dry run - not making changes[/yellow]")
                for att in attachments[:10]:
                    console.print(f"  - {att.id}")
                if len(attachments) > 10:
                    console.print(f"  ... and {len(attachments) - 10} more")
                return

            success_count = 0
            fail_count = 0

            for i, attachment in enumerate(attachments):
                try:
                    image_data = await get_attachment_image_data(attachment)
                    attachment.content_hash = hashlib.sha256(image_data).hexdigest()
                    success_count += 1

                    if (i + 1) % 50 == 0:
                        console.print(f"[dim]Processed {i + 1}/{len(attachments)}...[/dim]")

                except Exception as e:
                    console.print(f"[red]Error processing {attachment.id}: {e}[/red]")
                    fail_count += 1

            await session.commit()
            console.print(f"\n[green]Completed:[/green] {success_count} updated, {fail_count} failed")

    asyncio.run(_update_hashes())
