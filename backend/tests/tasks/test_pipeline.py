"""Tests for the PDF processing pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gamegame.services.pipeline.embed import ResourceInfo, chunk_text_simple
from gamegame.services.pipeline.metadata import extract_metadata
from gamegame.services.pipeline.vision import (
    ImageAnalysisContext,
    ImageAnalysisResult,
    ImageQuality,
    ImageType,
)


class TestChunkText:
    """Tests for the chunk_text_simple function."""

    def test_empty_input(self):
        """Empty input returns empty list."""
        result = chunk_text_simple("")
        assert result == []

    def test_whitespace_only(self):
        """Whitespace-only input returns empty list."""
        result = chunk_text_simple("   \n\n\t  ")
        assert result == []

    def test_single_paragraph(self):
        """Single paragraph stays as one chunk if above minimum size."""
        # Create text that exceeds MIN_CHUNK_SIZE
        text = "This is a paragraph. " * 10  # ~200 chars
        result = chunk_text_simple(text)
        assert len(result) == 1
        assert result[0].content == text.strip()

    def test_multiple_paragraphs(self):
        """Multiple small paragraphs combine into one chunk."""
        # Create paragraphs that together exceed MIN_CHUNK_SIZE
        text = "First paragraph with some content here.\n\n" * 5
        result = chunk_text_simple(text, max_size=2000)
        assert len(result) == 1
        assert "First paragraph" in result[0].content

    def test_short_content_filtered(self):
        """Content below MIN_CHUNK_SIZE is filtered out."""
        text = "Short."  # Below MIN_CHUNK_SIZE
        result = chunk_text_simple(text)
        assert len(result) == 0

    def test_large_paragraph_splits(self):
        """Large paragraphs are split by sentences."""
        text = "This is sentence one. " * 100  # Creates a large paragraph
        result = chunk_text_simple(text, max_size=200)
        assert len(result) > 1

    def test_respects_max_size(self):
        """Chunks don't exceed max_size (approximately)."""
        text = "Para one.\n\n" * 50
        result = chunk_text_simple(text, max_size=100)
        for chunk in result:
            # Allow some tolerance for paragraph boundaries
            assert len(chunk.content) < 200


class TestExtractMetadata:
    """Tests for the extract_metadata function."""

    def test_word_count(self):
        """Correctly counts words."""
        text = "One two three four five"
        result = extract_metadata(text, page_count=1, image_count=0)
        assert result.word_count == 5

    def test_detects_tables(self):
        """Detects markdown tables."""
        text = "| Header 1 | Header 2 |\n|---|---|\n| Cell | Cell |"
        result = extract_metadata(text, page_count=1, image_count=0)
        assert result.has_tables is True

    def test_no_tables(self):
        """Returns False when no tables present."""
        text = "Just some regular text without tables."
        result = extract_metadata(text, page_count=1, image_count=0)
        assert result.has_tables is False

    def test_preserves_counts(self):
        """Preserves provided page and image counts."""
        text = "Some text"
        result = extract_metadata(text, page_count=10, image_count=5)
        assert result.page_count == 10
        assert result.image_count == 5


