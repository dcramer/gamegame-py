"""EMBED stage - Chunk content and generate embeddings with enrichment."""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from gamegame.config import settings
from gamegame.models import Embedding, Fragment, Resource
from gamegame.models.embedding import EmbeddingType
from gamegame.models.fragment import FragmentType
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import create_chat_completion, get_openai_client


@dataclass
class ResourceInfo:
    """Resource metadata for searchable content."""

    name: str
    original_filename: str | None = None
    description: str | None = None
    resource_type: str = "rulebook"


@dataclass
class Chunk:
    """A chunk of content to embed."""

    content: str
    page_number: int | None = None
    page_range: list[int] | None = None
    section: str | None = None
    segment_id: str | None = None
    chunk_type: FragmentType = FragmentType.TEXT
    images: list[dict] = field(default_factory=list)


# Chunking parameters are configured via settings.pipeline_max_chunk_size, etc.


def chunk_text_simple(
    markdown: str,
    max_size: int | None = None,
    _overlap: int | None = None,  # Reserved for future overlap implementation
) -> list[Chunk]:
    """Split markdown text into chunks using simple paragraph-based approach.

    Uses settings for defaults if not provided.

    Args:
        markdown: Markdown text to chunk
        max_size: Maximum chunk size in characters
        overlap: Overlap between chunks

    Returns:
        List of Chunk objects
    """
    # Apply settings defaults
    if max_size is None:
        max_size = settings.pipeline_max_chunk_size
    if _overlap is None:
        _overlap = settings.pipeline_chunk_overlap

    if not markdown.strip():
        return []

    # Split into paragraphs
    paragraphs = re.split(r"\n\n+", markdown)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[Chunk] = []
    current_chunk: list[str] = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)

        # If paragraph alone exceeds max size, split it
        if para_size > max_size:
            # Flush current chunk first
            if current_chunk:
                chunks.append(Chunk(content="\n\n".join(current_chunk)))
                current_chunk = []
                current_size = 0

            # Split large paragraph by sentences
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sentence in sentences:
                if current_size + len(sentence) > max_size and current_chunk:
                    chunks.append(Chunk(content=" ".join(current_chunk)))
                    current_chunk = []
                    current_size = 0
                current_chunk.append(sentence)
                current_size += len(sentence)

        # If adding paragraph exceeds max, flush and start new
        elif current_size + para_size + 2 > max_size:
            if current_chunk:
                chunks.append(Chunk(content="\n\n".join(current_chunk)))
            current_chunk = [para]
            current_size = para_size

        # Otherwise add to current chunk
        else:
            current_chunk.append(para)
            current_size += para_size + 2

    # Don't forget the last chunk
    if current_chunk:
        text = "\n\n".join(current_chunk)
        if len(text) >= settings.pipeline_min_chunk_size:
            chunks.append(Chunk(content=text))

    return chunks


def chunk_segments(
    segments: list,  # list[SegmentData] - avoid import cycle
    max_size: int | None = None,
) -> list[Chunk]:
    """Chunk segments while preserving segment metadata for parent document retrieval.

    Uses settings for defaults if not provided.

    Args:
        segments: List of SegmentData from segment extraction
        max_size: Maximum chunk size in characters

    Returns:
        List of Chunk objects with segment_id for linking
    """
    # Apply settings defaults
    if max_size is None:
        max_size = settings.pipeline_max_chunk_size

    all_chunks: list[Chunk] = []

    for segment in segments:
        content = segment.content
        segment_id = segment.id
        hierarchy_path = segment.hierarchy_path
        page_start = segment.page_start
        page_end = segment.page_end

        # Build page_range if we have both start and end
        page_range = None
        if page_start and page_end and page_end != page_start:
            page_range = [page_start, page_end]

        if len(content) <= max_size:
            # Segment fits in one chunk
            all_chunks.append(Chunk(
                content=content,
                section=hierarchy_path,
                segment_id=segment_id,
                page_number=page_start,
                page_range=page_range,
            ))
        else:
            # Split large segment into sub-chunks
            sub_chunks = chunk_text_simple(content, max_size)
            for sub in sub_chunks:
                sub.section = hierarchy_path
                sub.segment_id = segment_id
                sub.page_number = page_start
                sub.page_range = page_range
                all_chunks.append(sub)

    return all_chunks


