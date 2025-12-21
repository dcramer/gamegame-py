"""Embedding model for HyDE and content embeddings."""

from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Index
from sqlmodel import Field, SQLModel

from gamegame.config import settings
from gamegame.models.base import TimestampMixin


class EmbeddingType(str, Enum):
    """Type of embedding."""

    CONTENT = "content"
    QUESTION = "question"


class Embedding(TimestampMixin, SQLModel, table=True):
    """Separate embedding storage for HyDE questions and content."""

    __tablename__ = "embeddings"

    # ID format: fragmentId or fragmentId-q{0-4}
    id: str = Field(primary_key=True, max_length=50)
    fragment_id: str = Field(foreign_key="fragments.id", index=True, ondelete="CASCADE", max_length=21)
    game_id: str = Field(foreign_key="games.id", index=True, ondelete="CASCADE", max_length=21)
    resource_id: str = Field(foreign_key="resources.id", index=True, ondelete="CASCADE", max_length=21)

    # Embedding vector
    embedding: list[float] = Field(
        sa_column=Column(Vector(settings.embedding_dimensions), nullable=False),
    )

    # Type and metadata
    type: EmbeddingType = Field(default=EmbeddingType.CONTENT)
    question_index: int | None = Field(default=None)
    question_text: str | None = Field(default=None)
    version: int = Field(default=0)  # Matches TypeScript

    # Denormalized fields for efficient filtering
    page_number: int | None = Field(default=None)
    section: str | None = Field(default=None, max_length=255)
    fragment_type: str | None = Field(default=None, max_length=20)  # text, image, table

    __table_args__ = (
        # HNSW index for vector similarity search using inner product
        # OpenAI embeddings are normalized, so inner product = cosine similarity
        Index(
            "embedding_vector_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_ip_ops"},
        ),
        # Index for lookups by fragment
        Index("embedding_fragment_type_idx", "fragment_id", "type"),
        # Index for game-scoped searches
        Index("embedding_game_id_idx", "game_id"),
    )


class EmbeddingCreate(SQLModel):
    """Schema for creating an embedding."""

    id: str
    fragment_id: str
    game_id: str
    resource_id: str
    embedding: list[float]
    type: EmbeddingType = EmbeddingType.CONTENT
    question_index: int | None = None
    question_text: str | None = None
