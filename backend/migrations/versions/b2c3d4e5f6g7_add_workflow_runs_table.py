"""add_workflow_runs_table

Create workflow_runs table for tracking background job runs.

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2025-12-17 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6g7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.VARCHAR(21), primary_key=True),
        sa.Column("run_id", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("workflow_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_data", JSONB(), nullable=True),
        sa.Column("output_data", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column(
            "resource_id",
            sa.VARCHAR(21),
            sa.ForeignKey("resources.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "attachment_id",
            sa.VARCHAR(21),
            sa.ForeignKey("attachments.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "game_id",
            sa.VARCHAR(21),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("extra_data", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # Create index for querying by status
    op.create_index("workflow_runs_status_idx", "workflow_runs", ["status"])


def downgrade() -> None:
    op.drop_index("workflow_runs_status_idx", table_name="workflow_runs")
    op.drop_table("workflow_runs")
