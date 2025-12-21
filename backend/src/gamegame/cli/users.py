"""User management CLI commands."""

import asyncio
from datetime import UTC, datetime, timedelta
from secrets import token_hex

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from gamegame.config import settings
from gamegame.database import get_session_context
from gamegame.models import User, VerificationToken

console = Console()
app = typer.Typer(help="User management commands")


@app.command("list")
def list_users():
    """List all users."""

    async def _list():
        async with get_session_context() as session:
            stmt = select(User).order_by(User.email)
            result = await session.execute(stmt)
            users = result.scalars().all()

            table = Table(title="Users")
            table.add_column("ID", style="cyan")
            table.add_column("Email", style="green")
            table.add_column("Admin", style="magenta")
            table.add_column("Created", style="dim")

            for user in users:
                admin_str = "[green]Yes[/green]" if user.is_admin else "No"
                created = user.created_at.strftime("%Y-%m-%d") if user.created_at else "-"
                table.add_row(str(user.id), user.email, admin_str, created)

            console.print(table)

    asyncio.run(_list())


@app.command("create")
def create_user(
    email: str = typer.Argument(..., help="User email"),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name"),
    admin: bool = typer.Option(False, "--admin", help="Make user an admin"),
):
    """Create a new user."""

    async def _create():
        async with get_session_context() as session:
            # Check if user exists
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                console.print(f"[red]Error:[/red] User {email} already exists")
                raise typer.Exit(1)

            user = User(email=email, name=name, is_admin=admin)
            session.add(user)
            await session.commit()
            name_str = f" ({name})" if name else ""
            console.print(f"[green]Created user:[/green] {email}{name_str} (admin={admin})")

    asyncio.run(_create())


@app.command("grant-admin")
def grant_admin(email: str = typer.Argument(..., help="User email")):
    """Grant admin privileges to a user."""

    async def _grant():
        async with get_session_context() as session:
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                console.print(f"[red]Error:[/red] User {email} not found")
                raise typer.Exit(1)

            if user.is_admin:
                console.print(f"[yellow]Warning:[/yellow] User {email} is already an admin")
                return

            user.is_admin = True
            await session.commit()
            console.print(f"[green]Granted admin to:[/green] {email}")

    asyncio.run(_grant())


@app.command("login-url")
def login_url(email: str = typer.Argument(..., help="User email")):
    """Generate a magic link login URL for a user."""

    async def _generate():
        async with get_session_context() as session:
            # Check if user exists
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                console.print(f"[red]Error:[/red] User {email} not found")
                raise typer.Exit(1)

            # Generate token
            token = token_hex(32)
            expires = datetime.now(UTC) + timedelta(minutes=settings.magic_link_expiration_minutes)

            verification = VerificationToken(
                identifier=email,
                token=token,
                expires=expires,
            )
            session.add(verification)
            await session.commit()

            console.print(f"[green]Login URL:[/green] /auth/verify?token={token}")
            console.print(f"[dim]Expires: {expires}[/dim]")

    asyncio.run(_generate())
