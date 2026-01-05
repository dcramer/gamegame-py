"""add_bgg_games_table

Revision ID: g4567890bcde
Revises: f3456789abcd
Create Date: 2026-01-04 12:30:00.000000

Create bgg_games table for caching BoardGameGeek API responses.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "g4567890bcde"
down_revision: str | None = "f3456789abcd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bgg_games",
        sa.Column("id", sa.Integer(), nullable=False, comment="BoardGameGeek game ID"),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("year_published", sa.Integer(), nullable=True),
        sa.Column("min_players", sa.Integer(), nullable=True),
        sa.Column("max_players", sa.Integer(), nullable=True),
        sa.Column("playing_time", sa.Integer(), nullable=True),
        sa.Column("thumbnail_url", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("publishers", postgresql.JSON(), nullable=True),
        sa.Column("designers", postgresql.JSON(), nullable=True),
        sa.Column("categories", postgresql.JSON(), nullable=True),
        sa.Column("mechanics", postgresql.JSON(), nullable=True),
        sa.Column(
            "cached_at",
            sa.BigInteger(),
            nullable=False,
            comment="Unix timestamp in milliseconds when cached",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Create indexes
    op.create_index("idx_bgg_games_name", "bgg_games", ["name"])
    op.create_index("ix_bgg_games_cached_at", "bgg_games", ["cached_at"])


def downgrade() -> None:
    op.drop_index("ix_bgg_games_cached_at", table_name="bgg_games")
    op.drop_index("idx_bgg_games_name", table_name="bgg_games")
    op.drop_table("bgg_games")
