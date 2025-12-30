"""EMBED stage - Chunk content and generate embeddings with enrichment."""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from gamegame.config import settings
from gamegame.constants import ANSWER_TYPES
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
    chunk_type: FragmentType = FragmentType.TEXT
    images: list[dict] = field(default_factory=list)


# Chunking parameters
MAX_CHUNK_SIZE = 2500  # Characters (larger for better section coherence)
CHUNK_OVERLAP = 200  # Characters of overlap
MIN_CHUNK_SIZE = 100  # Minimum chunk size


def chunk_text_simple(
    markdown: str,
    max_size: int = MAX_CHUNK_SIZE,
    _overlap: int = CHUNK_OVERLAP,  # Reserved for future overlap implementation
) -> list[Chunk]:
    """Split markdown text into chunks using simple paragraph-based approach.

    Args:
        markdown: Markdown text to chunk
        max_size: Maximum chunk size in characters
        overlap: Overlap between chunks

    Returns:
        List of Chunk objects
    """
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
        if len(text) >= MIN_CHUNK_SIZE:
            chunks.append(Chunk(content=text))

    return chunks


def chunk_structured_content(
    pages: list[dict],
    max_size: int = MAX_CHUNK_SIZE,
) -> list[Chunk]:
    """Chunk structured PDF content while preserving page/section metadata.

    Args:
        pages: List of page dicts with markdown, pageNumber, sections, images
        max_size: Maximum chunk size

    Returns:
        List of Chunk objects with metadata
    """
    all_chunks: list[Chunk] = []

    # Collect all sections for hierarchy tracking
    all_sections: list[dict] = []
    for page in pages:
        sections = page.get("sections", [])
        page_number = page.get("pageNumber", 1)
        all_sections.extend(
            {**section, "pageNumber": page_number} for section in sections
        )

    def get_current_section(page_number: int) -> str | None:
        """Get the current section hierarchy for a page."""
        relevant = [s for s in all_sections if s.get("pageNumber", 0) <= page_number]
        if not relevant:
            return None
        return relevant[-1].get("hierarchy")

    for page in pages:
        page_number = page.get("pageNumber", 1)
        markdown = page.get("markdown", "")
        page_sections = page.get("sections", [])
        page_images = page.get("images", [])

        if not markdown.strip():
            continue

        # Convert images to simple dicts
        images_data = [
            {
                "id": img.get("id"),
                "url": img.get("url"),
                "description": img.get("description"),
                "detectedType": img.get("detectedType"),
                "ocrText": img.get("ocrText"),
            }
            for img in page_images
            if img.get("url")
        ]

        # Small page - keep as one chunk
        if len(markdown) < max_size and len(page_sections) <= 1:
            section = get_current_section(page_number)
            all_chunks.append(Chunk(
                content=markdown.strip(),
                page_number=page_number,
                section=section,
                images=images_data,
            ))
            continue

        # Larger page - split by sections if available
        if page_sections:
            # Split content by section headings
            for i, section in enumerate(page_sections):
                section_text = section.get("text", "")
                section_level = section.get("level", 1)
                section_hierarchy = section.get("hierarchy", section_text)

                # Find section in markdown
                heading_pattern = rf"^#{{{section_level}}}\s+{re.escape(section_text)}"
                match = re.search(heading_pattern, markdown, re.MULTILINE)

                if match:
                    start = match.start()
                    # Find next section
                    end = len(markdown)
                    if i + 1 < len(page_sections):
                        next_section = page_sections[i + 1]
                        next_pattern = rf"^#{{{next_section.get('level', 1)}}}\s+{re.escape(next_section.get('text', ''))}"
                        next_match = re.search(next_pattern, markdown[start + 1:], re.MULTILINE)
                        if next_match:
                            end = start + 1 + next_match.start()

                    section_content = markdown[start:end].strip()
                    if section_content:
                        # Split if still too large
                        if len(section_content) > max_size:
                            sub_chunks = chunk_text_simple(section_content, max_size)
                            for sub in sub_chunks:
                                sub.page_number = page_number
                                sub.section = section_hierarchy
                                sub.images = images_data
                                all_chunks.append(sub)
                        else:
                            all_chunks.append(Chunk(
                                content=section_content,
                                page_number=page_number,
                                section=section_hierarchy,
                                images=images_data,
                            ))
        else:
            # No sections - use simple chunking
            section = get_current_section(page_number)
            sub_chunks = chunk_text_simple(markdown, max_size)
            for sub in sub_chunks:
                sub.page_number = page_number
                sub.section = section
                sub.images = images_data
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