def build_searchable_content(
    chunk: Chunk,
    resource_info: ResourceInfo,
) -> str:
    """Build enriched searchable content for embedding.

    Creates a multi-section format:
    1. Document context (title, type, description)
    2. Location context (page, section)
    3. Visual elements context (images with descriptions)
    4. Main content

    Args:
        chunk: The chunk to enrich
        resource_info: Resource metadata

    Returns:
        Enriched content string for embedding
    """
    parts: list[str] = []

    # Document context
    parts.append("--- DOCUMENT CONTEXT ---")
    parts.append(f"Title: {resource_info.name}")
    if resource_info.original_filename:
        parts.append(f"Filename: {resource_info.original_filename}")
    if resource_info.description:
        parts.append(f"Description: {resource_info.description}")
    parts.append(f"Type: {resource_info.resource_type}")
    parts.append("")

    # Location context
    if chunk.page_number or chunk.section:
        parts.append("--- LOCATION ---")
        if chunk.page_number:
            parts.append(f"Page: {chunk.page_number}")
        if chunk.section:
            parts.append(f"Section: {chunk.section}")
        parts.append("")

    # Visual elements context
    if chunk.images:
        parts.append("--- VISUAL ELEMENTS ---")
        for i, img in enumerate(chunk.images):
            desc = img.get("description", "(no description)")
            parts.append(f"Image {i + 1}: {desc}")
            if img.get("detectedType"):
                parts.append(f"  Type: {img['detectedType']}")
            if img.get("ocrText"):
                ocr = img["ocrText"][:300] + "..." if len(img["ocrText"]) > 300 else img["ocrText"]
                parts.append(f"  OCR: {ocr}")
        parts.append("")

    # Main content
    parts.append("--- CONTENT ---")
    parts.append(chunk.content)

    return "\n".join(parts)


async def generate_embeddings(
    texts: list[str],
    batch_size: int = 100,
) -> list[list[float]]:
    """Generate embeddings for a list of texts using OpenAI.

    Args:
        texts: List of texts to embed
        batch_size: Number of texts per API call

    Returns:
        List of embedding vectors
    """
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    if not texts:
        return []

    client = get_openai_client()
    all_embeddings: list[list[float]] = []
    total = len(texts)
    total_batches = (total + batch_size - 1) // batch_size

    logger.info(f"Generating embeddings: {total} texts in {total_batches} batches")

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_num = i // batch_size + 1

        logger.info(f"Embedding batch {batch_num}/{total_batches} ({len(batch)} texts)")

        response = await client.embeddings.create(
            model=get_model("embedding"),
            input=batch,
        )

        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    logger.info(f"Completed embedding generation: {total} embeddings")
    return all_embeddings


async def generate_hyde_questions(
    content: str,
    section: str | None,
    resource_info: ResourceInfo,
    num_questions: int = 5,
) -> list[str]:
    """Generate hypothetical questions for HyDE embedding.

    Args:
        content: The chunk content
        section: Section name for context
        resource_info: Resource metadata
        num_questions: Number of questions to generate

    Returns:
        List of synthetic questions
    """
    if not settings.openai_api_key:
        return []

    prompt = f"""Given this excerpt from the {resource_info.resource_type} "{resource_info.name}", generate {num_questions} questions that a player might ask that this text would answer.

{f'Section: {section}' if section else ''}

Text:
\"\"\"
{content[:1500]}
\"\"\"

Generate exactly {num_questions} questions, one per line. Questions only, no numbering or extra text."""

    try:
        response = await create_chat_completion(
            model=get_model("hyde"),
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=400,
            temperature=1.0,  # GPT-5 requires temperature 1.0
        )

        text = response.choices[0].message.content or ""
        questions = [q.strip() for q in text.strip().split("\n") if q.strip()]
        return questions[:num_questions]
    except Exception:
        return []


async def generate_hyde_questions_batch(
    chunks: list[Chunk],
    resource_info: ResourceInfo,
    num_questions: int = 5,
) -> list[list[str]]:
    """Generate HyDE questions for multiple chunks sequentially.

    Args:
        chunks: Chunks to generate questions for
        resource_info: Resource metadata
        num_questions: Questions per chunk

    Returns:
        List of question lists (one per chunk)
    """
    results: list[list[str]] = []
    total = len(chunks)

    logger.info(f"Generating HyDE questions: {total} chunks")

    for idx, chunk in enumerate(chunks):
        logger.debug(f"Generating HyDE questions for chunk {idx + 1}/{total}")
        result = await generate_hyde_questions(
            chunk.content,
            chunk.section,
            resource_info,
            num_questions,
        )
        results.append(result)

    logger.info(f"Completed HyDE question generation: {total} chunks")
    return results


