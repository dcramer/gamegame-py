"""Search testing CLI commands."""

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlmodel import select

from gamegame.database import get_session_context
from gamegame.models import Game
from gamegame.services.search import SearchService

console = Console()
app = typer.Typer(help="Search testing commands")


@app.command("test")
def test_search(
    query: str = typer.Argument(..., help="Search query"),
    game: Annotated[str | None, typer.Option("--game", "-g", help="Filter by game ID or slug")] = None,
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum results"),
    no_rerank: bool = typer.Option(False, "--no-rerank", help="Disable LLM reranking"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed results"),
):
    """Test search locally without HTTP.

    Useful for debugging search quality and checking embeddings.
    """

    async def _search():
        async with get_session_context() as session:
            game_id = None

            # Resolve game
            if game:
                stmt = select(Game).where((Game.id == game) | (Game.slug == game))
                result = await session.execute(stmt)
                game_obj = result.scalar_one_or_none()
                if not game_obj:
                    console.print(f"[red]Error:[/red] Game '{game}' not found")
                    raise typer.Exit(1)
                game_id = game_obj.id
                console.print(f"[dim]Searching in game: {game_obj.name}[/dim]")

            console.print(f"[dim]Query: \"{query}\"[/dim]")
            if no_rerank:
                console.print("[dim]Reranking: disabled[/dim]")
            console.print()

            search_service = SearchService()
            response = await search_service.search(
                session=session,
                query=query,
                game_id=game_id,
                limit=limit,
                enable_reranking=not no_rerank,
            )

            if not response.results:
                console.print("[yellow]No results found[/yellow]")
                return

            # Show answer types if detected
            if response.answer_types:
                types_str = ", ".join(response.answer_types)
                console.print(f"[bold]Answer Types:[/bold] {types_str}")
                console.print()

            # Results table
            table = Table(title=f"Search Results ({len(response.results)} found)")
            table.add_column("#", style="dim", width=3)
            table.add_column("Score", style="cyan", justify="right", width=6)
            table.add_column("Resource", style="green")
            table.add_column("Page", justify="right", width=5)
            table.add_column("Section", style="yellow")

            for i, result in enumerate(response.results, 1):
                score = f"{result.score:.3f}" if result.score else "-"
                page = str(result.page_number) if result.page_number else "-"
                section = result.section[:30] + "..." if result.section and len(result.section) > 30 else (result.section or "-")
                table.add_row(
                    str(i),
                    score,
                    result.resource_name[:25] + "..." if len(result.resource_name) > 25 else result.resource_name,
                    page,
                    section,
                )

            console.print(table)

            # Show verbose content
            if verbose:
                console.print()
                for i, result in enumerate(response.results, 1):
                    content = result.content[:500] + "..." if len(result.content) > 500 else result.content
                    console.print(Panel(
                        content,
                        title=f"Result {i}: {result.resource_name}",
                        border_style="dim",
                    ))

    asyncio.run(_search())


@app.command("types")
def detect_types(
    query: str = typer.Argument(..., help="Query to analyze"),
):
    """Detect answer types for a query.

    Shows what type of content the search expects to find.
    """

    async def _detect():
        from gamegame.services.search import detect_query_answer_types

        console.print(f"[dim]Analyzing: \"{query}\"[/dim]")
        console.print()

        types = await detect_query_answer_types(query)

        if types:
            console.print("[bold]Detected Answer Types:[/bold]")
            for t in types:
                console.print(f"  - {t}")
        else:
            console.print("[yellow]No specific answer types detected[/yellow]")

    asyncio.run(_detect())
