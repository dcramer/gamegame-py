"""Game model."""

from sqlmodel import Field, SQLModel

from gamegame.models.base import TimestampMixin, generate_nanoid


class Game(TimestampMixin, SQLModel, table=True):
    """Board game model."""

    __tablename__ = "games"

    id: str = Field(default_factory=generate_nanoid, primary_key=True, max_length=21)
    name: str = Field(max_length=255, index=True)
    slug: str = Field(unique=True, index=True, max_length=255)
    year: int | None = Field(default=None)
    image_url: str | None = Field(default=None, max_length=2048)
    bgg_id: int | None = Field(default=None, unique=True, index=True)
    bgg_url: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None)


class GameCreate(SQLModel):
    """Schema for creating a game."""

    name: str
    slug: str | None = None
    year: int | None = None
    image_url: str | None = None
    bgg_id: int | None = None
    bgg_url: str | None = None
    description: str | None = None


class GameRead(SQLModel):
    """Schema for reading a game."""

    id: str
    name: str
    slug: str
    year: int | None
    image_url: str | None
    bgg_id: int | None
    bgg_url: str | None
    description: str | None
    resource_count: int = 0


class GameUpdate(SQLModel):
    """Schema for updating a game."""

    name: str | None = None
    slug: str | None = None
    year: int | None = None
    image_url: str | None = None
    bgg_id: int | None = None
    bgg_url: str | None = None
    description: str | None = None
