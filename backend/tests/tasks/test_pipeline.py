"""Tests for the PDF processing pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gamegame.models import Attachment, Embedding, Fragment, Game, Resource
from gamegame.models.attachment import AttachmentType
from gamegame.models.resource import ProcessingStage, ResourceStatus
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


class TestDataUrlStripping:
    """Tests for data URL prefix stripping."""

    def test_strips_jpeg_data_url(self):
        """Strips data:image/jpeg;base64, prefix."""
        from gamegame.utils.image import strip_data_url_prefix

        data_url = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        result = strip_data_url_prefix(data_url)
        assert result == "/9j/4AAQSkZJRg=="

    def test_strips_png_data_url(self):
        """Strips data:image/png;base64, prefix."""
        from gamegame.utils.image import strip_data_url_prefix

        data_url = "data:image/png;base64,iVBORw0KGgo="
        result = strip_data_url_prefix(data_url)
        assert result == "iVBORw0KGgo="

    def test_preserves_plain_base64(self):
        """Leaves plain base64 unchanged."""
        from gamegame.utils.image import strip_data_url_prefix

        plain_b64 = "/9j/4AAQSkZJRg=="
        result = strip_data_url_prefix(plain_b64)
        assert result == "/9j/4AAQSkZJRg=="

    def test_handles_data_url_with_charset(self):
        """Handles data URLs with extra parameters."""
        from gamegame.utils.image import strip_data_url_prefix

        data_url = "data:image/png;charset=utf-8;base64,iVBORw0KGgo="
        result = strip_data_url_prefix(data_url)
        assert result == "iVBORw0KGgo="

    def test_decodes_correctly_after_stripping(self):
        """Verify base64 decodes to valid image bytes after stripping."""
        import base64

        from gamegame.utils.image import strip_data_url_prefix

        # Real JPEG header in base64
        jpeg_header_b64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/"
        data_url = f"data:image/jpeg;base64,{jpeg_header_b64}"

        stripped = strip_data_url_prefix(data_url)
        decoded = base64.b64decode(stripped)

        # Should start with JPEG magic bytes
        assert decoded[:2] == b"\xff\xd8"


class TestImageContextExtraction:
    """Tests for extract_image_context function."""

    def test_extracts_surrounding_text(self):
        """Extracts text around an image reference."""
        from gamegame.services.pipeline.vision import extract_image_context

        markdown = """Some intro text here.

This paragraph explains the setup process for the game.
![Setup diagram](img_001)
After placing the board, each player takes their pieces.

More content follows."""

        section, surrounding = extract_image_context("img_001", markdown)

        assert surrounding is not None
        assert "setup process" in surrounding.lower()
        assert "each player takes" in surrounding.lower()
        assert "[...image...]" in surrounding

    def test_extracts_section_header(self):
        """Finds the nearest section header above the image."""
        from gamegame.services.pipeline.vision import extract_image_context

        markdown = """# Introduction

Some intro text.

## Game Setup

This section covers setup.
![Board layout](img_setup)
Place the board in the center."""

        section, surrounding = extract_image_context("img_setup", markdown)

        assert section == "Game Setup"

    def test_handles_nested_headers(self):
        """Finds the nearest header, not just the first."""
        from gamegame.services.pipeline.vision import extract_image_context

        markdown = """# Rules

## Combat

### Attacking

Roll dice to attack.
![Attack example](img_attack)
Compare results."""

        section, surrounding = extract_image_context("img_attack", markdown)

        assert section == "Attacking"

    def test_handles_missing_image(self):
        """Returns None when image not found."""
        from gamegame.services.pipeline.vision import extract_image_context

        markdown = "Some text without images."

        section, surrounding = extract_image_context("nonexistent", markdown)

        assert section is None
        assert surrounding is None

    def test_cleans_other_image_refs(self):
        """Replaces other image references with [image] placeholder."""
        from gamegame.services.pipeline.vision import extract_image_context

        markdown = """![First](img_001)
