"""Resource model for PDFs and other documents."""

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel

from gamegame.models.base import TimestampMixin, generate_nanoid


class ResourceType(str, Enum):
    """Type of resource."""

    RULEBOOK = "rulebook"
    EXPANSION = "expansion"
    FAQ = "faq"
    ERRATA = "errata"
    REFERENCE = "reference"


class ResourceStatus(str, Enum):
    """Processing status of a resource."""

    READY = "ready"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingStage(str, Enum):
    """Current processing stage."""

    INGEST = "ingest"
    VISION = "vision"
    CLEANUP = "cleanup"
    METADATA = "metadata"  # Name/description generation
    SEGMENT = "segment"  # Segment extraction
    EMBED = "embed"
    FINALIZE = "finalize"


class Resource(TimestampMixin, SQLModel, table=True):
    """Document resource (PDF, rulebook, etc.)."""

    __tablename__ = "resources"

    id: str = Field(default_factory=generate_nanoid, primary_key=True, max_length=21)
    game_id: str = Field(foreign_key="games.id", index=True, ondelete="CASCADE", max_length=21)
    name: str = Field(max_length=255)
    original_filename: str | None = Field(default=None, max_length=255)
    url: str = Field(max_length=2048)
    content: str = Field(default="")  # NOT NULL, matches TypeScript
    version: int = Field(default=0)  # For tracking reprocessing
    description: str | None = Field(default=None, description="LLM-generated description")
    status: ResourceStatus = Field(default=ResourceStatus.READY)  # Default 'ready' matches TS
    resource_type: ResourceType = Field(default=ResourceType.RULEBOOK)
    pdf_extractor: str | None = Field(default="mistral", max_length=50)

    # Attribution
    author: str | None = Field(default=None, max_length=255)
    attribution_url: str | None = Field(default=None, max_length=2048)

    # Classification
    language: str | None = Field(default="en", max_length=10)
    edition: str | None = Field(default=None, max_length=100)
    is_official: bool = Field(default=True)

    # Processing metadata
    processing_stage: ProcessingStage | None = Field(default=None)
    processing_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    current_run_id: str | None = Field(default=None, max_length=255)
    processed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    error_message: str | None = Field(default=None)

    # Stats
    page_count: int | None = Field(default=None)
    image_count: int | None = Field(default=None)
    word_count: int | None = Field(default=None)


class ResourceCreate(SQLModel):
    """Schema for creating a resource."""

    game_id: str
    name: str
    original_filename: str | None = None
    url: str
    resource_type: ResourceType = ResourceType.RULEBOOK


class ResourceRead(SQLModel):
    """Schema for reading a resource."""

    id: str
    game_id: str
    name: str
    original_filename: str | None = None
    url: str
    description: str | None
    status: ResourceStatus
    resource_type: ResourceType
    author: str | None = None
    attribution_url: str | None = None
    language: str | None = None
    edition: str | None = None
    is_official: bool = True
    processing_stage: ProcessingStage | None
    page_count: int | None
    image_count: int | None
    word_count: int | None
    segment_count: int = 0
    fragment_count: int = 0


class ResourceUpdate(SQLModel):
    """Schema for updating a resource."""

    name: str | None = None
    resource_type: ResourceType | None = None
    status: ResourceStatus | None = None
