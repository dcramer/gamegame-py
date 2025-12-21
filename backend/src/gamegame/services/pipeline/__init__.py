"""Pipeline services for PDF processing stages."""

from gamegame.services.pipeline.cleanup import cleanup_markdown
from gamegame.services.pipeline.embed import embed_content
from gamegame.services.pipeline.finalize import finalize_resource
from gamegame.services.pipeline.ingest import ingest_document
from gamegame.services.pipeline.metadata import extract_metadata, generate_resource_metadata
from gamegame.services.pipeline.vision import analyze_images_batch

__all__ = [
    "analyze_images_batch",
    "cleanup_markdown",
    "embed_content",
    "extract_metadata",
    "finalize_resource",
    "generate_resource_metadata",
    "ingest_document",
]
