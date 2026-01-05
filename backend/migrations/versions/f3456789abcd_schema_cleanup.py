"""schema_cleanup

Revision ID: f3456789abcd
Revises: 0a8665379286
Create Date: 2026-01-04 12:00:00.000000

Comprehensive schema cleanup before ship:
- Fix processed_at type (VARCHAR -> TIMESTAMP)
- Remove redundant Fragment.embedding column (use Embeddings table)
- Remove denormalized fields from Fragment (resource_name, resource_description, resource_type)
- Add missing indexes for frequently queried fields
- Add unique constraint on segment ordering
- Add check constraints for data integrity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = "f3456789abcd"
down_revision: str | None = "0a8665379286"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Fix processed_at type (VARCHAR -> TIMESTAMP WITH TIMEZONE)
    # First convert existing string data, then alter column type
    op.execute("""
        ALTER TABLE resources
        ALTER COLUMN processed_at TYPE TIMESTAMP WITH TIME ZONE
        USING CASE
            WHEN processed_at IS NOT NULL AND processed_at != ''
            THEN processed_at::TIMESTAMP WITH TIME ZONE
            ELSE NULL
        END
    """)

    # 2. Remove redundant Fragment.embedding column (data is in embeddings table)
    # First drop the HNSW index on this column
    op.drop_index("fragment_embedding_idx", table_name="fragments")
    op.drop_column("fragments", "embedding")

    # 3. Remove denormalized fields from Fragment
    op.drop_column("fragments", "resource_name")
    op.drop_column("fragments", "resource_description")
    op.drop_column("fragments", "resource_type")

    # 4. Add missing indexes
    # Resources: status and created_at for queue and pagination
    op.create_index("ix_resources_status", "resources", ["status"])
    op.create_index("ix_resources_created_at", "resources", ["created_at"])

    # Workflow runs: status and created_at for monitoring
    op.create_index("ix_workflow_runs_created_at", "workflow_runs", ["created_at"])

    # Segments: composite index for ordering within resource
    op.create_index(
        "ix_segments_resource_order",
        "segments",
        ["resource_id", "order_index"],
        unique=True
    )

    # Attachments: filter fields for admin UI
    op.create_index("ix_attachments_detected_type", "attachments", ["detected_type"])
    op.create_index("ix_attachments_is_relevant", "attachments", ["is_relevant"])

    # Fragments: type filtering
    op.create_index("ix_fragments_type", "fragments", ["type"])

    # Note: bgg_games table may not exist yet (model without migration)
    # Index will be created when that table is migrated

    # 5. Add check constraints
    op.create_check_constraint(
        "ck_resources_page_count_positive",
        "resources",
        "page_count IS NULL OR page_count >= 0"
    )
    op.create_check_constraint(
        "ck_resources_image_count_positive",
        "resources",
        "image_count IS NULL OR image_count >= 0"
    )
    op.create_check_constraint(
        "ck_segments_level_valid",
        "segments",
        "level >= 1 AND level <= 6"
    )
    op.create_check_constraint(
        "ck_segments_page_range_valid",
        "segments",
        "page_start IS NULL OR page_end IS NULL OR page_start <= page_end"
    )


def downgrade() -> None:
    # Remove check constraints
    op.drop_constraint("ck_segments_page_range_valid", "segments", type_="check")
    op.drop_constraint("ck_segments_level_valid", "segments", type_="check")
    op.drop_constraint("ck_resources_image_count_positive", "resources", type_="check")
    op.drop_constraint("ck_resources_page_count_positive", "resources", type_="check")

    # Remove indexes
    op.drop_index("ix_fragments_type", table_name="fragments")
    op.drop_index("ix_attachments_is_relevant", table_name="attachments")
    op.drop_index("ix_attachments_detected_type", table_name="attachments")
    op.drop_index("ix_segments_resource_order", table_name="segments")
    op.drop_index("ix_workflow_runs_created_at", table_name="workflow_runs")
    op.drop_index("ix_resources_created_at", table_name="resources")
    op.drop_index("ix_resources_status", table_name="resources")

    # Restore denormalized fields to Fragment
    op.add_column("fragments", sa.Column("resource_type", sa.VARCHAR(50), nullable=True))
    op.add_column("fragments", sa.Column("resource_description", sa.TEXT(), nullable=True))
    op.add_column("fragments", sa.Column("resource_name", sa.VARCHAR(255), nullable=True))

    # Restore Fragment.embedding column
    op.add_column(
        "fragments",
        sa.Column("embedding", Vector(1536), nullable=False)
    )
    # Note: Would need to repopulate embedding data from embeddings table
    op.create_index(
        "fragment_embedding_idx",
        "fragments",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_ip_ops"},
    )

    # Revert processed_at to VARCHAR
    op.execute("""
        ALTER TABLE resources
        ALTER COLUMN processed_at TYPE VARCHAR
        USING processed_at::VARCHAR
    """)
