"""Model parity fixes to match TypeScript schema.

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2025-01-02 20:00:00.000000

Changes:
- resources: add version column, make content NOT NULL with default ''
- resources: change status default from 'queued' to 'ready'
- fragments: make embedding NOT NULL, change version default to 0
- attachments: make blob_key and url NOT NULL
- embeddings: change version default to 0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6g7h8i9j0"
down_revision: str | None = "d4e5f6g7h8i9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Resources: add version column
    op.add_column(
        "resources",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )

    # Resources: make content NOT NULL with default ''
    # First set any NULL values to empty string
    op.execute("UPDATE resources SET content = '' WHERE content IS NULL")
    op.alter_column(
        "resources",
        "content",
        existing_type=sa.Text(),
        nullable=False,
        server_default="",
    )

    # Resources: change status default to 'READY' (enum uses uppercase)
    op.alter_column(
        "resources",
        "status",
        existing_type=sa.Enum('READY', 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED', name='resourcestatus'),
        server_default="READY",
    )

    # Fragments: change version default to 0
    op.alter_column(
        "fragments",
        "version",
        existing_type=sa.Integer(),
        server_default="0",
    )

    # Attachments: make blob_key NOT NULL
    # First ensure no NULL values exist
    op.execute("DELETE FROM attachments WHERE blob_key IS NULL")
    op.alter_column(
        "attachments",
        "blob_key",
        existing_type=sa.Text(),
        nullable=False,
    )

    # Attachments: make url NOT NULL
    op.execute("DELETE FROM attachments WHERE url IS NULL")
    op.alter_column(
        "attachments",
        "url",
        existing_type=sa.Text(),
        nullable=False,
    )

    # Embeddings: change version default to 0
    op.alter_column(
        "embeddings",
        "version",
        existing_type=sa.Integer(),
        server_default="0",
    )


def downgrade() -> None:
    # Embeddings: revert version default
    op.alter_column(
        "embeddings",
        "version",
        existing_type=sa.Integer(),
        server_default="1",
    )

    # Attachments: make url nullable
    op.alter_column(
        "attachments",
        "url",
        existing_type=sa.Text(),
        nullable=True,
    )

    # Attachments: make blob_key nullable
    op.alter_column(
        "attachments",
        "blob_key",
        existing_type=sa.Text(),
        nullable=True,
    )

    # Fragments: revert version default
    op.alter_column(
        "fragments",
        "version",
        existing_type=sa.Integer(),
        server_default="1",
    )

    # Resources: revert status default
    op.alter_column(
        "resources",
        "status",
        existing_type=sa.Enum('READY', 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED', name='resourcestatus'),
        server_default="QUEUED",
    )

    # Resources: make content nullable
    op.alter_column(
        "resources",
        "content",
        existing_type=sa.Text(),
        nullable=True,
        server_default=None,
    )

    # Resources: drop version column
    op.drop_column("resources", "version")