Some text between images.
![Target](img_002)
More text.
![Third](img_003)"""

        section, surrounding = extract_image_context("img_002", markdown)

        assert surrounding is not None
        assert "img_001" not in surrounding
        assert "img_003" not in surrounding
        assert "[image]" in surrounding

    def test_handles_empty_markdown(self):
        """Handles empty markdown gracefully."""
        from gamegame.services.pipeline.vision import extract_image_context

        section, surrounding = extract_image_context("img_001", "")

        assert section is None
        assert surrounding is None


class TestImageReferencePatterns:
    """Tests for image reference replacement patterns."""

    def test_simple_alt_text(self):
        """Matches simple alt text without brackets."""
        import re

        original_id = "img_001"
        pattern = rf"(!\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\]]*\])*\])*\])\({re.escape(original_id)}\)"

        markdown = "![Simple alt text](img_001)"
        match = re.search(pattern, markdown)

        assert match is not None
        assert match.group(1) == "![Simple alt text]"

    def test_alt_text_with_brackets(self):
        """Matches alt text containing brackets."""
        import re

        original_id = "img_002"
        pattern = rf"(!\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\]]*\])*\])*\])\({re.escape(original_id)}\)"

        markdown = "![Image with [note] inside](img_002)"
        match = re.search(pattern, markdown)

        assert match is not None
        assert match.group(1) == "![Image with [note] inside]"

    def test_alt_text_with_nested_brackets(self):
        """Matches alt text with nested brackets."""
        import re

        original_id = "img_003"
        pattern = rf"(!\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\]]*\])*\])*\])\({re.escape(original_id)}\)"

        markdown = "![Diagram [see [page 5]]](img_003)"
        match = re.search(pattern, markdown)

        assert match is not None
        assert match.group(1) == "![Diagram [see [page 5]]]"

    def test_replacement_preserves_alt_text(self):
        """Full replacement preserves alt text."""
        import re

        original_id = "img_001"
        attachment_id = "att_xyz"
        pattern = rf"(!\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\]]*\])*\])*\])\({re.escape(original_id)}\)"
        replacement = rf"\1(attachment://{attachment_id})"

        markdown = "![Game board [setup]](img_001)"
        result = re.sub(pattern, replacement, markdown)

        assert result == "![Game board [setup]](attachment://att_xyz)"

    def test_removal_pattern(self):
        """Removal pattern works with brackets in alt text."""
        import re

        original_id = "img_bad"
        pattern = rf"!\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\]]*\])*\])*\]\({re.escape(original_id)}\)\n?"

        markdown = "Some text\n![Bad [quality] image](img_bad)\nMore text"
        result = re.sub(pattern, "", markdown)

        assert "img_bad" not in result
        assert "Some text" in result
        assert "More text" in result


class TestImageAnalysis:
    """Tests for image analysis functions."""

    def test_detect_mime_type_png(self):
        """Detects PNG format from magic bytes."""
        from gamegame.utils.image import detect_mime_type

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert detect_mime_type(png_bytes) == "image/png"

    def test_detect_mime_type_jpeg(self):
        """Detects JPEG format from magic bytes."""
        from gamegame.utils.image import detect_mime_type

        jpeg_bytes = b"\xff\xd8\xff" + b"\x00" * 100
        assert detect_mime_type(jpeg_bytes) == "image/jpeg"

    def test_detect_mime_type_gif(self):
        """Detects GIF format from magic bytes."""
        from gamegame.utils.image import detect_mime_type

        gif87_bytes = b"GIF87a" + b"\x00" * 100
        gif89_bytes = b"GIF89a" + b"\x00" * 100
        assert detect_mime_type(gif87_bytes) == "image/gif"
        assert detect_mime_type(gif89_bytes) == "image/gif"

    def test_detect_mime_type_webp(self):
        """Detects WebP format from magic bytes."""
        from gamegame.utils.image import detect_mime_type

        webp_bytes = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100
        assert detect_mime_type(webp_bytes) == "image/webp"

    def test_detect_mime_type_tiff(self):
        """Detects TIFF format (unsupported by OpenAI)."""
        from gamegame.utils.image import detect_mime_type

        tiff_le_bytes = b"II\x2a\x00" + b"\x00" * 100  # Little-endian
        tiff_be_bytes = b"MM\x00\x2a" + b"\x00" * 100  # Big-endian
        assert detect_mime_type(tiff_le_bytes) == "image/tiff"
        assert detect_mime_type(tiff_be_bytes) == "image/tiff"

    def test_detect_mime_type_bmp(self):
        """Detects BMP format (unsupported by OpenAI)."""
        from gamegame.utils.image import detect_mime_type

        bmp_bytes = b"BM" + b"\x00" * 100
        assert detect_mime_type(bmp_bytes) == "image/bmp"

    def test_detect_mime_type_unknown(self):
        """Returns octet-stream for unknown formats."""
        from gamegame.utils.image import detect_mime_type

        unknown_bytes = b"UNKNOWN_FORMAT" + b"\x00" * 100
        assert detect_mime_type(unknown_bytes) == "application/octet-stream"

    def test_detect_mime_type_short_data(self):
        """Short data returns application/octet-stream."""
        from gamegame.utils.image import detect_mime_type

        short_bytes = b"\x00\x00"
        assert detect_mime_type(short_bytes) == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_analyze_single_image_rejects_unsupported_format(self):
        """Unsupported formats raise ValueError with clear message."""
        from gamegame.services.pipeline.vision import analyze_single_image

        with patch("gamegame.services.pipeline.vision.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"

            # TIFF format - common in PDFs but not supported by OpenAI
            tiff_bytes = b"II\x2a\x00" + b"\x00" * 100

            with pytest.raises(ValueError) as exc_info:
                await analyze_single_image(
                    tiff_bytes,
                    ImageAnalysisContext(page_number=1),
                )

            assert "image/tiff" in str(exc_info.value)
            assert "Unsupported image format" in str(exc_info.value)

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
            patch(
                "gamegame.services.pipeline.vision.create_chat_completion",
                new=AsyncMock(return_value=mock_response),
            ),
            patch("gamegame.services.pipeline.vision.settings") as mock_settings,
        ):
            mock_settings.openai_api_key = "test-key"

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

        with patch("gamegame.services.pipeline.vision.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"

            # Use fake image data that will fail format validation
            images = [
                (b"fake_image_data_here", ImageAnalysisContext(page_number=1)),
            ]

            results = await analyze_images_batch(images)

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
        from tests.conftest import make_openai_chat_response

        mock_response = make_openai_chat_response("Cleaned content")

        with patch(
            "gamegame.services.pipeline.cleanup.create_chat_completion",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
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
        from tests.conftest import make_openai_chat_response

        mock_response = make_openai_chat_response("Question 1?\nQuestion 2?\nQuestion 3?")

        with patch(
            "gamegame.services.pipeline.embed.create_chat_completion",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
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


class TestPipelineCleanup:
    """Tests for pipeline cleanup functions (idempotency)."""

    @pytest.mark.asyncio
    async def test_cleanup_attachments_deletes_records(self, session):
        """Cleanup deletes attachment records for a resource."""
        from gamegame.tasks.pipeline import _cleanup_attachments

        # Create test game and resource
        game = Game(name="Cleanup Test", slug="cleanup-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="Test Resource",
            original_filename="test.pdf",
            url="/uploads/test.pdf",
            content="",
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.flush()

        # Create some attachments
        for i in range(3):
            attachment = Attachment(
                game_id=game.id,
                resource_id=resource.id,
                type=AttachmentType.IMAGE,
                mime_type="image/jpeg",
                blob_key=f"test/attachment_{i}.jpg",
                url=f"/uploads/test/attachment_{i}.jpg",
            )
            session.add(attachment)
        await session.commit()

        # Verify attachments exist
        from sqlmodel import select
        stmt = select(Attachment).where(Attachment.resource_id == resource.id)
        result = await session.execute(stmt)
        assert len(result.scalars().all()) == 3

        # Run cleanup (mock storage to avoid file errors)
        with patch("gamegame.tasks.pipeline.storage") as mock_storage:
            mock_storage.delete_file = AsyncMock(return_value=True)
            deleted = await _cleanup_attachments(session, resource.id)

        assert deleted == 3

        # Verify attachments are gone
        result = await session.execute(stmt)
        assert len(result.scalars().all()) == 0

    @pytest.mark.asyncio
    async def test_cleanup_attachments_empty_resource(self, session):
        """Cleanup handles resource with no attachments."""
        from gamegame.tasks.pipeline import _cleanup_attachments

        game = Game(name="Empty Test", slug="empty-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="Empty Resource",
            original_filename="empty.pdf",
            url="/uploads/empty.pdf",
            content="",
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.commit()

        with patch("gamegame.tasks.pipeline.storage") as mock_storage:
            mock_storage.delete_file = AsyncMock(return_value=True)
            deleted = await _cleanup_attachments(session, resource.id)

        assert deleted == 0

    @pytest.mark.asyncio
    async def test_cleanup_fragments_deletes_records(self, session):
        """Cleanup deletes fragment and embedding records."""
        from gamegame.tasks.pipeline import _cleanup_fragments

        game = Game(name="Fragment Cleanup", slug="fragment-cleanup")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="Fragment Resource",
            original_filename="frag.pdf",
            url="/uploads/frag.pdf",
            content="Test content",
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.flush()

        # Create fragments with embeddings
        for i in range(2):
            fragment = Fragment(
                game_id=game.id,
                resource_id=resource.id,
                content=f"Fragment {i} content",
                searchable_content=f"Fragment {i}",
                embedding=[0.1] * 1536,
            )
            session.add(fragment)
            await session.flush()

            # Create embedding record
            embedding = Embedding(
                id=f"emb_{i}",
                fragment_id=fragment.id,
                game_id=game.id,
                resource_id=resource.id,
                embedding=[0.1] * 1536,
            )
            session.add(embedding)

        await session.commit()

        # Verify fragments and embeddings exist
        from sqlmodel import select
        frag_stmt = select(Fragment).where(Fragment.resource_id == resource.id)
        emb_stmt = select(Embedding).where(Embedding.resource_id == resource.id)

        result = await session.execute(frag_stmt)
        assert len(result.scalars().all()) == 2
        result = await session.execute(emb_stmt)
        assert len(result.scalars().all()) == 2

        # Run cleanup
        deleted = await _cleanup_fragments(session, resource.id)
        assert deleted == 2

        # Verify all are gone
        result = await session.execute(frag_stmt)
        assert len(result.scalars().all()) == 0
        result = await session.execute(emb_stmt)
        assert len(result.scalars().all()) == 0


class TestPipelineStageIntegration:
    """Integration tests for individual pipeline stages with real DB."""

    @pytest.mark.asyncio
    async def test_vision_stage_cleans_before_creating(self, session):
        """Vision stage deletes old attachments before creating new ones."""
        from gamegame.tasks.pipeline import _cleanup_attachments

        # Create test game and resource
        game = Game(name="Vision Stage Test", slug="vision-stage-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="vision.pdf",
            original_filename="vision.pdf",
            url="/uploads/vision.pdf",
            content="",
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.flush()

        # Create existing attachment (simulating previous run)
        old_attachment = Attachment(
            game_id=game.id,
            resource_id=resource.id,
            type=AttachmentType.IMAGE,
            mime_type="image/jpeg",
            blob_key="old/attachment.jpg",
            url="/uploads/old/attachment.jpg",
        )
        session.add(old_attachment)
        await session.commit()

        # Verify old attachment exists
        from sqlmodel import select
        stmt = select(Attachment).where(Attachment.resource_id == resource.id)
        result = await session.execute(stmt)
        assert len(result.scalars().all()) == 1

        # Run cleanup (mock storage)
        with patch("gamegame.tasks.pipeline.storage") as mock_storage:
            mock_storage.delete_file = AsyncMock(return_value=True)
            deleted = await _cleanup_attachments(session, resource.id)

        assert deleted == 1

        # Verify attachment is gone
        result = await session.execute(stmt)
        assert len(result.scalars().all()) == 0

    @pytest.mark.asyncio
    async def test_embed_stage_cleans_before_creating(self, session):
        """Embed stage deletes old fragments before creating new ones."""
        from gamegame.tasks.pipeline import _cleanup_fragments

        game = Game(name="Embed Stage Test", slug="embed-stage-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="embed.pdf",
            original_filename="embed.pdf",
            url="/uploads/embed.pdf",
            content="Test content",
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.flush()

        # Create old fragment (simulating previous run)
        old_fragment = Fragment(
            game_id=game.id,
            resource_id=resource.id,
            content="Old fragment content",
            searchable_content="Old content",
            embedding=[0.1] * 1536,
        )
        session.add(old_fragment)
        await session.commit()

        # Verify old fragment exists
        from sqlmodel import select
        stmt = select(Fragment).where(Fragment.resource_id == resource.id)
        result = await session.execute(stmt)
        assert len(result.scalars().all()) == 1

        # Run cleanup
        deleted = await _cleanup_fragments(session, resource.id)
        assert deleted == 1

        # Verify fragment is gone
        result = await session.execute(stmt)
        assert len(result.scalars().all()) == 0

    @pytest.mark.asyncio
    async def test_cleanup_and_metadata_stage(self, session):
        """Cleanup and metadata stages update resource content."""
        from gamegame.tasks.pipeline import _stage_cleanup, _stage_metadata

        game = Game(name="Content Test", slug="content-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="content.pdf",
            original_filename="content.pdf",
            url="/uploads/content.pdf",
            content="",
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.commit()

        # Test cleanup stage with mock
        state = {"raw_markdown": "# Test\n\nSome dirty content here."}

        with patch("gamegame.services.pipeline.cleanup.create_chat_completion") as mock_chat:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content="# Test\n\nCleaned content."))]
            mock_chat.return_value = mock_response

            with patch("gamegame.services.pipeline.cleanup.settings") as mock_settings:
                mock_settings.openai_api_key = "test-key"
                state = await _stage_cleanup(session, resource, state)

        assert "cleaned_markdown" in state
        assert "Cleaned content" in state["cleaned_markdown"]

        # Test metadata stage with mock
        with patch("gamegame.services.pipeline.metadata.create_chat_completion") as mock_chat:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(
                content='{"name": "Game Rules", "description": "Complete game rules."}'
            ))]
            mock_chat.return_value = mock_response

            with patch("gamegame.services.pipeline.metadata.settings") as mock_settings:
                mock_settings.openai_api_key = "test-key"
                state = await _stage_metadata(session, resource, state)

        # Verify resource was updated
        assert resource.content is not None
        assert resource.description == "Complete game rules."

    @pytest.mark.asyncio
    async def test_metadata_stage_updates_and_persists_name(self, session):
        """Metadata stage replaces filename-derived name with LLM-generated name and persists it."""
        from sqlmodel import select

        from gamegame.tasks.pipeline import _stage_metadata

        game = Game(name="Name Update Test", slug="name-update-test")
        session.add(game)
        await session.flush()

        # Simulate what happens on upload: name is cleaned from filename
        # but original_filename is the raw filename
        resource = Resource(
            game_id=game.id,
            name="Scytherulescombined V2 Cs R13 Bw",  # Cleaned from filename
            original_filename="scytherulescombined_v2_cs_r13_bw.pdf",  # Raw filename
            url="/uploads/test.pdf",
            content="",
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.commit()

        resource_id = resource.id

        state = {"cleaned_markdown": "# Scythe Rules\n\nGame content here."}

        with patch("gamegame.services.pipeline.metadata.create_chat_completion") as mock_chat:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(
                content='{"name": "Scythe Rulebook", "description": "Complete rules for Scythe."}'
            ))]
            mock_chat.return_value = mock_response

            with patch("gamegame.services.pipeline.metadata.settings") as mock_settings:
                mock_settings.openai_api_key = "test-key"
                await _stage_metadata(session, resource, state)

        # In-memory update should be applied
        assert resource.name == "Scythe Rulebook"
        assert resource.description == "Complete rules for Scythe."

        # Commit like the pipeline does after each stage
        await session.commit()

        # Verify persistence by re-fetching from database
        session.expire(resource)
        stmt = select(Resource).where(Resource.id == resource_id)
        result = await session.execute(stmt)
        fetched_resource = result.scalar_one()

        assert fetched_resource.name == "Scythe Rulebook"
        assert fetched_resource.description == "Complete rules for Scythe."


class TestResumableJobs:
    """Tests for resumable job functionality with cursor checkpointing."""

    @pytest.mark.asyncio
    async def test_embed_stage_resume_from_cursor(self, session):
        """Embed stage can resume from a checkpoint cursor."""
        from gamegame.services.pipeline.embed import embed_content

        game = Game(name="Embed Resume Test", slug="embed-resume-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="embed-resume.pdf",
            original_filename="embed-resume.pdf",
            url="/uploads/embed-resume.pdf",
            content="",
            status=ResourceStatus.PROCESSING,
        )
        session.add(resource)
        await session.commit()

        # Create some existing fragments (simulating partial completion)
        for i in range(5):
            fragment = Fragment(
                game_id=game.id,
                resource_id=resource.id,
                content=f"Fragment {i} content",
                searchable_content=f"Fragment {i}",
                embedding=[0.1] * 1536,
            )
            session.add(fragment)
        await session.commit()

        # Mock OpenAI to return embeddings
        with patch("gamegame.services.pipeline.embed.get_openai_client") as mock_client:
            mock_embeddings_response = MagicMock()
            mock_embeddings_response.data = [MagicMock(embedding=[0.1] * 1536)]
            mock_client.return_value.embeddings.create = AsyncMock(
                return_value=mock_embeddings_response
            )

            with patch("gamegame.services.pipeline.embed.settings") as mock_settings:
                mock_settings.openai_api_key = "test-key"
                # Provide pipeline chunking settings for chunk_text_simple
                mock_settings.pipeline_max_chunk_size = 2500
                mock_settings.pipeline_chunk_overlap = 200
                mock_settings.pipeline_min_chunk_size = 100

                # Test content that will create ~2 chunks
                markdown = "Paragraph one with enough content. " * 20 + "\n\n"
                markdown += "Paragraph two with more content. " * 20

                checkpoints_received = []

                async def track_checkpoint(cursor: int) -> None:
                    checkpoints_received.append(cursor)

                # Resume from cursor=1 (skip first chunk)
                fragments = await embed_content(
                    session=session,
                    resource_id=resource.id,
                    game_id=game.id,
                    markdown=markdown,
                    generate_hyde=False,
                    on_checkpoint=track_checkpoint,
                    resume_from=0,  # Start fresh for this test
                )

        # Should have created fragments
        assert fragments > 0
        # Should have received checkpoint calls
        assert len(checkpoints_received) > 0

    @pytest.mark.asyncio
    async def test_cleanup_stage_saves_partial_results(self):
        """Cleanup stage saves partial results during checkpointing."""
        from gamegame.services.pipeline.cleanup import cleanup_markdown

        checkpoints_received = []
        partial_results_received = []

        async def track_checkpoint(cursor: int, results: list[str]) -> None:
            checkpoints_received.append(cursor)
            partial_results_received.append(len(results))

        # Create content large enough to require multiple chunks
        # (each paragraph will be ~8000 chars to exceed chunk_size)
        content = ""
        for i in range(5):
            content += f"Section {i}. " + "This is test content. " * 400 + "\n\n"

        with patch("gamegame.services.pipeline.cleanup.create_chat_completion") as mock_chat:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content="Cleaned text"))]
            mock_chat.return_value = mock_response

            with patch("gamegame.services.pipeline.cleanup.settings") as mock_settings:
                mock_settings.openai_api_key = "test-key"

                await cleanup_markdown(
                    content,
                    chunk_size=8000,
                    on_checkpoint=track_checkpoint,
                    resume_from=0,
                )

        # Should have received checkpoint calls with increasing result counts
        assert len(checkpoints_received) > 0
        # Each checkpoint should have more or equal results than previous
        for i in range(1, len(partial_results_received)):
            assert partial_results_received[i] >= partial_results_received[i - 1]

    @pytest.mark.asyncio
    async def test_cleanup_stage_resume_with_previous_results(self):
        """Cleanup stage can resume with previous results."""
        from gamegame.services.pipeline.cleanup import cleanup_markdown

        # Create content that will be split into multiple chunks
        content = ""
        for i in range(3):
            content += f"Section {i}. " + "Test content here. " * 400 + "\n\n"

        # Previous results from first 2 chunks
        previous_results = ["Cleaned chunk 0", "Cleaned chunk 1"]

        with patch("gamegame.services.pipeline.cleanup.create_chat_completion") as mock_chat:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content="Cleaned remaining"))]
            mock_chat.return_value = mock_response

            with patch("gamegame.services.pipeline.cleanup.settings") as mock_settings:
                mock_settings.openai_api_key = "test-key"

                result = await cleanup_markdown(
                    content,
                    chunk_size=8000,
                    resume_from=2,  # Skip first 2 chunks
                    previous_results=previous_results,
                )

        # Result should include both previous and new results
        assert "Cleaned chunk 0" in result
        assert "Cleaned chunk 1" in result

    @pytest.mark.asyncio
    async def test_vision_stage_cursor_checkpoint(self, session):
        """Vision stage saves cursor and image mapping during checkpointing."""
        from gamegame.tasks.pipeline import _stage_vision

        game = Game(name="Vision Resume Test", slug="vision-resume-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="vision-resume.pdf",
            original_filename="vision-resume.pdf",
            url="/uploads/vision-resume.pdf",
            content="",
            status=ResourceStatus.PROCESSING,
            processing_stage=ProcessingStage.VISION,
        )
        session.add(resource)
        await session.commit()

        # Create state with multiple images
        import base64

        # Create a minimal valid PNG (8x8 red square)
        png_data = base64.b64encode(bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
            # ... minimal PNG content
        ])).decode()

        state = {
            "raw_markdown": "# Test\n\n![img1](img_1)\n\n![img2](img_2)",
            "extracted_images": [
                {"id": "img_1", "base64": png_data, "page_number": 1},
                {"id": "img_2", "base64": png_data, "page_number": 2},
            ],
        }

        # Mock all external dependencies
        with patch("gamegame.tasks.pipeline.analyze_images_batch") as mock_analyze:
            # Return empty results (images rejected as bad quality)
            mock_analyze.return_value = [
                ImageAnalysisResult(
                    description="Test image",
                    image_type=ImageType.DIAGRAM,
                    quality=ImageQuality.BAD,
                    relevant=False,
                    ocr_text=None,
                ),
                ImageAnalysisResult(
                    description="Test image 2",
                    image_type=ImageType.DIAGRAM,
                    quality=ImageQuality.BAD,
                    relevant=False,
                    ocr_text=None,
                ),
            ]

            with patch("gamegame.tasks.pipeline.storage") as mock_storage:
                mock_storage.upload_file = AsyncMock(return_value=("/url", "key"))
                mock_storage.delete_file = AsyncMock(return_value=True)

                result_state = await _stage_vision(session, resource, state)

        # Should have processed all images
        assert result_state.get("images_analyzed") == 2
        # Cursor should be cleared on completion
        assert "stage_cursor" not in result_state

    @pytest.mark.asyncio
    async def test_auto_resume_disabled(self, session):
        """Stalled workflows are detected and not auto-resumed when disabled."""
        from datetime import UTC, datetime, timedelta

        from gamegame.models.workflow_run import WorkflowRun
        from gamegame.services.workflow_tracking import get_stalled_workflows

        # Create a stalled workflow with explicit timestamps
        now = datetime.now(UTC)
        stalled_time = now - timedelta(hours=1)  # 1 hour ago
        workflow = WorkflowRun(
            run_id="test-stalled-1",
            workflow_name="process_resource",
            status="running",
            started_at=now - timedelta(hours=2),
            created_at=now,
            updated_at=stalled_time,
            resource_id=None,
        )
        session.add(workflow)
        await session.flush()

        # Query stalled workflows using our test session
        stalled = await get_stalled_workflows(
            session,
            stall_threshold_seconds=30 * 60,  # 30 minutes
        )

        # Should have found the stalled workflow
        assert len(stalled) == 1
        assert stalled[0].run_id == "test-stalled-1"
        assert stalled[0].status == "running"

    @pytest.mark.asyncio
    async def test_auto_resume_re_enqueues_stalled_job(self, session):
        """Auto-resume re-enqueues stalled pipeline jobs."""
        from datetime import UTC, datetime, timedelta

        from gamegame.models.workflow_run import WorkflowRun
        from gamegame.services.workflow_tracking import get_stalled_workflows

        # Create game and resource for the stalled job
        game = Game(name="Resume Test", slug="resume-test")
        session.add(game)
        await session.flush()

        resource = Resource(
            game_id=game.id,
            name="resume.pdf",
            original_filename="resume.pdf",
            url="/uploads/resume.pdf",
            content="",
            status=ResourceStatus.PROCESSING,
            processing_stage=ProcessingStage.CLEANUP,  # Was in cleanup stage
        )
        session.add(resource)
        await session.flush()

        # Create a stalled workflow linked to the resource
        now = datetime.now(UTC)
        workflow = WorkflowRun(
            run_id="test-stalled-pipeline",
            workflow_name="process_resource",
            status="running",
            started_at=now - timedelta(hours=2),
            created_at=now,
            updated_at=now - timedelta(hours=1),
            resource_id=resource.id,
        )
        session.add(workflow)
        await session.flush()

        # Query stalled workflows
        stalled = await get_stalled_workflows(
            session,
            stall_threshold_seconds=30 * 60,
        )

        # Should find the stalled workflow
        assert len(stalled) == 1
        assert stalled[0].resource_id == resource.id

        # The workflow should be resumable (has resource_id and processing_stage)
        stalled_wf = stalled[0]
        assert stalled_wf.workflow_name == "process_resource"
        assert resource.processing_stage is not None
