"""Add missing resource fields.

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2025-01-02 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6g7h8i9"
down_revision: str | None = "c3d4e5f6g7h8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new columns to resources table for feature parity with TypeScript
    op.add_column(
        "resources",
        sa.Column("author", sa.String(255), nullable=True),
    )
    op.add_column(
        "resources",
        sa.Column("attribution_url", sa.String(2048), nullable=True),
    )
    op.add_column(
        "resources",
        sa.Column("language", sa.String(10), nullable=True, server_default="en"),
    )
    op.add_column(
        "resources",
        sa.Column("edition", sa.String(100), nullable=True),
    )
    op.add_column(
        "resources",
        sa.Column("is_official", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("resources", "is_official")
    op.drop_column("resources", "edition")
    op.drop_column("resources", "language")
    op.drop_column("resources", "attribution_url")
    op.drop_column("resources", "author")
