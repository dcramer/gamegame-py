"""add chapters table

Revision ID: b8455ec27832
Revises: 8a145b18f352
Create Date: 2025-12-31 10:16:47.684692

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'b8455ec27832'
down_revision: Union[str, None] = '5b9035552706'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create chapters table
    op.create_table('chapters',
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(length=21), nullable=False),
        sa.Column('resource_id', sqlmodel.sql.sqltypes.AutoString(length=21), nullable=False),
        sa.Column('game_id', sqlmodel.sql.sqltypes.AutoString(length=21), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('hierarchy_path', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('content', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('page_start', sa.Integer(), nullable=True),
        sa.Column('page_end', sa.Integer(), nullable=True),
        sa.Column('word_count', sa.Integer(), nullable=True),
        sa.Column('char_count', sa.Integer(), nullable=True),
        sa.Column('parent_id', sqlmodel.sql.sqltypes.AutoString(length=21), nullable=True),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['chapters.id']),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chapters_game_id'), 'chapters', ['game_id'], unique=False)
    op.create_index(op.f('ix_chapters_resource_id'), 'chapters', ['resource_id'], unique=False)

    # Add chapter_id to fragments
    op.add_column('fragments', sa.Column('chapter_id', sqlmodel.sql.sqltypes.AutoString(length=21), nullable=True))
    op.create_index(op.f('ix_fragments_chapter_id'), 'fragments', ['chapter_id'], unique=False)
    op.create_foreign_key('fk_fragments_chapter_id', 'fragments', 'chapters', ['chapter_id'], ['id'])


def downgrade() -> None:
    # Remove chapter_id from fragments
    op.drop_constraint('fk_fragments_chapter_id', 'fragments', type_='foreignkey')
    op.drop_index(op.f('ix_fragments_chapter_id'), table_name='fragments')
    op.drop_column('fragments', 'chapter_id')

    # Drop chapters table
    op.drop_index(op.f('ix_chapters_resource_id'), table_name='chapters')
    op.drop_index(op.f('ix_chapters_game_id'), table_name='chapters')
    op.drop_table('chapters')
