"""BoardGameGeek API endpoints."""

import io
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from PIL import Image
from pydantic import BaseModel
from sqlmodel import select

from gamegame.api.deps import AdminUser, SessionDep
from gamegame.api.utils import slugify
from gamegame.models import Game
from gamegame.services.bgg import (
    download_image,
    fetch_game_info,
    search_games_basic,
)
from gamegame.services.storage import storage

router = APIRouter()

# Max image dimensions for WebP conversion
MAX_IMAGE_WIDTH = 900
MAX_IMAGE_HEIGHT = 600
WEBP_QUALITY = 85


class BGGSearchResultResponse(BaseModel):
    """Search result from BGG with import status."""

    bgg_id: int
    name: str
    year: int | None
    game_type: str
    is_imported: bool
    game_id: str | None = None
    game_slug: str | None = None
    game_image_url: str | None = None


@router.get("/search", response_model=list[BGGSearchResultResponse])
async def search_bgg(
    session: SessionDep,
    _user: AdminUser,
    q: Annotated[str, Query(min_length=2, description="Search query")],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    """Search BoardGameGeek for games (admin only).

    Returns search results with import status indicating if the game
    already exists in the local database.
    """
    # Search BGG
    results = await search_games_basic(q, limit=limit)

    if not results:
        return []

    # Get BGG IDs that are already imported
    bgg_ids = [r.bgg_id for r in results]
    stmt = select(Game).where(Game.bgg_id.in_(bgg_ids))  # type: ignore[union-attr]
    db_result = await session.execute(stmt)
    imported_games = {g.bgg_id: g for g in db_result.scalars()}

    # Build response with import status
    response = []
    for result in results:
        imported_game = imported_games.get(result.bgg_id)
        response.append(
            BGGSearchResultResponse(
                bgg_id=result.bgg_id,
                name=result.name,
                year=result.year,
                game_type=result.game_type,
                is_imported=imported_game is not None,
                game_id=imported_game.id if imported_game else None,
                game_slug=imported_game.slug if imported_game else None,
                game_image_url=imported_game.image_url if imported_game else None,
            )
        )

    return response


class BGGImportResponse(BaseModel):
    """Response for BGG game import."""

    id: str
    name: str
    slug: str
    year: int | None
    image_url: str | None
    bgg_id: int
    bgg_url: str


def convert_to_webp(image_data: bytes) -> bytes:
    """Convert image to WebP format with resizing.

    Args:
        image_data: Original image bytes

    Returns:
        WebP image bytes
    """
    # Open image
    img: Image.Image = Image.open(io.BytesIO(image_data))

    # Convert to RGB if necessary (WebP doesn't support all modes)
    if img.mode in ("RGBA", "LA", "P"):
        # Create white background for transparency
        background: Image.Image = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if too large
    if img.width > MAX_IMAGE_WIDTH or img.height > MAX_IMAGE_HEIGHT:
        img.thumbnail((MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT), Image.Resampling.LANCZOS)

    # Convert to WebP
    output = io.BytesIO()
    img.save(output, format="WEBP", quality=WEBP_QUALITY)
    return output.getvalue()


@router.post("/games/{bgg_id}/import", response_model=BGGImportResponse)
async def import_bgg_game(
    bgg_id: int,
    session: SessionDep,
    _user: AdminUser,
):
    """Import a game from BoardGameGeek (admin only).

    Fetches game details from BGG, downloads and converts the image to WebP,
    and creates a new game record.

    Returns 409 Conflict if the game is already imported.
    """
    # Check if already imported
    stmt = select(Game).where(Game.bgg_id == bgg_id)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Game with BGG ID {bgg_id} is already imported as '{existing.name}'",
        )

    # Fetch game info from BGG
    info = await fetch_game_info(bgg_id)
    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game with BGG ID {bgg_id} not found on BoardGameGeek",
        )

    # Generate slug
    slug = slugify(info.name, info.year)

    # Check for duplicate slug
    slug_stmt = select(Game).where(Game.slug == slug)
    slug_result = await session.execute(slug_stmt)
    if slug_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Game with slug '{slug}' already exists",
        )

    # Download and convert image
    image_url = None
    uploaded_key = None

    if info.image_url:
        image_data = await download_image(info.image_url)
        if image_data:
            try:
                # Convert to WebP
                webp_data = convert_to_webp(image_data)

                # Upload to storage
                image_url, uploaded_key = await storage.upload_file(
                    data=webp_data,
                    prefix="games",
                    extension="webp",
                )
            except Exception:
                # Log error but continue without image
                pass

    # Create game
    bgg_url = f"https://boardgamegeek.com/boardgame/{bgg_id}"
    game = Game(
        name=info.name,
        slug=slug,
        year=info.year,
        image_url=image_url,
        bgg_id=bgg_id,
        bgg_url=bgg_url,
        description=info.description,
    )

    try:
        session.add(game)
        await session.commit()
        await session.refresh(game)
    except Exception as e:
        # Clean up uploaded image on failure
        if uploaded_key:
            await storage.delete_file(uploaded_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create game: {e}",
        ) from e

    return BGGImportResponse(
        id=game.id,
        name=game.name,
        slug=game.slug,
        year=game.year,
        image_url=game.image_url,
        bgg_id=bgg_id,
        bgg_url=bgg_url,
    )


class BGGThumbnailResponse(BaseModel):
    """Response for BGG thumbnail lookup."""

    thumbnail_url: str | None
    cached: bool


@router.get("/games/{bgg_id}/thumbnail", response_model=BGGThumbnailResponse)
async def get_bgg_thumbnail(
    bgg_id: int,
    _user: AdminUser,
):
    """Get thumbnail URL for a BGG game (admin only).

    Returns the thumbnail URL from BoardGameGeek for lazy loading.
    This does not download or store the image.
    """
    # Fetch game info from BGG
    info = await fetch_game_info(bgg_id)

    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game with BGG ID {bgg_id} not found on BoardGameGeek",
        )

    return BGGThumbnailResponse(
        thumbnail_url=info.thumbnail_url,
        cached=False,  # We don't implement caching for now
    )
