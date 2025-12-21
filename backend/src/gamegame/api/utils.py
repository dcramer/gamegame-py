"""Shared API utilities."""

import re

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gamegame.models import Game


def slugify(name: str, year: int | None = None) -> str:
    """Convert name and optional year to URL-friendly slug.

    Examples:
        slugify("Catan") -> "catan"
        slugify("Catan", 1995) -> "catan-1995"
    """
    text = name.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    if year:
        text = f"{text}-{year}"
    return text


async def get_game_by_id_or_slug(game_id_or_slug: str, session: AsyncSession) -> Game:
    """Get a game by ID or slug.

    Args:
        game_id_or_slug: Game ID or URL slug
        session: Database session

    Returns:
        Game model instance

    Raises:
        HTTPException: 404 if game not found
    """
    # Try ID first, then slug
    stmt = select(Game).where(Game.id == game_id_or_slug)
    result = await session.execute(stmt)
    game = result.scalar_one_or_none()

    if not game:
        stmt = select(Game).where(Game.slug == game_id_or_slug)
        result = await session.execute(stmt)
        game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    return game
