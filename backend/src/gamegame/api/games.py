"""Game CRUD endpoints."""

import re

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from gamegame.api.deps import AdminUser, CurrentUserOptional, SessionDep
from gamegame.api.utils import get_game_by_id_or_slug, slugify
from gamegame.models import Game, Resource
from gamegame.models.game import GameCreate, GameRead, GameUpdate
from gamegame.services.bgg import fetch_game_info

router = APIRouter()


def extract_bgg_id(bgg_url: str | None) -> int | None:
    """Extract BGG ID from a BoardGameGeek URL.

    Examples:
        extract_bgg_id("https://boardgamegeek.com/boardgame/13/catan") -> 13
        extract_bgg_id("https://boardgamegeek.com/boardgame/174430/gloomhaven") -> 174430
    """
    if not bgg_url:
        return None
    match = re.search(r"/boardgame/(\d+)", bgg_url)
    return int(match.group(1)) if match else None


@router.get("", response_model=list[GameRead])
async def list_games(session: SessionDep, _user: CurrentUserOptional):
    """List all games with resource counts."""
    # Query games with resource count subquery
    resource_count_subq = (
        select(Resource.game_id, func.count(Resource.id).label("resource_count"))  # type: ignore[arg-type]
        .group_by(Resource.game_id)
        .subquery()
    )

    stmt = (
        select(Game, func.coalesce(resource_count_subq.c.resource_count, 0).label("resource_count"))
        .outerjoin(resource_count_subq, Game.id == resource_count_subq.c.game_id)  # type: ignore[arg-type]
        .order_by(Game.name)
    )
    result = await session.execute(stmt)
    rows = result.all()

    return [
        GameRead(
            id=game.id,
            name=game.name,
            slug=game.slug,
            year=game.year,
            image_url=game.image_url,
            bgg_id=game.bgg_id,
            bgg_url=game.bgg_url,
            description=game.description,
            resource_count=resource_count,
        )
        for game, resource_count in rows
    ]


async def get_resource_count(session: SessionDep, game_id: str) -> int:
    """Get resource count for a game."""
    stmt = select(func.count(Resource.id)).where(Resource.game_id == game_id)  # type: ignore[arg-type]
    result = await session.execute(stmt)
    return result.scalar() or 0


@router.get("/{game_id_or_slug}", response_model=GameRead)
async def get_game(game_id_or_slug: str, session: SessionDep, _user: CurrentUserOptional):
    """Get a game by ID or slug."""
    game = await get_game_by_id_or_slug(game_id_or_slug, session)
    resource_count = await get_resource_count(session, game.id)

    return GameRead(
        id=game.id,
        name=game.name,
        slug=game.slug,
        year=game.year,
        image_url=game.image_url,
        bgg_id=game.bgg_id,
        bgg_url=game.bgg_url,
        description=game.description,
        resource_count=resource_count,
    )


@router.post("", response_model=GameRead, status_code=status.HTTP_201_CREATED)
async def create_game(game_in: GameCreate, session: SessionDep, _user: AdminUser):
    """Create a new game (admin only)."""
    # Generate slug from name + year if not provided
    slug = game_in.slug or slugify(game_in.name, game_in.year)

    # Check for duplicate slug
    stmt = select(Game).where(Game.slug == slug)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Game with slug '{slug}' already exists",
        )

    # Extract BGG ID from URL if not explicitly provided
    bgg_id = game_in.bgg_id or extract_bgg_id(game_in.bgg_url)

    # Check for duplicate BGG ID if we have one
    if bgg_id:
        stmt = select(Game).where(Game.bgg_id == bgg_id)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Game with BGG ID {bgg_id} already exists",
            )

    game = Game(
        name=game_in.name,
        slug=slug,
        year=game_in.year,
        image_url=game_in.image_url,
        bgg_id=bgg_id,
        bgg_url=game_in.bgg_url,
        description=game_in.description,
    )
    session.add(game)
    await session.commit()
    await session.refresh(game)

    return GameRead(
        id=game.id,
        name=game.name,
        slug=game.slug,
        year=game.year,
        image_url=game.image_url,
        bgg_id=game.bgg_id,
        bgg_url=game.bgg_url,
        description=game.description,
        resource_count=0,
    )