async def generate_segment_summary(
    content: str,
    title: str,
    hierarchy_path: str,
    resource_name: str,
) -> str | None:
    """Generate a summary for a segment optimized for retrieval matching.

    Creates a summary that describes what questions this section can answer,
    making it more likely to match user queries during search.

    Args:
        content: The segment content
        title: Segment title
        hierarchy_path: Full hierarchy path (e.g., "Setup > Board Preparation")
        resource_name: Name of the resource/rulebook

    Returns:
        Summary text (100-150 words) or None if generation fails
    """
    if not settings.openai_api_key:
        return None

    # Truncate content to fit in context
    content_truncated = content[:4000]

    prompt = f"""Summarize this section from the board game rulebook "{resource_name}". Focus on:
- What rules or mechanics are explained
- What player actions are covered
- Key terms and concepts defined
- Edge cases or special situations addressed

Write 100-150 words describing what questions this section can answer. Write in a way that would match natural player questions.

Section: {title} ({hierarchy_path})
Content:
\"\"\"
{content_truncated}
\"\"\""""

    try:
        response = await create_chat_completion(
            model=get_model("hyde"),
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=300,
            temperature=0.7,
        )

        summary = response.choices[0].message.content or ""
        return summary.strip() if summary.strip() else None
    except Exception as e:
        logger.warning(f"Failed to generate segment summary: {e}")
        return None


