"""add_segment_summary_embeddings

Revision ID: h5678901cdef
Revises: g4567890bcde
Create Date: 2026-01-04 14:00:00.000000

Extend embeddings table to support segment-level summary embeddings:
- Make fragment_id nullable (segment embeddings don't have fragments)
- Add segment_id foreign key
- Add summary_text field for storing generated summaries
- Add index for segment lookups
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "h5678901cdef"
down_revision: str | None = "g4567890bcde"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0. Add 'SUMMARY' to embeddingtype enum (uppercase to match existing CONTENT/QUESTION)
    op.execute("ALTER TYPE embeddingtype ADD VALUE IF NOT EXISTS 'SUMMARY'")

    # 1. Make fragment_id nullable (was NOT NULL)
    op.alter_column(
        "embeddings",
        "fragment_id",
        existing_type=sa.VARCHAR(21),
        nullable=True,
    )

    # 2. Add segment_id column with FK to segments
    op.add_column(
        "embeddings",
        sa.Column("segment_id", sa.VARCHAR(21), nullable=True),
    )
    op.create_foreign_key(
        "fk_embeddings_segment_id",
        "embeddings",
        "segments",
        ["segment_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 3. Add summary_text column for storing generated summaries
    op.add_column(
        "embeddings",
        sa.Column("summary_text", sa.Text(), nullable=True),
    )

    # 4. Add index for segment + type lookups
    op.create_index(
        "embedding_segment_type_idx",
        "embeddings",
        ["segment_id", "type"],
    )


def downgrade() -> None:
    # Remove index
    op.drop_index("embedding_segment_type_idx", table_name="embeddings")

    # Remove summary_text column
    op.drop_column("embeddings", "summary_text")

    # Remove segment_id foreign key and column
    op.drop_constraint("fk_embeddings_segment_id", "embeddings", type_="foreignkey")
    op.drop_column("embeddings", "segment_id")

    # Make fragment_id NOT NULL again
    # Note: This will fail if there are rows with NULL fragment_id
    op.alter_column(
        "embeddings",
        "fragment_id",
        existing_type=sa.VARCHAR(21),
        nullable=False,
    )
