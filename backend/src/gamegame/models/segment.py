"""Segment model for document sections."""

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from gamegame.models.base import TimestampMixin, generate_nanoid


class Segment(TimestampMixin, SQLModel, table=True):
    """Segment/section of a resource for parent document retrieval.

    Represents a logical section of a document (e.g., "Setup", "Combat", "Victory Conditions").
    Fragments are linked to segments for context expansion during RAG.
    """

    __tablename__ = "segments"

    id: str = Field(default_factory=generate_nanoid, primary_key=True, max_length=21)
    resource_id: str = Field(foreign_key="resources.id", index=True, ondelete="CASCADE", max_length=21)
    game_id: str = Field(foreign_key="games.id", index=True, ondelete="CASCADE", max_length=21)

    # Segment identity
    title: str = Field(max_length=255, description="Segment title (e.g., 'Board Preparation')")
    hierarchy_path: str = Field(max_length=512, description="Full path (e.g., 'Setup > Board Preparation')")
    level: int = Field(default=1, description="Heading level (1-6)")
    order_index: int = Field(default=0, description="Order within resource")

    # Content
    content: str = Field(description="Full segment content as markdown")

    # Page annotations for citations
    page_start: int | None = Field(default=None, description="First page of segment")
    page_end: int | None = Field(default=None, description="Last page of segment")

    # Stats
    word_count: int | None = Field(default=None)
    char_count: int | None = Field(default=None)

    # Hierarchy (for tree traversal if needed)
    parent_id: str | None = Field(
        default=None,
        foreign_key="segments.id",
        max_length=21,
        ondelete="SET NULL",
        description="Parent segment ID for nested sections",
    )

    __table_args__ = (
        # Ensure unique ordering within each resource
        UniqueConstraint("resource_id", "order_index", name="uq_segments_resource_order"),
    )


class SegmentRead(SQLModel):
    """Schema for reading a segment."""

    id: str
    resource_id: str
    game_id: str
    title: str
    hierarchy_path: str
    level: int
    order_index: int
    content: str
    page_start: int | None
    page_end: int | None
    word_count: int | None
    char_count: int | None
    parent_id: str | None
