"""rename chapters to segments

Revision ID: c9566fd34721
Revises: b8455ec27832
Create Date: 2025-12-31 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c9566fd34721'
down_revision: Union[str, None] = 'b8455ec27832'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop foreign key constraints first
    op.drop_constraint('fk_fragments_chapter_id', 'fragments', type_='foreignkey')

    # Rename chapters table to segments
    op.rename_table('chapters', 'segments')

    # Rename indexes on segments table
    op.drop_index('ix_chapters_game_id', table_name='segments')
    op.drop_index('ix_chapters_resource_id', table_name='segments')
    op.create_index('ix_segments_game_id', 'segments', ['game_id'], unique=False)
    op.create_index('ix_segments_resource_id', 'segments', ['resource_id'], unique=False)

    # Update self-referential foreign key (parent_id) with ON DELETE SET NULL
    # First drop the old constraint, then recreate with new table name
    op.drop_constraint('chapters_parent_id_fkey', 'segments', type_='foreignkey')
    op.create_foreign_key(
        'fk_segments_parent_id', 'segments', 'segments',
        ['parent_id'], ['id'], ondelete='SET NULL'
    )

    # Rename chapter_id to segment_id in fragments
    op.drop_index('ix_fragments_chapter_id', table_name='fragments')
    op.alter_column('fragments', 'chapter_id', new_column_name='segment_id')
    op.create_index('ix_fragments_segment_id', 'fragments', ['segment_id'], unique=False)

    # Recreate foreign key with new table name and ON DELETE SET NULL
    op.create_foreign_key(
        'fk_fragments_segment_id', 'fragments', 'segments',
        ['segment_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    # Drop new foreign key constraint
    op.drop_constraint('fk_fragments_segment_id', 'fragments', type_='foreignkey')

    # Rename segment_id back to chapter_id in fragments
    op.drop_index('ix_fragments_segment_id', table_name='fragments')
    op.alter_column('fragments', 'segment_id', new_column_name='chapter_id')
    op.create_index('ix_fragments_chapter_id', 'fragments', ['chapter_id'], unique=False)

    # Update self-referential foreign key back
    op.drop_constraint('fk_segments_parent_id', 'segments', type_='foreignkey')
    op.create_foreign_key('chapters_parent_id_fkey', 'segments', 'segments', ['parent_id'], ['id'])

    # Rename indexes back
    op.drop_index('ix_segments_game_id', table_name='segments')
    op.drop_index('ix_segments_resource_id', table_name='segments')

    # Rename segments table back to chapters
    op.rename_table('segments', 'chapters')

    op.create_index('ix_chapters_game_id', 'chapters', ['game_id'], unique=False)
    op.create_index('ix_chapters_resource_id', 'chapters', ['resource_id'], unique=False)

    # Recreate original foreign key
    op.create_foreign_key('fk_fragments_chapter_id', 'fragments', 'chapters', ['chapter_id'], ['id'])
