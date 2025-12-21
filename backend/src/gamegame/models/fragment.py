"""Fragment model for document chunks with embeddings."""

from enum import Enum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Index, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlmodel import Field, SQLModel

from gamegame.config import settings
from gamegame.models.base import TimestampMixin, generate_nanoid


class FragmentType(str, Enum):
    """Type of fragment."""

    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"


class Fragment(TimestampMixin, SQLModel, table=True):
    """Document fragment/chunk for RAG retrieval."""

    __tablename__ = "fragments"

    id: str = Field(default_factory=generate_nanoid, primary_key=True, max_length=21)
    game_id: str = Field(foreign_key="games.id", index=True, ondelete="CASCADE", max_length=21)
    resource_id: str = Field(foreign_key="resources.id", index=True, ondelete="CASCADE", max_length=21)

    content: str = Field(description="Original text content")
    type: FragmentType = Field(default=FragmentType.TEXT)

    # Enriched searchable content (includes context, resource info)
    searchable_content: str | None = Field(default=None, description="Enriched content for embedding")

    # Location info
    page_number: int | None = Field(default=None)
    page_range: list[int] | None = Field(
        default=None,
        sa_column=Column(JSONB),
        description="Page range [start, end] for multi-page fragments",
    )
    section: str | None = Field(default=None, max_length=255)

    # Associated attachment (for image fragments)
    attachment_id: str | None = Field(default=None, foreign_key="attachments.id", max_length=21)

    # Denormalized resource info for search enrichment
    resource_name: str | None = Field(default=None, max_length=255)
    resource_description: str | None = Field(default=None)
    resource_type: str | None = Field(default=None, max_length=50)

    # Vector embedding for semantic search (NOT NULL, matches TypeScript)
    embedding: list[float] = Field(
        sa_column=Column(Vector(settings.embedding_dimensions), nullable=False),
    )

    # Full-text search vector
    search_vector: Any | None = Field(
        default=None,
        sa_column=Column(TSVECTOR),
    )

    # HyDE synthetic questions
    synthetic_questions: list[str] | None = Field(
        default=None,
        sa_column=Column(JSONB),
    )

    # Answer type classification (e.g., "rules", "setup", "components", "strategy")
    answer_types: list[str] | None = Field(
        default=None,
        sa_column=Column(JSONB),
    )

    # Image metadata (for image fragments)
    images: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(JSONB),
    )

    # Version tracking for reindexing
    version: int = Field(default=0, description="Embedding/index version")

    __table_args__ = (
        # HNSW index for vector similarity search using inner product
        # OpenAI embeddings are normalized, so inner product = cosine similarity
        # but inner product is faster to compute
        Index(
            "fragment_embedding_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_ip_ops"},
        ),
        # GIN index for full-text search
        Index(
            "fragment_search_vector_idx",
            "search_vector",
            postgresql_using="gin",
        ),
    )


class FragmentCreate(SQLModel):
    """Schema for creating a fragment."""

    game_id: str
    resource_id: str
    content: str
    type: FragmentType = FragmentType.TEXT
    page_number: int | None = None
    section: str | None = None
    attachment_id: str | None = None


class FragmentRead(SQLModel):
    """Schema for reading a fragment."""

    id: str
    game_id: str
    resource_id: str
    content: str
    type: FragmentType
    page_number: int | None
    section: str | None
    attachment_id: str | None


# SQL function to update search vector
UPDATE_SEARCH_VECTOR_SQL = text("""
    CREATE OR REPLACE FUNCTION update_fragment_search_vector()
    RETURNS trigger AS $$
    BEGIN
        NEW.search_vector := to_tsvector('english', NEW.content);
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
""")

# Trigger to auto-update search vector
CREATE_SEARCH_VECTOR_TRIGGER_SQL = text("""
    DROP TRIGGER IF EXISTS fragment_search_vector_update ON fragments;
    CREATE TRIGGER fragment_search_vector_update
    BEFORE INSERT OR UPDATE ON fragments
    FOR EACH ROW
    EXECUTE FUNCTION update_fragment_search_vector();
""")
