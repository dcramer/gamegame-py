"""Search endpoints for RAG retrieval."""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import select

from gamegame.api.deps import CurrentUserOptional, SessionDep
from gamegame.models import Game
from gamegame.services.search import SearchResult, search_service

router = APIRouter()


class ImageMetadataRead(BaseModel):
    """Image metadata from a fragment."""

    id: str
    url: str
    bbox: list[float] | None = None
    caption: str | None = None
    description: str | None = None
    detected_type: str | None = None
    ocr_text: str | None = None
    is_relevant: bool | None = None


class SearchResultRead(BaseModel):
    """A single search result."""

    fragment_id: str
    content: str
    page_number: int | None
    section: str | None
    resource_id: str
    resource_name: str
    game_id: str
    score: float
    images: list[ImageMetadataRead] | None = None
    searchable_content: str | None = None


class SearchResponseRead(BaseModel):
    """Search response."""

    results: list[SearchResultRead]
    query: str
    game_id: str | None
    total: int


def result_to_read(result: SearchResult) -> SearchResultRead:
    """Convert SearchResult to API response."""
    images = None
    if result.images:
        images = [
            ImageMetadataRead(
                id=img.id,
                url=img.url,
                bbox=img.bbox,
                caption=img.caption,
                description=img.description,
                detected_type=img.detected_type,
                ocr_text=img.ocr_text,
                is_relevant=img.is_relevant,
            )
            for img in result.images
        ]

    return SearchResultRead(
        fragment_id=result.fragment_id,
        content=result.content,
        page_number=result.page_number,
        section=result.section,
        resource_id=result.resource_id,
        resource_name=result.resource_name,
        game_id=result.game_id,
        score=result.score,
        images=images,
        searchable_content=result.searchable_content,
    )


@router.get("", response_model=SearchResponseRead)
async def search(
    session: SessionDep,
    _user: CurrentUserOptional,
    q: str = Query(..., min_length=1, description="Search query"),
    game_id: str | None = Query(None, description="Filter to specific game ID"),
    limit: int = Query(5, ge=1, le=20, description="Max results to return"),
):
    """Search for relevant content across game resources.

    Performs hybrid search using:
    - Vector similarity on content embeddings
    - Vector similarity on HyDE question embeddings
    - Full-text search with PostgreSQL tsvector

    Results are combined using Reciprocal Rank Fusion (RRF).
    """
    # Validate game_id if provided
    if game_id:
        stmt = select(Game).where(Game.id == game_id)
        result = await session.execute(stmt)
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found",
            )

    # Perform search
    response = await search_service.search(
        session=session,
        query=q,
        game_id=game_id,
        limit=limit,
    )

    return SearchResponseRead(
        results=[result_to_read(r) for r in response.results],
        query=response.query,
        game_id=response.game_id,
        total=len(response.results),
    )


@router.get("/games/{game_id_or_slug}", response_model=SearchResponseRead)
async def search_game(
    game_id_or_slug: str,
    session: SessionDep,
    _user: CurrentUserOptional,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(5, ge=1, le=20, description="Max results to return"),
):
    """Search within a specific game's resources.

    Game can be specified by ID or slug.
    """
    # Resolve game ID from ID or slug - try ID first, then slug
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

    # Perform search
    response = await search_service.search(
        session=session,
        query=q,
        game_id=game.id,
        limit=limit,
    )

    return SearchResponseRead(
        results=[result_to_read(r) for r in response.results],
        query=response.query,
        game_id=game.id,
        total=len(response.results),
    )