class TestImageAnalysis:
    """Tests for image analysis functions."""

    @pytest.mark.asyncio
    async def test_analyze_images_batch_empty(self):
        """Empty input returns empty result."""
        from gamegame.services.pipeline.vision import analyze_images_batch

        result = await analyze_images_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_single_image_with_mock(self):
        """Single image analysis with mocked OpenAI."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"description": "Test diagram", "quality": "good", "relevant": true, "type": "diagram", "ocrText": null}'
                )
            )
        ]

        with (
            patch("gamegame.services.pipeline.vision.get_openai_client") as mock_get_client,
            patch("gamegame.services.pipeline.vision.settings") as mock_settings,
        ):
            mock_settings.openai_api_key = "test-key"
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            from gamegame.services.pipeline.vision import analyze_single_image

            result = await analyze_single_image(
                b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,  # PNG magic bytes
                ImageAnalysisContext(page_number=1, game_name="Test Game"),
            )

            assert isinstance(result, ImageAnalysisResult)
            assert result.description == "Test diagram"
            assert result.quality == ImageQuality.GOOD
            assert result.image_type == ImageType.DIAGRAM

    @pytest.mark.asyncio
    async def test_analyze_images_batch_handles_errors(self):
        """Batch analysis handles failures gracefully."""
        from gamegame.services.pipeline.vision import analyze_images_batch

        with (
            patch("gamegame.services.pipeline.vision.get_openai_client") as mock_get_client,
            patch("gamegame.services.pipeline.vision.settings") as mock_settings,
        ):
            mock_settings.openai_api_key = "test-key"
            mock_client = MagicMock()
            # Simulate an error
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("API error")
            )
            mock_get_client.return_value = mock_client

            images = [
                (b"fake_image", ImageAnalysisContext(page_number=1)),
            ]

            results = await analyze_images_batch(images, batch_size=1)

            # Should return fallback result instead of raising
            assert len(results) == 1
            assert results[0].description == "Analysis failed"
            assert results[0].quality == ImageQuality.BAD


class TestPipelineStages:
    """Tests for individual pipeline stage functions."""

    @pytest.mark.asyncio
    async def test_stage_ingest_extracts_content(self):
        """INGEST stage extracts content from PDF."""
        from gamegame.services.pipeline.ingest import (
            ExtractedImage,
            ExtractedPage,
            ExtractionResult,
        )

        # Create mock extraction result
        result = ExtractionResult(
            pages=[
                ExtractedPage(
                    page_number=1,
                    markdown="# Test\n\nContent here.",
                    images=[
                        ExtractedImage(
                            id="img1",
                            base64_data="base64data",
                            page_number=1,
                        )
                    ],
                ),
                ExtractedPage(
                    page_number=2,
                    markdown="More content.",
                    images=[],
                ),
            ],
            total_pages=2,
            raw_markdown="# Test\n\nContent here.\n\nMore content.",
        )

        assert result.total_pages == 2
        assert len(result.pages) == 2
        assert len(result.pages[0].images) == 1
        assert "# Test" in result.raw_markdown

    @pytest.mark.asyncio
    async def test_cleanup_markdown_mock(self):
        """CLEANUP stage cleans markdown content."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Cleaned content"))]

        with (
            patch("gamegame.services.pipeline.cleanup.get_openai_client") as mock_get_client,
            patch("gamegame.services.pipeline.cleanup.settings") as mock_settings,
        ):
            mock_settings.openai_api_key = "test-key"
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            from gamegame.services.pipeline.cleanup import cleanup_markdown

            result = await cleanup_markdown("# Raw\n\nDirty content")

            assert result == "Cleaned content"

    def test_metadata_extraction(self):
        """METADATA stage extracts document metadata."""
        markdown = "| Col1 | Col2 |\n|---|---|\n| A | B |\n\nSome text here with multiple words."
        result = extract_metadata(markdown, page_count=5, image_count=3)

        assert result.page_count == 5
        assert result.image_count == 3
        assert result.has_tables is True
        assert result.word_count > 0