async def embed_segment_summaries(
    session: AsyncSession,
    resource_id: str,
    game_id: str,
    segments: list,  # list[Segment] - avoid import cycle
    resource_name: str,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> int:
    """Generate and embed summaries for segments.

    Creates summary embeddings for each segment to enable segment-level search.
    These embeddings are designed to match user queries better than chunk embeddings.

    Args:
        session: Database session
        resource_id: Resource ID
        game_id: Game ID
        segments: List of Segment objects
        resource_name: Resource name for prompt context
        on_progress: Optional callback for progress updates

    Returns:
        Number of segment embeddings created
    """
    if not segments:
        logger.info(f"Resource {resource_id}: No segments to embed summaries for")
        return 0

    logger.info(f"Resource {resource_id}: Generating summaries for {len(segments)} segments")
    embeddings_created = 0

    for idx, segment in enumerate(segments):
        logger.info(
            f"Resource {resource_id}: Processing segment {idx + 1}/{len(segments)}: {segment.title}"
        )

        # Generate summary
        summary = await generate_segment_summary(
            content=segment.content,
            title=segment.title,
            hierarchy_path=segment.hierarchy_path,
            resource_name=resource_name,
        )

        if not summary:
            logger.warning(f"Resource {resource_id}: Failed to generate summary for segment {segment.id}")
            continue

        # Generate embedding for summary
        embeddings = await generate_embeddings([summary])
        if not embeddings:
            logger.warning(f"Resource {resource_id}: Failed to generate embedding for segment {segment.id}")
            continue

        summary_embedding = embeddings[0]

        # Create segment summary embedding record
        segment_emb_record = Embedding(
            id=f"seg-{segment.id}",
            segment_id=segment.id,
            game_id=game_id,
            resource_id=resource_id,
            embedding=summary_embedding,
            type=EmbeddingType.SUMMARY,
            summary_text=summary,
            page_number=segment.page_start,
            section=segment.hierarchy_path,
            version=1,
        )
        session.add(segment_emb_record)

        # Also generate HyDE questions for the segment summary
        hyde_questions = await generate_hyde_questions(
            content=segment.content[:2000],
            section=segment.hierarchy_path,
            resource_info=ResourceInfo(name=resource_name),
            num_questions=3,  # Fewer questions per segment than per chunk
        )

        if hyde_questions:
            question_embeddings = await generate_embeddings(hyde_questions)
            for q_idx, (question, q_embedding) in enumerate(
                zip(hyde_questions, question_embeddings, strict=False)
            ):
                hyde_emb_record = Embedding(
                    id=f"seg-{segment.id}-q{q_idx}",
                    segment_id=segment.id,
                    game_id=game_id,
                    resource_id=resource_id,
                    embedding=q_embedding,
                    type=EmbeddingType.QUESTION,
                    question_index=q_idx,
                    question_text=question,
                    page_number=segment.page_start,
                    section=segment.hierarchy_path,
                    version=1,
                )
                session.add(hyde_emb_record)

        embeddings_created += 1

        if on_progress:
            await on_progress(idx + 1, len(segments))

    logger.info(f"Resource {resource_id}: Created {embeddings_created} segment summary embeddings")
    return embeddings_created


async def embed_content(
    session: AsyncSession,
    resource_id: str,
    game_id: str,
    markdown: str,
    resource_info: ResourceInfo | None = None,
    segments: list | None = None,
    generate_hyde: bool = True,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    on_checkpoint: Callable[[int], Awaitable[None]] | None = None,
    resume_from: int = 0,
) -> int:
    """Chunk content, generate embeddings, and store fragments.

    Processes chunks sequentially with per-item checkpointing for resumability.

    Args:
        session: Database session
        resource_id: Resource ID
        game_id: Game ID
        markdown: Cleaned markdown content (fallback if no segments)
        resource_info: Resource metadata for enrichment
        segments: List of SegmentData from segment extraction (preferred)
        generate_hyde: Whether to generate HyDE questions
        on_progress: Callback for progress updates (current, total)
        on_checkpoint: Callback for checkpointing after each item (cursor)
        resume_from: Chunk index to resume from (0 = start fresh)

    Returns:
        Number of fragments created
    """
    # Get resource info if not provided
    if resource_info is None:
        from sqlmodel import select
        stmt = select(Resource).where(Resource.id == resource_id)
        result = await session.execute(stmt)
        resource = result.scalar_one_or_none()
        if resource:
            resource_info = ResourceInfo(
                name=resource.name or "Unknown",
                original_filename=resource.original_filename,
                description=None,
                resource_type="rulebook",
            )
        else:
            resource_info = ResourceInfo(name="Unknown")

    # Chunk the content - prefer segments, fall back to simple text chunking
    if segments:
        chunks = chunk_segments(segments)
        logger.info(f"Resource {resource_id}: Chunking {len(segments)} segments into {len(chunks)} chunks")
    else:
        chunks = chunk_text_simple(markdown)
        logger.info(f"Resource {resource_id}: Chunking markdown into {len(chunks)} chunks (no segments)")

    if not chunks:
        logger.info(f"Resource {resource_id}: No chunks to embed")
        return 0

    logger.info(f"Resource {resource_id}: Processing {len(chunks)} chunks sequentially")

    if resume_from > 0:
        logger.info(f"Resource {resource_id}: Resuming from chunk {resume_from}")

    # Track total fragments created (including already-created from resume)
    fragments_created = resume_from

    # Process chunks sequentially with per-item checkpointing
    for idx in range(resume_from, len(chunks)):
        chunk = chunks[idx]
        chunk_chars = len(chunk.content)
        logger.info(f"Resource {resource_id}: Embedding chunk {idx + 1}/{len(chunks)} ({chunk_chars} chars)")

        # Generate HyDE questions for this chunk
        if generate_hyde:
            hyde_questions = await generate_hyde_questions(
                chunk.content,
                chunk.section,
                resource_info,
                num_questions=5,
            )
        else:
            hyde_questions = []

        # Build searchable content
        searchable = build_searchable_content(chunk, resource_info)

        # Prepare texts to embed (content + questions)
        texts_to_embed = [searchable, *hyde_questions]

        # Generate embeddings
        embeddings = await generate_embeddings(texts_to_embed)
        content_embedding = embeddings[0]
        question_embeddings = embeddings[1:] if len(embeddings) > 1 else []

        # Create fragment (embeddings stored separately in embeddings table)
        fragment = Fragment(
            game_id=game_id,
            resource_id=resource_id,
            content=chunk.content,
            searchable_content=searchable,
            type=chunk.chunk_type,
            segment_id=chunk.segment_id,
            page_number=chunk.page_number,
            page_range=chunk.page_range,
            section=chunk.section,
            synthetic_questions=hyde_questions if hyde_questions else None,
            images=chunk.images if chunk.images else None,
            version=1,
        )
        session.add(fragment)
        await session.flush()

        # Create content embedding record
        content_emb_record = Embedding(
            id=str(fragment.id),
            fragment_id=fragment.id,
            game_id=game_id,
            resource_id=resource_id,
            embedding=content_embedding,
            type=EmbeddingType.CONTENT,
            page_number=chunk.page_number,
            section=chunk.section,
            fragment_type=chunk.chunk_type.value,
            version=1,
        )
        session.add(content_emb_record)

        # Create question embedding records
        # Note: Don't use strict=True - if counts mismatch due to API issues,
        # we still want to create embeddings for the questions we have
        for q_idx, (question, q_embedding) in enumerate(
            zip(hyde_questions, question_embeddings, strict=False)
        ):
            hyde_emb_record = Embedding(
                id=f"{fragment.id}-q{q_idx}",
                fragment_id=fragment.id,
                game_id=game_id,
                resource_id=resource_id,
                embedding=q_embedding,
                type=EmbeddingType.QUESTION,
                question_index=q_idx,
                question_text=question,
                page_number=chunk.page_number,
                section=chunk.section,
                fragment_type=chunk.chunk_type.value,
                version=1,
            )
            session.add(hyde_emb_record)

        fragments_created += 1

        # Report progress and checkpoint after each item
        if on_progress:
            await on_progress(fragments_created, len(chunks))

        if on_checkpoint:
            await on_checkpoint(idx + 1)

    logger.info(f"Resource {resource_id}: Completed embedding, {fragments_created} fragments created")
    return fragments_created
