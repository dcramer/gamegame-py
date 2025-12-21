"""Add missing attachment fields.

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2025-01-02 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6g7h8"
down_revision: str | None = "b2c3d4e5f6g7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new columns to attachments table for feature parity with TypeScript
    op.add_column(
        "attachments",
        sa.Column("original_filename", sa.String(255), nullable=True),
    )
    op.add_column(
        "attachments",
        sa.Column("width", sa.Integer(), nullable=True),
    )
    op.add_column(
        "attachments",
        sa.Column("height", sa.Integer(), nullable=True),
    )
    op.add_column(
        "attachments",
        sa.Column("caption", sa.Text(), nullable=True),
    )
    op.add_column(
        "attachments",
        sa.Column("is_relevant", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("attachments", "is_relevant")
    op.drop_column("attachments", "caption")
    op.drop_column("attachments", "height")
    op.drop_column("attachments", "width")
    op.drop_column("attachments", "original_filename")
