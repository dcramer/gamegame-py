"""WorkflowRun model for tracking background job runs."""

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel

from gamegame.models.base import TimestampMixin, generate_nanoid


class WorkflowStatus(str, Enum):
    """Status of a workflow run."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowRun(TimestampMixin, SQLModel, table=True):
    """Tracks background workflow/job runs."""

    __tablename__ = "workflow_runs"

    id: str = Field(default_factory=generate_nanoid, primary_key=True, max_length=21)

    # External job ID (from SAQ or other queue)
    run_id: str = Field(max_length=255, index=True, unique=True)

    # Workflow details
    workflow_name: str = Field(max_length=100)
    status: WorkflowStatus = Field(default=WorkflowStatus.QUEUED)

    # Timing - use timezone-aware columns
    started_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # Input/Output
    input_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    output_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Error info
    error: str | None = Field(default=None)
    error_code: str | None = Field(default=None, max_length=50)

    # Related entities
    resource_id: str | None = Field(default=None, foreign_key="resources.id", index=True, max_length=21)
    attachment_id: str | None = Field(default=None, foreign_key="attachments.id", index=True, max_length=21)
    game_id: str | None = Field(default=None, foreign_key="games.id", index=True, max_length=21)

    # Extra metadata
    extra_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class WorkflowRunRead(SQLModel):
    """Schema for reading a workflow run."""

    id: str
    run_id: str
    workflow_name: str
    status: WorkflowStatus
    started_at: datetime | None
    completed_at: datetime | None
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    error: str | None
    error_code: str | None
    resource_id: str | None
    attachment_id: str | None
    game_id: str | None
    extra_data: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