class TestEmbedding:
    """Tests for embedding functions."""

    @pytest.mark.asyncio
    async def test_generate_embeddings_empty(self):
        """Empty input returns empty list."""
        from gamegame.services.pipeline.embed import generate_embeddings

        with patch("gamegame.services.pipeline.embed.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            result = await generate_embeddings([])
            assert result == []

    @pytest.mark.asyncio
    async def test_generate_embeddings_with_mock(self):
        """Generates embeddings for texts."""
        mock_embedding = [0.1] * 1536  # OpenAI returns 1536-dim vectors

        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=mock_embedding),
            MagicMock(embedding=mock_embedding),
        ]

        with (
            patch("gamegame.services.pipeline.embed.get_openai_client") as mock_get_client,
            patch("gamegame.services.pipeline.embed.settings") as mock_settings,
        ):
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_embedding_model = "text-embedding-3-small"
            mock_client = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            from gamegame.services.pipeline.embed import generate_embeddings

            result = await generate_embeddings(["text 1", "text 2"])

            assert len(result) == 2
            assert len(result[0]) == 1536

    @pytest.mark.asyncio
    async def test_generate_hyde_questions_mock(self):
        """Generates HyDE questions from content."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Question 1?\nQuestion 2?\nQuestion 3?"))
        ]

        with (
            patch("gamegame.services.pipeline.embed.get_openai_client") as mock_get_client,
            patch("gamegame.services.pipeline.embed.settings") as mock_settings,
        ):
            mock_settings.openai_api_key = "test-key"
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            from gamegame.services.pipeline.embed import generate_hyde_questions

            resource_info = ResourceInfo(name="Test Game Rulebook", resource_type="rulebook")
            result = await generate_hyde_questions(
                "Some rulebook content about movement.",
                section="Movement Rules",
                resource_info=resource_info,
            )

            assert len(result) == 3
            assert all("?" in q for q in result)

    @pytest.mark.asyncio
    async def test_generate_hyde_no_api_key(self):
        """Returns empty list when no API key."""
        with patch("gamegame.services.pipeline.embed.settings") as mock_settings:
            mock_settings.openai_api_key = None

            from gamegame.services.pipeline.embed import generate_hyde_questions

            resource_info = ResourceInfo(name="Test Game", resource_type="rulebook")
            result = await generate_hyde_questions(
                "Content",
                section=None,
                resource_info=resource_info,
            )
            assert result == []


class TestIngest:
    """Tests for document ingestion."""

    @pytest.mark.asyncio
    async def test_ingest_document_mock(self):
        """Ingests document with mocked Mistral API."""
        from gamegame.services.pipeline.ingest import ingest_document

        mock_page = MagicMock()
        mock_page.index = 0
        mock_page.markdown = "# Page 1\n\nContent here."
        mock_page.images = []

        mock_result = MagicMock()
        mock_result.pages = [mock_page]

        with (
            patch("gamegame.services.pipeline.ingest.Mistral") as mock_cls,
            patch("gamegame.services.pipeline.ingest.settings") as mock_settings,
        ):
            mock_settings.mistral_api_key = "test-key"
            mock_client = MagicMock()
            mock_client.ocr.process_async = AsyncMock(return_value=mock_result)
            mock_cls.return_value = mock_client

            result = await ingest_document(b"fake_pdf_bytes")

            assert result.total_pages == 1
            assert "# Page 1" in result.raw_markdown

    def test_get_supported_mime_types(self):
        """Returns supported MIME types."""
        from gamegame.services.pipeline.ingest import get_supported_mime_types

        types = get_supported_mime_types()
        assert "application/pdf" in types
        assert "image/png" in types
        assert "image/jpeg" in types


class TestFinalize:
    """Tests for finalize functions."""

    @pytest.mark.asyncio
    async def test_finalize_resource(self, session):
        """Finalizes a resource."""
        from gamegame.models import Game, Resource
        from gamegame.models.resource import ResourceStatus
        from gamegame.services.pipeline.finalize import finalize_resource

        # Create test data
        game = Game(name="Finalize Test", slug="finalize-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="Test",
            original_filename="test.pdf",
            url="/uploads/test.pdf",
            content="",  # Required field
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.commit()

        result = await finalize_resource(
            session,
            resource.id,
            page_count=10,
            word_count=500,
            image_count=5,
        )

        assert result.status == ResourceStatus.COMPLETED
        assert result.page_count == 10
        assert result.word_count == 500
        assert result.image_count == 5
        assert result.processed_at is not None

    @pytest.mark.asyncio
    async def test_mark_resource_failed(self, session):
        """Marks a resource as failed."""
        from gamegame.models import Game, Resource
        from gamegame.models.resource import ResourceStatus
        from gamegame.services.pipeline.finalize import mark_resource_failed

        game = Game(name="Failed Test", slug="failed-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="Fail Test",
            original_filename="fail.pdf",
            url="/uploads/fail.pdf",
            content="",  # Required field
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.commit()

        result = await mark_resource_failed(session, resource.id, "Test error message")

        assert result.status == ResourceStatus.FAILED
        assert result.error_message == "Test error message"


class TestCleanupChunking:
    """Tests for cleanup chunking logic."""

    @pytest.mark.asyncio
    async def test_cleanup_empty_content(self):
        """Empty content returns empty string."""
        from gamegame.services.pipeline.cleanup import cleanup_markdown

        result = await cleanup_markdown("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_cleanup_whitespace_only(self):
        """Whitespace-only content returns empty string."""
        from gamegame.services.pipeline.cleanup import cleanup_markdown

        result = await cleanup_markdown("   \n\n  ")
        assert result == ""

    @pytest.mark.asyncio
    async def test_cleanup_no_api_key_passthrough(self):
        """Without API key, returns content as-is."""
        with patch("gamegame.services.pipeline.cleanup.settings") as mock_settings:
            mock_settings.openai_api_key = None

            from gamegame.services.pipeline.cleanup import cleanup_markdown

            result = await cleanup_markdown("# Original\n\nContent")
            assert result == "# Original\n\nContent"


class TestModelConfig:
    """Tests for model configuration."""

    def test_dev_models(self):
        """Development environment uses cheap models."""
        from gamegame.models.model_config import get_model_config

        config = get_model_config("development")
        assert config.vision == "gpt-5-mini"
        assert config.reasoning == "gpt-5-mini"
        assert config.hyde == "gpt-5-mini"
        assert config.embedding == "text-embedding-3-small"

    def test_prod_models(self):
        """Production environment uses quality models."""
        from gamegame.models.model_config import get_model_config

        config = get_model_config("production")
        assert config.vision == "gpt-5"
        assert config.reasoning == "gpt-5"
        assert config.hyde == "gpt-5"
        assert config.classification == "gpt-5-mini"  # Still mini for classification

    def test_get_model(self):
        """get_model returns correct model for task."""
        from gamegame.models.model_config import get_model

        assert get_model("vision", "development") == "gpt-5-mini"
        assert get_model("vision", "production") == "gpt-5"
        assert get_model("embedding") == "text-embedding-3-small"

    def test_test_environment_uses_dev_models(self):
        """Test environment uses dev models."""
        from gamegame.models.model_config import get_model_config

        config = get_model_config("test")
        assert config.vision == "gpt-5-mini"


class TestMimeTypeDetection:
    """Tests for MIME type detection from magic bytes."""

    def test_detect_png(self):
        """Detects PNG from magic bytes."""
        from gamegame.services.pipeline.vision import _detect_mime_type

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert _detect_mime_type(png_bytes) == "image/png"

    def test_detect_jpeg(self):
        """Detects JPEG from magic bytes."""
        from gamegame.services.pipeline.vision import _detect_mime_type

        jpeg_bytes = b"\xff\xd8\xff" + b"\x00" * 100
        assert _detect_mime_type(jpeg_bytes) == "image/jpeg"

    def test_detect_webp(self):
        """Detects WebP from magic bytes."""
        from gamegame.services.pipeline.vision import _detect_mime_type

        webp_bytes = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 100
        assert _detect_mime_type(webp_bytes) == "image/webp"

    def test_detect_gif(self):
        """Detects GIF from magic bytes."""
        from gamegame.services.pipeline.vision import _detect_mime_type

        gif87_bytes = b"GIF87a" + b"\x00" * 100
        gif89_bytes = b"GIF89a" + b"\x00" * 100
        assert _detect_mime_type(gif87_bytes) == "image/gif"
        assert _detect_mime_type(gif89_bytes) == "image/gif"

    def test_default_to_jpeg(self):
        """Unknown format defaults to JPEG."""
        from gamegame.services.pipeline.vision import _detect_mime_type

        unknown_bytes = b"unknown format data" + b"\x00" * 100
        assert _detect_mime_type(unknown_bytes) == "image/jpeg"

    def test_short_data(self):
        """Short data defaults to JPEG."""
        from gamegame.services.pipeline.vision import _detect_mime_type

        short_bytes = b"\x00\x00"
        assert _detect_mime_type(short_bytes) == "image/jpeg"
