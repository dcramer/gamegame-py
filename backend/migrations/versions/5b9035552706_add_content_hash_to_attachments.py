"""Add content_hash to attachments

Revision ID: 5b9035552706
Revises: e5f6g7h8i9j0
Create Date: 2025-12-29 21:42:06.495185

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5b9035552706'
down_revision: str | None = 'e5f6g7h8i9j0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('attachments', sa.Column('content_hash', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_attachments_content_hash'), 'attachments', ['content_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_attachments_content_hash'), table_name='attachments')
    op.drop_column('attachments', 'content_hash')
