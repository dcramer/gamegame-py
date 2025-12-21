"""BoardGameGeek CLI commands."""

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from gamegame.api.utils import slugify
from gamegame.database import get_session_context
from gamegame.models import Game
from gamegame.services.bgg import fetch_game_info, search_games_basic

console = Console()
app = typer.Typer(help="BoardGameGeek integration commands")


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum results"),
):
    """Search BoardGameGeek for games."""

    async def _search():
        console.print(f"[dim]Searching BoardGameGeek for '{query}'...[/dim]")

        results = await search_games_basic(query, limit)

        if not results:
            console.print("[yellow]No results found[/yellow]")
            return

        table = Table(title=f"BGG Search: {query}")
        table.add_column("BGG ID", style="cyan", justify="right")
        table.add_column("Name", style="green")
        table.add_column("Year", style="magenta")
        table.add_column("Type", style="dim")

        for result in results:
            table.add_row(
                str(result.bgg_id),
                result.name,
                str(result.year) if result.year else "-",
                result.game_type,
            )

        console.print(table)
        console.print("\n[dim]Use 'gamegame bgg import <BGG_ID>' to import a game[/dim]")

    asyncio.run(_search())


@app.command("info")
def info(
    bgg_id: int = typer.Argument(..., help="BoardGameGeek game ID"),
):
    """Show detailed info for a BGG game."""

    async def _info():
        console.print(f"[dim]Fetching details for BGG ID {bgg_id}...[/dim]")

        async with get_session_context() as session:
            game_info = await fetch_game_info(bgg_id, session)

            if not game_info:
                console.print("[red]Error:[/red] Game not found on BoardGameGeek")
                raise typer.Exit(1)

            console.print(f"\n[bold]{game_info.name}[/bold] ({game_info.year or 'Unknown'})")
            console.print(f"  BGG ID: [cyan]{game_info.bgg_id}[/cyan]")
            console.print(f"  URL: https://boardgamegeek.com/boardgame/{game_info.bgg_id}")

            if game_info.min_players or game_info.max_players:
                players = f"{game_info.min_players or '?'}-{game_info.max_players or '?'}"
                console.print(f"  Players: {players}")

            if game_info.playing_time:
                console.print(f"  Playing Time: {game_info.playing_time} min")

            if game_info.designers:
                console.print(f"  Designers: {', '.join(game_info.designers[:3])}")

            if game_info.publishers:
                console.print(f"  Publishers: {', '.join(game_info.publishers[:3])}")

            if game_info.categories:
                console.print(f"  Categories: {', '.join(game_info.categories[:5])}")

            if game_info.mechanics:
                console.print(f"  Mechanics: {', '.join(game_info.mechanics[:5])}")

            if game_info.description:
                desc = game_info.description[:300] + "..." if len(game_info.description) > 300 else game_info.description
                console.print(f"\n[dim]{desc}[/dim]")

    asyncio.run(_info())


@app.command("import")
def import_game(
    bgg_id: int = typer.Argument(..., help="BoardGameGeek game ID"),
    name: Annotated[str | None, typer.Option("--name", "-n", help="Override game name")] = None,
):
    """Import a game from BoardGameGeek."""

    async def _import():
        async with get_session_context() as session:
            # Check if already imported
            stmt = select(Game).where(Game.bgg_id == bgg_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                console.print(f"[yellow]Game already exists:[/yellow] {existing.name} (ID: {existing.id})")
                raise typer.Exit(1)

            # Fetch from BGG
            console.print("[dim]Fetching game details from BoardGameGeek...[/dim]")
            info = await fetch_game_info(bgg_id, session)

            if not info:
                console.print("[red]Error:[/red] Game not found on BoardGameGeek")
                raise typer.Exit(1)

            # Use provided name or BGG name
            game_name = name or info.name

            # Generate slug
            slug = slugify(game_name, info.year)

            # Check for duplicate slug
            stmt = select(Game).where(Game.slug == slug)
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                console.print(f"[red]Error:[/red] Game with slug '{slug}' already exists")
                raise typer.Exit(1)

            # Create game
            game = Game(
                name=game_name,
                slug=slug,
                year=info.year,
                description=info.description,
                image_url=info.image_url,
                bgg_id=bgg_id,
                bgg_url=f"https://boardgamegeek.com/boardgame/{bgg_id}",
            )
            session.add(game)
            await session.commit()

            console.print(f"[green]Imported:[/green] {game_name}")
            console.print(f"  ID: {game.id}")
            console.print(f"  Slug: {slug}")
            if info.year:
                console.print(f"  Year: {info.year}")
            console.print(f"  BGG ID: {bgg_id}")

    asyncio.run(_import())


@app.command("sync")
def sync_game(
    game_id_or_slug: str = typer.Argument(..., help="Game ID or slug to sync"),
):
    """Sync a game's metadata with BoardGameGeek."""

    async def _sync():
        async with get_session_context() as session:
            # Find game
            stmt = select(Game).where((Game.id == game_id_or_slug) | (Game.slug == game_id_or_slug))
            result = await session.execute(stmt)
            game = result.scalar_one_or_none()

            if not game:
                console.print(f"[red]Error:[/red] Game '{game_id_or_slug}' not found")
                raise typer.Exit(1)

            if not game.bgg_id:
                console.print("[red]Error:[/red] Game has no BGG ID set")
                raise typer.Exit(1)

            console.print(f"[dim]Syncing {game.name} with BGG ID {game.bgg_id}...[/dim]")

            info = await fetch_game_info(game.bgg_id, session, bypass_cache=True)

            if not info:
                console.print("[red]Error:[/red] Could not fetch BGG data")
                raise typer.Exit(1)

            # Update fields
            updated = []
            if info.year and game.year != info.year:
                game.year = info.year
                updated.append("year")
            if info.description and game.description != info.description:
                game.description = info.description
                updated.append("description")
            if info.image_url and game.image_url != info.image_url:
                game.image_url = info.image_url
                updated.append("image_url")

            if updated:
                await session.commit()
                console.print(f"[green]Updated:[/green] {', '.join(updated)}")
            else:
                console.print("[dim]No changes needed[/dim]")

    asyncio.run(_sync())
