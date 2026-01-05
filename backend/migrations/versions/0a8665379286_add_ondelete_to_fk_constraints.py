"""add_ondelete_to_fk_constraints

Revision ID: 0a8665379286
Revises: e2345678901b
Create Date: 2026-01-04 10:19:14.479393

This migration adds ON DELETE SET NULL to the fragments.attachment_id FK constraint
that was created without it in the initial schema.

Note: workflow_runs FKs already have SET NULL from their creation migration.
Note: segments.parent_id and fragments.segment_id have SET NULL from the rename migration.
"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0a8665379286"
down_revision: str | None = "e2345678901b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop and recreate FK on fragments.attachment_id with ON DELETE SET NULL
    op.drop_constraint("fragments_attachment_id_fkey", "fragments", type_="foreignkey")
    op.create_foreign_key(
        "fk_fragments_attachment_id",
        "fragments",
        "attachments",
        ["attachment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Restore original FK on fragments.attachment_id (no ON DELETE)
    op.drop_constraint("fk_fragments_attachment_id", "fragments", type_="foreignkey")
    op.create_foreign_key(
        "fragments_attachment_id_fkey",
        "fragments",
        "attachments",
        ["attachment_id"],
        ["id"],
    )
