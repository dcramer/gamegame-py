"""Add SEGMENT to ProcessingStage enum.

Revision ID: e2345678901b
Revises: d1234567890a
Create Date: 2024-12-31 14:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2345678901b"
down_revision: str | None = "c9566fd34721"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add SEGMENT value to the processingstage enum
    # In PostgreSQL, we need to use ALTER TYPE to add a new value
    op.execute("ALTER TYPE processingstage ADD VALUE IF NOT EXISTS 'SEGMENT' AFTER 'METADATA'")


def downgrade() -> None:
    # Note: PostgreSQL doesn't support removing enum values directly
    # The safest approach is to leave the enum value in place
    # If a full downgrade is needed, you'd need to:
    # 1. Create a new enum type without SEGMENT
    # 2. Update the column to use the new type
    # 3. Drop the old type
    pass