async def classify_fragment_answer_types(
    content: str,
    section: str | None,
    resource_info: ResourceInfo,
) -> list[str]:
    """Classify what types of questions a fragment can answer.

    Args:
        content: Fragment content
        section: Section name
        resource_info: Resource metadata

    Returns:
        List of answer type strings
    """
    if not settings.openai_api_key:
        return []

    prompt = f"""Analyze this content from a board game {resource_info.resource_type} and classify what types of questions it can answer.

Document: {resource_info.name}
{f'Description: {resource_info.description}' if resource_info.description else ''}
{f'Section: {section}' if section else ''}

Content:
{content[:2000]}

Available answer type categories:

**Metadata:**
- player_count, play_time, age_rating, game_overview, publisher_info

**Rules:**
- setup_instructions, turn_structure, win_conditions, end_game, scoring

**Components:**
- component_list, card_types, resource_types, board_layout, token_types

**Gameplay:**
- action_options, combat_rules, movement_rules, trading_rules, special_abilities

**Clarifications:**
- edge_case, example, faq, timing, rule_clarification

Select 1-4 answer types that best match what questions this content can answer.
Return ONLY a JSON object with an "answerTypes" array.
Format: {{ "answerTypes": ["type1", "type2", ...] }}"""

    try:
        response = await create_chat_completion(
            model=get_model("classification"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=1,  # GPT-5/GPT-4o-mini requires temperature 1
            max_completion_tokens=200,
        )

        content_str = response.choices[0].message.content
        if not content_str:
            return []

        result = json.loads(content_str)
        if not isinstance(result.get("answerTypes"), list):
            return []

        return [t for t in result["answerTypes"] if t in ANSWER_TYPES]
    except Exception:
        return []


async def classify_fragments_batch(
    chunks: list[Chunk],
    resource_info: ResourceInfo,
    batch_size: int = 5,
) -> list[list[str]]:
    """Batch classify answer types for multiple fragments.

    Args:
        chunks: Chunks to classify
        resource_info: Resource metadata
        batch_size: Parallel batch size

    Returns:
        List of answer type lists (one per chunk)
    """
    results: list[list[str]] = []
    total = len(chunks)
    total_batches = (total + batch_size - 1) // batch_size

    logger.info(f"Classifying answer types: {total} chunks in {total_batches} batches")

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        batch_num = i // batch_size + 1

        logger.info(f"Classification batch {batch_num}/{total_batches} ({len(batch)} chunks)")

        batch_results = await asyncio.gather(*[
            classify_fragment_answer_types(
                chunk.content,
                chunk.section,
                resource_info,
            )
            for chunk in batch
        ])

        results.extend(batch_results)

        # Small delay between batches
        if i + batch_size < len(chunks):
            await asyncio.sleep(0.1)

    logger.info(f"Completed answer type classification: {total} chunks")
    return results


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
    batch_size: int = 5,
    num_questions: int = 5,
) -> list[list[str]]:
    """Batch generate HyDE questions for multiple chunks.

    Args:
        chunks: Chunks to generate questions for
        resource_info: Resource metadata
        batch_size: Parallel batch size
        num_questions: Questions per chunk

    Returns:
        List of question lists (one per chunk)
    """
    results: list[list[str]] = []
    total = len(chunks)
    total_batches = (total + batch_size - 1) // batch_size

    logger.info(f"Generating HyDE questions: {total} chunks in {total_batches} batches")

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        batch_num = i // batch_size + 1

        logger.info(f"HyDE batch {batch_num}/{total_batches} ({len(batch)} chunks)")

        batch_results = await asyncio.gather(*[
            generate_hyde_questions(
                chunk.content,
                chunk.section,
                resource_info,
                num_questions,
            )
            for chunk in batch
        ])

        results.extend(batch_results)

        # Small delay between batches
        if i + batch_size < len(chunks):
            await asyncio.sleep(0.1)

    logger.info(f"Completed HyDE question generation: {total} chunks")
    return results


# Batch size for resumable processing
EMBED_BATCH_SIZE = 15


