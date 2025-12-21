"""add_search_quality_improvements

Adds searchable_content, answer types, version tracking, and improved indexes
for enhanced search quality matching TypeScript implementation.

Revision ID: a1b2c3d4e5f6
Revises: f363b308d775
Create Date: 2025-12-17 17:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f363b308d775"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to fragments table
    op.add_column(
        "fragments",
        sa.Column("searchable_content", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragments",
        sa.Column("page_range", JSONB(), nullable=True),
    )
    op.add_column(
        "fragments",
        sa.Column("resource_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "fragments",
        sa.Column("resource_description", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragments",
        sa.Column("resource_type", sa.String(50), nullable=True),
    )
    op.add_column(
        "fragments",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    # Add new columns to embeddings table
    op.add_column(
        "embeddings",
        sa.Column("page_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "embeddings",
        sa.Column("section", sa.String(255), nullable=True),
    )
    op.add_column(
        "embeddings",
        sa.Column("fragment_type", sa.String(20), nullable=True),
    )

    # Add description column to resources (for LLM-generated descriptions)
    op.add_column(
        "resources",
        sa.Column("description", sa.Text(), nullable=True),
    )

    # Drop existing vector indexes (they use cosine ops)
    op.execute("DROP INDEX IF EXISTS fragment_embedding_idx")
    op.execute("DROP INDEX IF EXISTS embedding_vector_idx")

    # Recreate vector indexes with inner product ops (faster for normalized embeddings)
    op.execute("""
        CREATE INDEX fragment_embedding_idx ON fragments
        USING hnsw (embedding vector_ip_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("""
        CREATE INDEX embedding_vector_idx ON embeddings
        USING hnsw (embedding vector_ip_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Add new indexes for efficient queries
    op.create_index("embedding_game_id_idx", "embeddings", ["game_id"])


def downgrade() -> None:
    # Drop new indexes
    op.drop_index("embedding_game_id_idx", table_name="embeddings")

    # Drop and recreate vector indexes with cosine ops
    op.execute("DROP INDEX IF EXISTS fragment_embedding_idx")
    op.execute("DROP INDEX IF EXISTS embedding_vector_idx")
    op.execute("""
        CREATE INDEX fragment_embedding_idx ON fragments
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("""
        CREATE INDEX embedding_vector_idx ON embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Drop new columns from resources
    op.drop_column("resources", "description")

    # Drop new columns from embeddings
    op.drop_column("embeddings", "fragment_type")
    op.drop_column("embeddings", "section")
    op.drop_column("embeddings", "page_number")

    # Drop new columns from fragments
    op.drop_column("fragments", "version")
    op.drop_column("fragments", "resource_type")
    op.drop_column("fragments", "resource_description")
    op.drop_column("fragments", "resource_name")
    op.drop_column("fragments", "page_range")
    op.drop_column("fragments", "searchable_content")
