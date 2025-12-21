"""User model."""

from sqlmodel import Field, SQLModel

from gamegame.models.base import TimestampMixin, generate_nanoid


class User(TimestampMixin, SQLModel, table=True):
    """User account model."""

    __tablename__ = "users"

    id: str = Field(default_factory=generate_nanoid, primary_key=True, max_length=21)
    email: str = Field(unique=True, index=True, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    is_admin: bool = Field(default=False)


class UserCreate(SQLModel):
    """Schema for creating a user."""

    email: str
    name: str | None = None
    is_admin: bool = False


class UserRead(SQLModel):
    """Schema for reading a user."""

    id: str
    email: str
    name: str | None
    is_admin: bool