async def embed_content(
    session: AsyncSession,
    resource_id: str,
    game_id: str,
    markdown: str,
    resource_info: ResourceInfo | None = None,
    structured_pages: list[dict] | None = None,
    generate_hyde: bool = True,
    classify_answer_types: bool = True,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    on_checkpoint: Callable[[int], Awaitable[None]] | None = None,
    resume_from: int = 0,
) -> int:
    """Chunk content, generate embeddings, and store fragments.

    Processes chunks in batches for resumability. Each batch generates
    questions/embeddings and creates fragments before checkpointing.

    Args:
        session: Database session
        resource_id: Resource ID
        game_id: Game ID
        markdown: Cleaned markdown content (fallback if no structured pages)
        resource_info: Resource metadata for enrichment
        structured_pages: Structured PDF pages with sections/images
        generate_hyde: Whether to generate HyDE questions
        classify_answer_types: Whether to classify answer types
        on_progress: Callback for progress updates (current, total)
        on_checkpoint: Callback for checkpointing after each batch (cursor)
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

    # Chunk the content
    if structured_pages:
        chunks = chunk_structured_content(structured_pages)
    else:
        chunks = chunk_text_simple(markdown)

    if not chunks:
        logger.info(f"Resource {resource_id}: No chunks to embed")
        return 0

    logger.info(f"Resource {resource_id}: Created {len(chunks)} chunks from content")

    if resume_from > 0:
        logger.info(f"Resource {resource_id}: Resuming from chunk {resume_from}")

    # Track total fragments created (including already-created from resume)
    fragments_created = resume_from

    # Process chunks in batches
    for batch_start in range(resume_from, len(chunks), EMBED_BATCH_SIZE):
        batch_end = min(batch_start + EMBED_BATCH_SIZE, len(chunks))
        batch_chunks = chunks[batch_start:batch_end]

        logger.info(
            f"Resource {resource_id}: Processing batch {batch_start}-{batch_end} "
            f"of {len(chunks)} chunks"
        )

        # Generate HyDE questions for this batch
        if generate_hyde:
            batch_hyde_questions = await generate_hyde_questions_batch(
                batch_chunks, resource_info, batch_size=5, num_questions=5
            )
        else:
            batch_hyde_questions = [[] for _ in batch_chunks]

        # Classify answer types for this batch
        if classify_answer_types:
            batch_answer_types = await classify_fragments_batch(
                batch_chunks, resource_info, batch_size=5
            )
        else:
            batch_answer_types = [[] for _ in batch_chunks]

        # Build searchable content for this batch
        batch_searchable = [
            build_searchable_content(chunk, resource_info)
            for chunk in batch_chunks
        ]

        # Prepare texts to embed for this batch
        texts_to_embed: list[str] = []
        embedding_map: list[dict] = []

        for i, (chunk, questions, searchable) in enumerate(
            zip(batch_chunks, batch_hyde_questions, batch_searchable, strict=True)
        ):
            # Add searchable content embedding
            texts_to_embed.append(searchable)
            embedding_map.append({"batch_idx": i, "type": "content"})

            # Add question embeddings
            for q_idx, question in enumerate(questions):
                texts_to_embed.append(question)
                embedding_map.append({
                    "batch_idx": i, "type": "question", "q_idx": q_idx, "text": question
                })

        # Generate embeddings for this batch
        batch_embeddings = await generate_embeddings(texts_to_embed)

        # Create fragments for this batch
        for batch_idx, chunk in enumerate(batch_chunks):
            # Find content embedding
            content_embedding = None
            for emb_idx, mapping in enumerate(embedding_map):
                if mapping["batch_idx"] == batch_idx and mapping["type"] == "content":
                    content_embedding = batch_embeddings[emb_idx]
                    break

            if content_embedding is None:
                continue

            # Create fragment
            fragment = Fragment(
                game_id=game_id,
                resource_id=resource_id,
                content=chunk.content,
                searchable_content=batch_searchable[batch_idx],
                type=chunk.chunk_type,
                page_number=chunk.page_number,
                page_range=chunk.page_range,
                section=chunk.section,
                embedding=content_embedding,
                synthetic_questions=batch_hyde_questions[batch_idx] if batch_hyde_questions[batch_idx] else None,
                answer_types=batch_answer_types[batch_idx] if batch_answer_types[batch_idx] else None,
                images=chunk.images if chunk.images else None,
                resource_name=resource_info.name,
                resource_description=resource_info.description,
                resource_type=resource_info.resource_type,
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
            for emb_idx, mapping in enumerate(embedding_map):
                if mapping["batch_idx"] == batch_idx and mapping["type"] == "question":
                    q_idx = mapping["q_idx"]
                    q_text = mapping["text"]
                    q_embedding = batch_embeddings[emb_idx]

                    hyde_emb_record = Embedding(
                        id=f"{fragment.id}-q{q_idx}",
                        fragment_id=fragment.id,
                        game_id=game_id,
                        resource_id=resource_id,
                        embedding=q_embedding,
                        type=EmbeddingType.QUESTION,
                        question_index=q_idx,
                        question_text=q_text,
                        page_number=chunk.page_number,
                        section=chunk.section,
                        fragment_type=chunk.chunk_type.value,
                        version=1,
                    )
                    session.add(hyde_emb_record)

            fragments_created += 1

            # Report progress
            if on_progress:
                await on_progress(fragments_created, len(chunks))

        # Checkpoint after each batch
        if on_checkpoint:
            await on_checkpoint(batch_end)

        logger.info(
            f"Resource {resource_id}: Completed batch, "
            f"{fragments_created}/{len(chunks)} fragments created"
        )

    logger.info(f"Resource {resource_id}: Completed embedding, {fragments_created} fragments created")
    return fragments_created
