"""Database management CLI commands."""

import subprocess
import sys

import typer
from rich.console import Console

console = Console()
app = typer.Typer(help="Database management commands")


@app.command("migrate")
def migrate(
    revision: str = typer.Argument("head", help="Target revision (default: head)"),
):
    """Run database migrations to the specified revision."""
    console.print(f"[dim]Running migrations to {revision}...[/dim]")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        check=False, capture_output=False,
    )

    if result.returncode == 0:
        console.print("[green]Migrations complete![/green]")
    else:
        console.print("[red]Migration failed![/red]")
        raise typer.Exit(1)


@app.command("rollback")
def rollback(
    revision: str = typer.Argument("-1", help="Target revision (default: -1 for one step back)"),
):
    """Rollback database migrations."""
    console.print(f"[dim]Rolling back to {revision}...[/dim]")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        check=False, capture_output=False,
    )

    if result.returncode == 0:
        console.print("[green]Rollback complete![/green]")
    else:
        console.print("[red]Rollback failed![/red]")
        raise typer.Exit(1)


@app.command("current")
def current():
    """Show current database revision."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        check=False, capture_output=False,
    )


@app.command("history")
def history(
    limit: int = typer.Option(10, "--limit", "-l", help="Number of revisions to show"),
):
    """Show migration history."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "history", f"-r-{limit}:"],
        check=False, capture_output=False,
    )


@app.command("reset")
def reset(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Reset database (drop all tables and re-migrate).

    WARNING: This will delete all data!
    """
    if not force:
        console.print("[bold red]WARNING:[/bold red] This will delete ALL data in the database!")
        if not typer.confirm("Are you sure you want to continue?"):
            console.print("[dim]Cancelled[/dim]")
            raise typer.Exit(0)

    console.print("[dim]Dropping all tables...[/dim]")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        check=False, capture_output=False,
    )

    if result.returncode != 0:
        console.print("[red]Failed to drop tables![/red]")
        raise typer.Exit(1)

    console.print("[dim]Re-running migrations...[/dim]")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False, capture_output=False,
    )

    if result.returncode == 0:
        console.print("[green]Database reset complete![/green]")
    else:
        console.print("[red]Migration failed![/red]")
        raise typer.Exit(1)


@app.command("create-migration")
def create_migration(
    message: str = typer.Argument(..., help="Migration message"),
    autogenerate: bool = typer.Option(True, "--autogenerate/--no-autogenerate", help="Auto-detect model changes"),
):
    """Create a new migration."""
    console.print(f"[dim]Creating migration: {message}[/dim]")

    args = [sys.executable, "-m", "alembic", "revision", "-m", message]
    if autogenerate:
        args.append("--autogenerate")

    result = subprocess.run(args, check=False, capture_output=False)

    if result.returncode == 0:
        console.print("[green]Migration created![/green]")
    else:
        console.print("[red]Failed to create migration![/red]")
        raise typer.Exit(1)
