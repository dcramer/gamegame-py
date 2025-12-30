"""Workflow management CLI commands."""

import asyncio
from datetime import datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlmodel import select

from gamegame.database import get_session_context
from gamegame.models import Game, Resource
from gamegame.models.workflow_run import WorkflowRun
from gamegame.tasks import queue
from gamegame.tasks.queue import PIPELINE_TIMEOUT_SECONDS

console = Console()
app = typer.Typer(help="Workflow management commands")


def status_style(status: str) -> str:
    """Get Rich style for workflow status."""
    return {
        "queued": "yellow",
        "running": "cyan",
        "completed": "green",
        "failed": "red",
        "cancelled": "dim",
    }.get(status, "white")


def format_duration(start: datetime | None, end: datetime | None) -> str:
    """Format duration between two datetimes."""
    if not start:
        return "-"
    end_time = end or datetime.now(start.tzinfo)
    duration = end_time - start
    seconds = int(duration.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


@app.command("list")
def list_workflows(
    game: Annotated[str | None, typer.Option("--game", "-g", help="Filter by game ID or slug")] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum workflows to show"),
):
    """List workflow runs."""

    async def _list():
        async with get_session_context() as session:
            stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(limit)  # type: ignore[attr-defined]

            # Filter by game
            if game:
                game_stmt = select(Game).where((Game.id == game) | (Game.slug == game))
                result = await session.execute(game_stmt)
                game_obj = result.scalar_one_or_none()
                if not game_obj:
                    console.print(f"[red]Error:[/red] Game '{game}' not found")
                    raise typer.Exit(1)
                stmt = stmt.where(WorkflowRun.game_id == game_obj.id)

            # Filter by status
            if status:
                valid_statuses = ["queued", "running", "completed", "failed", "cancelled"]
                status_lower = status.lower()
                if status_lower not in valid_statuses:
                    console.print(f"[red]Error:[/red] Invalid status '{status}'")
                    console.print(f"Valid: {', '.join(valid_statuses)}")
                    raise typer.Exit(1)
                stmt = stmt.where(WorkflowRun.status == status_lower)

            result = await session.execute(stmt)
            workflows = result.scalars().all()

            if not workflows:
                console.print("[dim]No workflows found[/dim]")
                return

            table = Table(title="Workflow Runs")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Name", style="blue")
            table.add_column("Status")
            table.add_column("Duration", justify="right")
            table.add_column("Resource", style="dim")
            table.add_column("Created", style="dim")

            for wf in workflows:
                status_text = f"[{status_style(wf.status)}]{wf.status}[/{status_style(wf.status)}]"
                duration = format_duration(wf.started_at, wf.completed_at)
                resource = wf.resource_id[:8] + "..." if wf.resource_id else "-"
                created = wf.created_at.strftime("%Y-%m-%d %H:%M") if wf.created_at else "-"

                table.add_row(
                    wf.id[:12] + "...",
                    wf.workflow_name,
                    status_text,
                    duration,
                    resource,
                    created,
                )

            console.print(table)
            console.print(f"[dim]Showing {len(workflows)} workflows[/dim]")

    asyncio.run(_list())


@app.command("show")
def show_workflow(
    workflow_id: str = typer.Argument(..., help="Workflow ID"),
):
    """Show details for a workflow run."""

    async def _show():
        async with get_session_context() as session:
            # Try partial match on ID
            stmt = select(WorkflowRun).where(WorkflowRun.id.startswith(workflow_id))
            result = await session.execute(stmt)
            workflow = result.scalar_one_or_none()

            if not workflow:
                # Try full ID match
                stmt = select(WorkflowRun).where(WorkflowRun.id == workflow_id)
                result = await session.execute(stmt)
                workflow = result.scalar_one_or_none()

            if not workflow:
                console.print(f"[red]Error:[/red] Workflow '{workflow_id}' not found")
                raise typer.Exit(1)

            # Get resource name if applicable
            resource_name = None
            if workflow.resource_id:
                stmt = select(Resource.name).where(Resource.id == workflow.resource_id)
                result = await session.execute(stmt)
                resource_name = result.scalar_one_or_none()

            status_text = f"[{status_style(workflow.status)}]{workflow.status.upper()}[/{status_style(workflow.status)}]"
            duration = format_duration(workflow.started_at, workflow.completed_at)

            content = f"""[bold]Status:[/bold] {status_text}
[bold]Workflow:[/bold] {workflow.workflow_name}
[bold]Run ID:[/bold] {workflow.run_id}
[bold]Duration:[/bold] {duration}

[bold]Started:[/bold] {workflow.started_at or 'Not started'}
[bold]Completed:[/bold] {workflow.completed_at or 'Not completed'}"""

            if workflow.resource_id:
                content += f"\n[bold]Resource:[/bold] {resource_name or workflow.resource_id}"

            if workflow.game_id:
                content += f"\n[bold]Game ID:[/bold] {workflow.game_id}"

            console.print(Panel(content, title=f"Workflow: {workflow.id}"))

            if workflow.error:
                console.print(f"\n[bold red]Error:[/bold red] {workflow.error}")
                if workflow.error_code:
                    console.print(f"[dim]Error code: {workflow.error_code}[/dim]")

            if workflow.input_data:
                console.print("\n[bold]Input Data:[/bold]")
                for key, value in workflow.input_data.items():
                    console.print(f"  {key}: {value}")

            if workflow.output_data:
                console.print("\n[bold]Output Data:[/bold]")
                for key, value in workflow.output_data.items():
                    val_str = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                    console.print(f"  {key}: {val_str}")

    asyncio.run(_show())


@app.command("retry")
def retry_workflow(
    workflow_id: str = typer.Argument(..., help="Workflow ID to retry"),
):
    """Retry a failed workflow."""

    async def _retry():
        async with get_session_context() as session:
            # Find workflow
            stmt = select(WorkflowRun).where(WorkflowRun.id.startswith(workflow_id))
            result = await session.execute(stmt)
            workflow = result.scalar_one_or_none()

            if not workflow:
                stmt = select(WorkflowRun).where(WorkflowRun.id == workflow_id)
                result = await session.execute(stmt)
                workflow = result.scalar_one_or_none()

            if not workflow:
                console.print(f"[red]Error:[/red] Workflow '{workflow_id}' not found")
                raise typer.Exit(1)

            if workflow.status != "failed":
                console.print(f"[yellow]Warning:[/yellow] Workflow is not failed (status: {workflow.status})")
                if not typer.confirm("Retry anyway?"):
                    raise typer.Exit(0)

            # Get input data for retry
            input_data = workflow.input_data or {}

            # For resource processing workflows, re-enqueue the resource
            if workflow.workflow_name == "process_resource" and workflow.resource_id:
                await queue.enqueue(
                    "process_resource",
                    resource_id=workflow.resource_id,
                    start_stage=input_data.get("start_stage"),
                    timeout=PIPELINE_TIMEOUT_SECONDS,
                )
                console.print(f"[green]Queued retry[/green] for resource {workflow.resource_id}")
            else:
                console.print(f"[red]Error:[/red] Cannot retry workflow type: {workflow.workflow_name}")
                raise typer.Exit(1)

    asyncio.run(_retry())


@app.command("cancel")
def cancel_workflow(
    workflow_id: str = typer.Argument(..., help="Workflow ID to cancel"),
):
    """Cancel a running or queued workflow."""

    async def _cancel():
        async with get_session_context() as session:
            stmt = select(WorkflowRun).where(WorkflowRun.id.startswith(workflow_id))
            result = await session.execute(stmt)
            workflow = result.scalar_one_or_none()

            if not workflow:
                stmt = select(WorkflowRun).where(WorkflowRun.id == workflow_id)
                result = await session.execute(stmt)
                workflow = result.scalar_one_or_none()

            if not workflow:
                console.print(f"[red]Error:[/red] Workflow '{workflow_id}' not found")
                raise typer.Exit(1)

            if workflow.status not in ("queued", "running"):
                console.print(f"[yellow]Warning:[/yellow] Workflow is not active (status: {workflow.status})")
                raise typer.Exit(1)

            workflow.status = "cancelled"
            await session.commit()

            console.print(f"[green]Cancelled[/green] workflow {workflow.id}")

    asyncio.run(_cancel())