@router.patch("/{game_id}", response_model=GameRead)
async def update_game(game_id: str, game_in: GameUpdate, session: SessionDep, _user: AdminUser):
    """Update a game (admin only)."""
    stmt = select(Game).where(Game.id == game_id)
    result = await session.execute(stmt)
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    update_data = game_in.model_dump(exclude_unset=True)

    # Regenerate slug if name or year changes (and slug not explicitly provided)
    if ("name" in update_data or "year" in update_data) and "slug" not in update_data:
        new_name = update_data.get("name", game.name)
        new_year = update_data.get("year", game.year)
        update_data["slug"] = slugify(new_name, new_year)

    # Check for duplicate slug if slug is changing
    if "slug" in update_data and update_data["slug"] != game.slug:
        stmt = select(Game).where(Game.slug == update_data["slug"], Game.id != game_id)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Game with slug '{update_data['slug']}' already exists",
            )

    # Extract BGG ID from URL if URL is provided but ID is not
    if "bgg_url" in update_data and "bgg_id" not in update_data:
        extracted_id = extract_bgg_id(update_data["bgg_url"])
        if extracted_id:
            update_data["bgg_id"] = extracted_id

    # Update fields
    for field, value in update_data.items():
        setattr(game, field, value)

    await session.commit()
    await session.refresh(game)

    # Get resource count
    resource_count_stmt = select(func.count(Resource.id)).where(Resource.game_id == game_id)  # type: ignore[arg-type]
    resource_count_result = await session.execute(resource_count_stmt)
    resource_count = resource_count_result.scalar() or 0

    return GameRead(
        id=game.id,
        name=game.name,
        slug=game.slug,
        year=game.year,
        image_url=game.image_url,
        bgg_id=game.bgg_id,
        bgg_url=game.bgg_url,
        description=game.description,
        resource_count=resource_count,
    )


@router.delete("/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game(game_id: str, session: SessionDep, _user: AdminUser):
    """Delete a game (admin only)."""
    stmt = select(Game).where(Game.id == game_id)
    result = await session.execute(stmt)
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    await session.delete(game)
    await session.commit()


class BGGInfoResponse(BaseModel):
    """Response for BGG info lookup."""

    bgg_id: int
    name: str
    year: int | None
    image_url: str | None
    thumbnail_url: str | None
    description: str | None
    min_players: int | None
    max_players: int | None
    playing_time: int | None


@router.get("/bgg/{bgg_id}", response_model=BGGInfoResponse)
async def get_bgg_info(bgg_id: int, _user: CurrentUserOptional):
    """Fetch game information from BoardGameGeek.

    This endpoint fetches metadata from BGG without modifying any local data.
    Use POST /games/{game_id}/sync-bgg to apply the metadata to a game.
    """
    info = await fetch_game_info(bgg_id)

    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game with BGG ID {bgg_id} not found on BoardGameGeek",
        )

    return BGGInfoResponse(
        bgg_id=info.bgg_id,
        name=info.name,
        year=info.year,
        image_url=info.image_url,
        thumbnail_url=info.thumbnail_url,
        description=info.description,
        min_players=info.min_players,
        max_players=info.max_players,
        playing_time=info.playing_time,
    )


@router.post("/{game_id}/sync-bgg", response_model=GameRead)
async def sync_game_with_bgg(game_id: str, session: SessionDep, _user: AdminUser):
    """Sync a game's metadata with BoardGameGeek (admin only).

    Fetches the latest metadata from BGG and updates the game's:
    - year
    - image_url
    - description

    The game must have a bgg_id set.
    """
    stmt = select(Game).where(Game.id == game_id)
    result = await session.execute(stmt)
    game = result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    if not game.bgg_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Game does not have a BGG ID set",
        )

    info = await fetch_game_info(game.bgg_id)

    if not info:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch game info from BoardGameGeek",
        )

    # Update game with BGG metadata
    game.year = info.year
    game.image_url = info.image_url
    if info.description:
        game.description = info.description

    await session.commit()
    await session.refresh(game)

    # Get resource count
    resource_count_stmt = select(func.count(Resource.id)).where(Resource.game_id == game_id)  # type: ignore[arg-type]
    resource_count_result = await session.execute(resource_count_stmt)
    resource_count = resource_count_result.scalar() or 0

    return GameRead(
        id=game.id,
        name=game.name,
        slug=game.slug,
        year=game.year,
        image_url=game.image_url,
        bgg_id=game.bgg_id,
        bgg_url=game.bgg_url,
        description=game.description,
        resource_count=resource_count,
    )
