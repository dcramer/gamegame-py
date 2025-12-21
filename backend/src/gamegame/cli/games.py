"""Game management CLI commands."""

import asyncio

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import func, select

from gamegame.api.utils import slugify
from gamegame.database import get_session_context
from gamegame.models import Game, Resource
from gamegame.services.bgg import fetch_game_info

console = Console()
app = typer.Typer(help="Game management commands")


@app.command("list")
def list_games():
    """List all games with resource counts."""

    async def _list():
        async with get_session_context() as session:
            # Get games with resource counts
            stmt = (
                select(Game, func.count(Resource.id).label("resource_count"))
                .outerjoin(Resource, Resource.game_id == Game.id)
                .group_by(Game.id)
                .order_by(Game.name)
            )
            result = await session.execute(stmt)
            rows = result.all()

            table = Table(title="Games")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Slug", style="yellow")
            table.add_column("Year", style="magenta")
            table.add_column("Resources", style="blue", justify="right")
            table.add_column("BGG ID", style="dim")

            for game, resource_count in rows:
                table.add_row(
                    str(game.id),
                    game.name,
                    game.slug,
                    str(game.year or "-"),
                    str(resource_count),
                    str(game.bgg_id or "-"),
                )

            console.print(table)

    asyncio.run(_list())


@app.command("create")
def create_game(
    name: str = typer.Argument(..., help="Game name"),
    bgg_id: int | None = typer.Option(None, "--bgg-id", help="BoardGameGeek ID to import metadata"),
    year: int | None = typer.Option(None, "--year", help="Release year"),
    description: str | None = typer.Option(None, "--description", help="Game description"),
):
    """Create a new game with optional BGG integration."""

    async def _create():
        async with get_session_context() as session:
            game_year = year
            game_description = description
            image_url = None
            bgg_url = None

            # If BGG ID provided, fetch metadata
            if bgg_id:
                console.print(f"[dim]Fetching metadata from BoardGameGeek (ID: {bgg_id})...[/dim]")
                info = await fetch_game_info(bgg_id, session)

                if info:
                    # Use BGG data as defaults if not provided
                    if game_year is None:
                        game_year = info.year
                    if game_description is None:
                        game_description = info.description
                    image_url = info.image_url
                    bgg_url = f"https://boardgamegeek.com/boardgame/{bgg_id}"
                    console.print(f"[green]Found:[/green] {info.name} ({info.year})")
                else:
                    console.print(f"[yellow]Warning:[/yellow] Could not fetch BGG data for ID {bgg_id}")

            # Generate slug
            slug = slugify(name, game_year)

            # Check for duplicate slug
            stmt = select(Game).where(Game.slug == slug)
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                console.print(f"[red]Error:[/red] Game with slug '{slug}' already exists")
                raise typer.Exit(1)

            # Check for duplicate BGG ID
            if bgg_id:
                stmt = select(Game).where(Game.bgg_id == bgg_id)
                result = await session.execute(stmt)
                if result.scalar_one_or_none():
                    console.print(f"[red]Error:[/red] Game with BGG ID {bgg_id} already exists")
                    raise typer.Exit(1)

            # Create game
            game = Game(
                name=name,
                slug=slug,
                year=game_year,
                description=game_description,
                image_url=image_url,
                bgg_id=bgg_id,
                bgg_url=bgg_url,
            )
            session.add(game)
            await session.commit()

            console.print(f"[green]Created game:[/green] {name}")
            console.print(f"  ID: {game.id}")
            console.print(f"  Slug: {slug}")
            if game_year:
                console.print(f"  Year: {game_year}")
            if bgg_id:
                console.print(f"  BGG ID: {bgg_id}")

    asyncio.run(_create())


@app.command("show")
def show_game(
    game_id_or_slug: str = typer.Argument(..., help="Game ID or slug"),
):
    """Show details for a game."""

    async def _show():
        async with get_session_context() as session:
            # Try ID first, then slug
            stmt = select(Game).where(Game.id == game_id_or_slug)
            result = await session.execute(stmt)
            game = result.scalar_one_or_none()

            if not game:
                stmt = select(Game).where(Game.slug == game_id_or_slug)
                result = await session.execute(stmt)
                game = result.scalar_one_or_none()

            if not game:
                console.print(f"[red]Error:[/red] Game '{game_id_or_slug}' not found")
                raise typer.Exit(1)

            # Get resource count
            stmt = select(func.count(Resource.id)).where(Resource.game_id == game.id)
            result = await session.execute(stmt)
            resource_count = result.scalar() or 0

            console.print(f"[bold]{game.name}[/bold]")
            console.print(f"  ID: [cyan]{game.id}[/cyan]")
            console.print(f"  Slug: [yellow]{game.slug}[/yellow]")
            console.print(f"  Year: {game.year or '-'}")
            console.print(f"  Resources: [blue]{resource_count}[/blue]")
            if game.bgg_id:
                console.print(f"  BGG ID: {game.bgg_id}")
                console.print(f"  BGG URL: {game.bgg_url}")
            if game.image_url:
                console.print(f"  Image: {game.image_url}")
            if game.description:
                desc = game.description[:200] + "..." if len(game.description) > 200 else game.description
                console.print(f"  Description: {desc}")

    asyncio.run(_show())
