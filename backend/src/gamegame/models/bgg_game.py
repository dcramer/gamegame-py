"""BGG game cache model for storing BoardGameGeek API responses."""

from datetime import datetime

from sqlalchemy import JSON, Column, Index
from sqlmodel import Field, SQLModel

# Cache freshness in days
CACHE_FRESHNESS_DAYS = 7


class BGGGame(SQLModel, table=True):
    """Cached BoardGameGeek game data.

    Used to avoid excessive API calls to BGG by caching game details.
    Cache entries are considered stale after CACHE_FRESHNESS_DAYS.
    """

    __tablename__ = "bgg_games"
    __table_args__ = (Index("idx_bgg_games_name", "name"),)

    # BGG game ID as primary key (not a nanoid since it's from BGG)
    id: int = Field(primary_key=True, description="BoardGameGeek game ID")

    # Basic info
    name: str = Field(index=True)
    year_published: int | None = Field(default=None)

    # Player info
    min_players: int | None = Field(default=None)
    max_players: int | None = Field(default=None)
    playing_time: int | None = Field(default=None)

    # Images
    thumbnail_url: str | None = Field(default=None)
    image_url: str | None = Field(default=None)

    # Description
    description: str | None = Field(default=None)

    # Metadata (stored as JSON arrays)
    publishers: list[str] | None = Field(default=None, sa_column=Column(JSON))
    designers: list[str] | None = Field(default=None, sa_column=Column(JSON))
    categories: list[str] | None = Field(default=None, sa_column=Column(JSON))
    mechanics: list[str] | None = Field(default=None, sa_column=Column(JSON))

    # Cache timestamp (Unix timestamp in milliseconds for TypeScript parity)
    cached_at: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000),
        description="Unix timestamp in milliseconds when cached",
    )


def is_cache_stale(cached_at: int) -> bool:
    """Check if a cached entry is stale.

    Args:
        cached_at: Unix timestamp in milliseconds

    Returns:
        True if cache is older than CACHE_FRESHNESS_DAYS
    """
    now_ms = int(datetime.now().timestamp() * 1000)
    age_ms = now_ms - cached_at
    age_days = age_ms / (1000 * 60 * 60 * 24)
    return age_days > CACHE_FRESHNESS_DAYS


class BGGGameRead(SQLModel):
    """Schema for reading a cached BGG game."""

    id: int
    name: str
    year_published: int | None
    min_players: int | None
    max_players: int | None
    playing_time: int | None
    thumbnail_url: str | None
    image_url: str | None
    description: str | None
    publishers: list[str] | None
    designers: list[str] | None
    categories: list[str] | None
    mechanics: list[str] | None
    cached_at: int
