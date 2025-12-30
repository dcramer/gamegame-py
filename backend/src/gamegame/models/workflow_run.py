"""WorkflowRun model for tracking background job runs."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import computed_field
from sqlalchemy import JSON, Column, DateTime, String
from sqlmodel import Field, SQLModel

from gamegame.models.base import TimestampMixin, generate_nanoid

# Stage metadata - single source of truth
STAGE_METADATA: dict[str, tuple[int, str]] = {
    "ingest": (15, "Extracting PDF"),
    "vision": (35, "Analyzing images"),
    "cleanup": (50, "Cleaning content"),
    "metadata": (60, "Generating metadata"),
    "embed": (85, "Creating embeddings"),
    "finalize": (95, "Finalizing"),
}

# Maximum retries allowed
MAX_WORKFLOW_RETRIES = 3


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
    status: str = Field(
        default="queued",
        sa_column=Column(String(20), nullable=False, default="queued"),
    )

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
    status: str
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

    @computed_field
    @property
    def progress_percent(self) -> int | None:
        """Compute progress percentage from current stage."""
        if self.status == "completed":
            return 100
        if self.status not in ("queued", "running"):
            return None
        stage = (self.extra_data or {}).get("current_stage")
        if not stage:
            return 0
        metadata = STAGE_METADATA.get(stage)
        return metadata[0] if metadata else 0

    @computed_field
    @property
    def stage_label(self) -> str | None:
        """Get human-readable label for current stage with optional item progress."""
        extra = self.extra_data or {}
        stage = extra.get("current_stage")
        if not stage:
            return None

        metadata = STAGE_METADATA.get(stage)
        label = metadata[1] if metadata else stage.replace("_", " ").title()

        # Add item progress if available
        progress_current = extra.get("progress_current")
        progress_total = extra.get("progress_total")
        if progress_current is not None and progress_total is not None:
            label = f"{label} ({progress_current}/{progress_total})"

        return label

    @computed_field
    @property
    def resource_name(self) -> str | None:
        """Get resource name from extra_data."""
        return (self.extra_data or {}).get("resource_name")

    @computed_field
    @property
    def retry_count(self) -> int:
        """Get number of retries attempted."""
        return (self.extra_data or {}).get("retry_count", 0)

    @computed_field
    @property
    def can_retry(self) -> bool:
        """Whether this workflow can be retried."""
        return self.status == "failed" and self.retry_count < MAX_WORKFLOW_RETRIES
