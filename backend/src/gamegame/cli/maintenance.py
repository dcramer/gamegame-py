"""Maintenance CLI commands."""

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from gamegame.services.storage import storage
from gamegame.tasks import queue
from gamegame.tasks.maintenance import MAINTENANCE_TIMEOUT_SECONDS

console = Console()
app = typer.Typer(help="Maintenance and cleanup commands")


@app.command("cleanup-blobs")
def cleanup_blobs(
    dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Only report, don't delete"),
    background: bool = typer.Option(False, "--background", "-b", help="Run in background worker"),
):
    """Find and remove orphaned blobs from storage.

    By default runs in dry-run mode to show what would be deleted.
    Use --execute to actually delete orphaned blobs.
    """

    async def _cleanup():
        if background:
            # Queue as background job
            job = await queue.enqueue(
                "cleanup_orphaned_blobs",
                dry_run=dry_run,
                timeout=MAINTENANCE_TIMEOUT_SECONDS,
            )
            console.print(f"[green]Queued blob cleanup job:[/green] {job.id if job else 'unknown'}")
            if dry_run:
                console.print("[dim]Running in dry-run mode (will only report)[/dim]")
            else:
                console.print("[yellow]Running in execute mode (will delete files)[/yellow]")
            return

        # Run directly
        from gamegame.tasks.maintenance import cleanup_orphaned_blobs

        console.print("[cyan]Scanning for orphaned blobs...[/cyan]")

        result = await cleanup_orphaned_blobs(ctx={}, dry_run=dry_run)

        if not result.get("success"):
            console.print(f"[red]Error:[/red] {result.get('error')}")
            raise typer.Exit(1)

        # Display results
        table = Table(title="Blob Cleanup Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Database References", str(result.get("db_references", 0)))
        table.add_row("Storage Blobs", str(result.get("storage_blobs", 0)))
        table.add_row("Orphaned Blobs", str(result.get("orphaned_count", 0)))

        if dry_run:
            table.add_row("Would Delete", str(result.get("orphaned_count", 0)))
        else:
            table.add_row("Deleted", str(result.get("deleted_count", 0)))
            if result.get("failed_deletions"):
                table.add_row("Failed", str(len(result["failed_deletions"])))

        console.print(table)

        if dry_run and result.get("orphaned_count", 0) > 0:
            console.print("\n[yellow]Dry run mode - no files were deleted.[/yellow]")
            console.print("Run with --execute to delete orphaned blobs.")

    asyncio.run(_cleanup())


@app.command("prune-workflows")
def prune_workflows(
    retention_days: int = typer.Option(30, "--days", "-d", help="Keep runs newer than this"),
    dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Only report, don't delete"),
    background: bool = typer.Option(False, "--background", "-b", help="Run in background worker"),
):
    """Delete old workflow run records.

    By default keeps runs from the last 30 days and runs in dry-run mode.
    """

    async def _prune():
        if background:
            job = await queue.enqueue(
                "prune_workflow_runs",
                retention_days=retention_days,
                dry_run=dry_run,
                timeout=MAINTENANCE_TIMEOUT_SECONDS,
            )
            console.print(f"[green]Queued workflow prune job:[/green] {job.id if job else 'unknown'}")
            return

        from gamegame.tasks.maintenance import prune_workflow_runs

        console.print(f"[cyan]Scanning for workflow runs older than {retention_days} days...[/cyan]")

        result = await prune_workflow_runs(
            ctx={}, retention_days=retention_days, dry_run=dry_run
        )

        if not result.get("success"):
            console.print(f"[red]Error:[/red] {result.get('error')}")
            raise typer.Exit(1)

        count = result.get("runs_would_delete", 0)

        if dry_run:
            console.print(f"\n[yellow]Found {count} workflow runs to delete.[/yellow]")
            console.print("Run with --execute to delete them.")
        else:
            console.print(f"\n[green]Deleted {result.get('runs_deleted', 0)} workflow runs.[/green]")

    asyncio.run(_prune())


@app.command("storage-stats")
def storage_stats():
    """Show storage usage statistics."""

    async def _stats():
        from pathlib import Path

        # Get all blobs
        all_blobs = await storage.list_files()

        # Calculate total size
        total_size = 0
        by_prefix: dict[str, dict[str, int]] = {}

        for key in all_blobs:
            file_path = Path(storage.upload_dir) / key
            if file_path.exists():
                size = file_path.stat().st_size
                total_size += size

                # Group by first path component
                prefix = key.split("/")[0] if "/" in key else "root"
                if prefix not in by_prefix:
                    by_prefix[prefix] = {"count": 0, "size": 0}
                by_prefix[prefix]["count"] += 1
                by_prefix[prefix]["size"] += size

        # Display results
        table = Table(title="Storage Statistics")
        table.add_column("Category", style="cyan")
        table.add_column("Files", justify="right")
        table.add_column("Size", justify="right")

        for prefix, stats in sorted(by_prefix.items()):
            size_str = _format_size(stats["size"])
            table.add_row(prefix, str(stats["count"]), size_str)

        table.add_row("─" * 15, "─" * 8, "─" * 10, style="dim")
        table.add_row("Total", str(len(all_blobs)), _format_size(total_size), style="bold")

        console.print(table)

    asyncio.run(_stats())


def _format_size(size: float) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
