"""Attachment model for images extracted from documents."""

from enum import Enum
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from gamegame.models.base import TimestampMixin, generate_nanoid


class AttachmentType(str, Enum):
    """Type of attachment."""

    IMAGE = "image"


class DetectedType(str, Enum):
    """AI-detected image type."""

    DIAGRAM = "diagram"
    TABLE = "table"
    PHOTO = "photo"
    ICON = "icon"
    DECORATIVE = "decorative"


class QualityRating(str, Enum):
    """Image quality rating."""

    GOOD = "good"
    BAD = "bad"


class Attachment(TimestampMixin, SQLModel, table=True):
    """Image or other attachment extracted from documents."""

    __tablename__ = "attachments"

    id: str = Field(default_factory=generate_nanoid, primary_key=True, max_length=21)
    game_id: str = Field(foreign_key="games.id", index=True, ondelete="CASCADE", max_length=21)
    resource_id: str = Field(foreign_key="resources.id", index=True, ondelete="CASCADE", max_length=21)

    type: AttachmentType = Field(default=AttachmentType.IMAGE)
    mime_type: str = Field(max_length=100)

    # Storage (NOT NULL to match TypeScript)
    blob_key: str = Field(max_length=500)
    url: str = Field(max_length=2048)
    original_filename: str | None = Field(default=None, max_length=255)
    content_hash: str | None = Field(default=None, max_length=64, index=True, description="SHA256 hash of image bytes")

    # Location
    page_number: int | None = Field(default=None)
    bbox: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB),
        description="Bounding box coordinates [x1, y1, x2, y2]",
    )

    # Dimensions
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)

    # Content
    caption: str | None = Field(default=None, description="Text caption from document")

    # AI analysis
    description: str | None = Field(default=None, description="AI-generated description")
    detected_type: DetectedType | None = Field(default=None)
    is_good_quality: QualityRating | None = Field(default=None)
    is_relevant: bool | None = Field(default=None, description="True if useful, False if decorative")
    ocr_text: str | None = Field(default=None, description="Text extracted from image")


class AttachmentCreate(SQLModel):
    """Schema for creating an attachment."""

    game_id: str
    resource_id: str
    type: AttachmentType = AttachmentType.IMAGE
    mime_type: str
    blob_key: str
    url: str
    original_filename: str | None = None
    page_number: int | None = None
    bbox: dict[str, Any] | None = None
    width: int | None = None
    height: int | None = None
    caption: str | None = None


class AttachmentRead(SQLModel):
    """Schema for reading an attachment."""

    id: str
    game_id: str
    resource_id: str
    type: AttachmentType
    mime_type: str
    url: str
    original_filename: str | None = None
    page_number: int | None
    bbox: dict[str, Any] | None = None
    width: int | None = None
    height: int | None = None
    caption: str | None = None
    description: str | None
    detected_type: DetectedType | None
    is_good_quality: QualityRating | None
    is_relevant: bool | None = None
    ocr_text: str | None = None


class AttachmentUpdate(SQLModel):
    """Schema for updating an attachment."""

    description: str | None = None
    detected_type: DetectedType | None = None
    is_good_quality: QualityRating | None = None
