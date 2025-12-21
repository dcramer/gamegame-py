"""Base model with common fields and mixins."""

from datetime import UTC, datetime

from nanoid import generate as nanoid_generate
from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel


def generate_nanoid() -> str:
    """Generate a nanoid string ID (21 chars, URL-safe)."""
    return nanoid_generate()


class TimestampMixin(SQLModel):
    """Mixin that adds created_at and updated_at timestamps."""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        description="Timestamp when the record was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
        description="Timestamp when the record was last updated",
    )


class BaseModel(TimestampMixin, SQLModel):
    """Base model with ID and timestamps."""

    id: str = Field(default_factory=generate_nanoid, primary_key=True, max_length=21)
