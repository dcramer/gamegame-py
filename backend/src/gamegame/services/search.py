"""Hybrid search service combining vector search and full-text search with RRF."""

import asyncio
import json
import logging
import math
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from gamegame.config import settings
from gamegame.constants import ANSWER_TYPES
from gamegame.models import Embedding, Fragment, Resource, Segment
from gamegame.models.embedding import EmbeddingType
from gamegame.models.model_config import get_model
from gamegame.services.openai_client import get_openai_client

logger = logging.getLogger(__name__)


@dataclass
class ImageMetadata:
    """Image metadata from a fragment."""

    id: str
    url: str
    bbox: list[float] | None = None
    caption: str | None = None
    description: str | None = None
    detected_type: str | None = None
    ocr_text: str | None = None
    is_relevant: bool | None = None


@dataclass
class SearchResult:
    """A single search result."""

    fragment_id: str
    content: str
    page_number: int | None
    section: str | None
    resource_id: str
    resource_name: str
    game_id: str
    score: float
    match_type: str  # 'vector', 'fts', or 'hybrid'
    images: list[ImageMetadata] | None = None
    searchable_content: str | None = None


@dataclass
class SearchResponse:
    """Response from search."""

    results: list[SearchResult]
    query: str
    game_id: str | None
    answer_types: list[str] | None = None


# RRF constants
RRF_K = 50
CONTENT_WEIGHT = 1.0
QUESTION_WEIGHT = 1.0  # Equal weight - HyDE questions are key for Q&A matching
FTS_WEIGHT = 1.0

# Diversification limits
MAX_RESULTS_PER_PAGE = 2
DEFAULT_LIMIT = 5


async def detect_query_answer_types(
    query: str,
) -> list[str]:
    """Detect answer types from user query using LLM classification.

    Args:
        query: User's search query

    Returns:
        List of answer type strings that match the query intent
    """
    if not settings.openai_api_key:
        return []

    client = get_openai_client()

    prompt = f"""Analyze this board game question and classify what types of answers it needs.

Question: {query}

Available answer type categories:

**Metadata:**
- player_count: Number of players supported
- play_time: How long the game takes
- age_rating: Recommended age
- game_overview: High-level game description
- publisher_info: Publisher, designer, edition info

**Rules:**
- setup_instructions: How to set up the game
- turn_structure: How turns work
- win_conditions: How to win
- end_game: When/how the game ends
- scoring: How points are calculated

**Components:**
- component_list: What pieces are included
- card_types: Types of cards in the game
- resource_types: Types of resources/tokens
- board_layout: Board setup and areas
- token_types: Types of tokens/markers

**Gameplay:**
- action_options: Actions players can take
- combat_rules: How combat/conflict works
- movement_rules: How to move pieces
- trading_rules: How trading/exchange works
- special_abilities: Special powers or abilities

**Clarifications:**
- edge_case: Unusual situations
- example: Example of gameplay
- faq: Frequently asked question
- timing: When something happens
- rule_clarification: Clarifying a specific rule

Select 1-3 answer types that best match what this question is asking for.
Be specific and conservative - only select types that clearly match the question intent.

Return ONLY a JSON object with an "answerTypes" array, nothing else.
Format: {{ "answerTypes": ["type1", "type2", ...] }}"""

    try:
        response = await client.chat.completions.create(
            model=get_model("classification"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=1,  # GPT-5/GPT-4o-mini requires temperature 1
            max_completion_tokens=100,
        )

        content = response.choices[0].message.content
        if not content:
            return []

        result = json.loads(content)
        if not isinstance(result.get("answerTypes"), list):
            return []

        # Filter to only valid answer types
        return [t for t in result["answerTypes"] if t in ANSWER_TYPES]
    except Exception:
        logger.warning(f"Failed to detect answer types for query: {query[:100]!r}", exc_info=True)
        return []


async def rerank_with_cross_encoder(
    query: str,
    candidates: list[SearchResult],
) -> list[SearchResult]:
    """Rerank search results using LLM cross-encoder scoring.

    Scores each candidate's relevance to the query (0-100).

    Args:
        query: User's search query
        candidates: Candidate results to rerank

    Returns:
        Candidates sorted by relevance score (highest first)
    """
    if not candidates or not settings.openai_api_key:
        return candidates

    client = get_openai_client()
    model = get_model("reranking")

    async def score_candidate(candidate: SearchResult) -> tuple[SearchResult, int]:
        """Score a single candidate."""
        try:
            # Use searchable_content if available (has more context), fallback to content
            content = (candidate.searchable_content or candidate.content)[:2000]

            response = await client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": f"""Rate how well this content answers the query on a scale of 0-100.

Query: "{query}"

Content:
{content}

Return ONLY a number between 0-100, nothing else."""
                }],
                temperature=1,  # GPT-5/GPT-4o-mini requires temperature 1
                max_completion_tokens=10,
            )

            score_text = response.choices[0].message.content or "0"
            score = int(score_text.strip())

            # Validate score is in range
            if score < 0 or score > 100:
                score = 0

            return (candidate, score)
        except Exception:
            logger.debug(f"Failed to score candidate {candidate.fragment_id}", exc_info=True)
            return (candidate, 0)

    # Score all candidates in parallel
    tasks = [score_candidate(c) for c in candidates]
    scored = await asyncio.gather(*tasks)

    # Sort by score (highest first)
    scored.sort(key=lambda x: x[1], reverse=True)

    return [c for c, _ in scored]


async def vector_search(
    session: AsyncSession,
    query_embedding: list[float],
    game_id: str | None = None,
    limit: int = 20,
) -> list[tuple[str, float]]:
    """Search fragments by vector similarity using inner product.

    OpenAI embeddings are normalized, so inner product = cosine similarity.
    pgvector's max_inner_product returns negative inner product for ordering,
    so we negate it to get similarity score.

    Returns list of (fragment_id, similarity_score) tuples.
    """
    # Use inner product (faster for normalized embeddings)
    # max_inner_product returns negative inner product, so negate to get similarity
    # Search content embeddings in the embeddings table
    similarity = -Embedding.embedding.max_inner_product(query_embedding)  # type: ignore[attr-defined]

    stmt = (
        select(Embedding.fragment_id, similarity.label("score"))  # type: ignore[call-overload]
        .where(Embedding.type == EmbeddingType.CONTENT)
    )

    if game_id:
        stmt = stmt.where(Embedding.game_id == game_id)

    stmt = stmt.order_by(similarity.desc()).limit(limit)

    result = await session.execute(stmt)
    return [(row.fragment_id, float(row.score)) for row in result]


async def question_vector_search(
    session: AsyncSession,
    query_embedding: list[float],
    game_id: str | None = None,
    limit: int = 20,
) -> list[tuple[str, float]]:
    """Search HyDE question embeddings using inner product.

    Returns list of (fragment_id, similarity_score) tuples.
    """
    # Use inner product (negate max_inner_product to get similarity)
    similarity = -Embedding.embedding.max_inner_product(query_embedding)  # type: ignore[attr-defined]

    stmt = (
        select(Embedding.fragment_id, func.max(similarity).label("score"))  # type: ignore[call-overload]
        .where(Embedding.type == EmbeddingType.QUESTION)
        .group_by(Embedding.fragment_id)
    )

    if game_id:
        stmt = stmt.where(Embedding.game_id == game_id)

    stmt = stmt.order_by(text("score DESC")).limit(limit)

    result = await session.execute(stmt)
    return [(row.fragment_id, float(row.score)) for row in result]


async def fulltext_search(
    session: AsyncSession,
    query: str,
    game_id: str | None = None,
    limit: int = 20,
) -> list[tuple[str, float]]:
    """Search fragments using PostgreSQL full-text search.

    Uses websearch_to_tsquery which supports operators:
    - OR for alternatives
    - AND (implicit between words)
    - - for NOT
    - "quoted phrases" for exact matches

    Returns list of (fragment_id, ts_rank score) tuples.
    """
    # Use websearch_to_tsquery for natural language query support
    # (supports OR, AND, -, and quoted phrases)
    tsquery = func.websearch_to_tsquery("english", query)

    # Use ts_rank_cd for ranking (considers document length)
    rank = func.ts_rank_cd(Fragment.search_vector, tsquery)

    stmt = (
        select(Fragment.id, rank.label("score"))  # type: ignore[call-overload]
        .where(Fragment.search_vector.op("@@")(tsquery))  # type: ignore[union-attr]
    )

    if game_id:
        stmt = stmt.where(Fragment.game_id == game_id)

    stmt = stmt.order_by(rank.desc()).limit(limit)

    result = await session.execute(stmt)
    return [(row.id, float(row.score)) for row in result]


def reciprocal_rank_fusion(
    rankings: list[tuple[list[tuple[str, float]], float]],
    k: int = RRF_K,
) -> dict[str, float]:
    """Combine multiple rankings using Reciprocal Rank Fusion.

    Args:
        rankings: List of (results, weight) tuples where results is [(id, score), ...]
        k: RRF constant (default 50)

    Returns:
        Dict mapping fragment_id to combined RRF score
    """
    scores: dict[str, float] = {}

    for results, weight in rankings:
        for rank, (fragment_id, _) in enumerate(results, start=1):
            rrf_score = weight / (k + rank)
            scores[fragment_id] = scores.get(fragment_id, 0) + rrf_score

    return scores


def diversify_results(
    results: list[SearchResult],
    max_per_page: int = MAX_RESULTS_PER_PAGE,
    max_per_resource: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[SearchResult]:
    """Apply diversification rules to search results.

    - Max N results per page
    - Max M results per resource (default: ceil(limit * 0.6))
    - Overall limit
    """
    # Dynamic max_per_resource based on limit (matches TypeScript)
    if max_per_resource is None:
        max_per_resource = math.ceil(limit * 0.6)
    page_counts: dict[tuple[str, int | None], int] = {}  # (resource_id, page) -> count
    resource_counts: dict[str, int] = {}  # resource_id -> count
    diversified: list[SearchResult] = []

    for result in results:
        if len(diversified) >= limit:
            break

        page_key = (result.resource_id, result.page_number)
        page_count = page_counts.get(page_key, 0)
        resource_count = resource_counts.get(result.resource_id, 0)

        if page_count >= max_per_page:
            continue
        if resource_count >= max_per_resource:
            continue

        diversified.append(result)
        page_counts[page_key] = page_count + 1
        resource_counts[result.resource_id] = resource_count + 1

    return diversified


async def hybrid_search(
    session: AsyncSession,
    query: str,
    query_embedding: list[float] | None = None,
    game_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    include_vector: bool = True,
    include_fts: bool = True,
    enable_reranking: bool = True,
    query_answer_types: list[str] | None = None,
) -> SearchResponse:
    """Perform hybrid search combining vector and full-text search with RRF.

    Args:
        session: Database session
        query: Search query text
        query_embedding: Pre-computed query embedding (optional)
        game_id: Filter to specific game (optional)
        limit: Max results to return
        include_vector: Whether to include vector search
        include_fts: Whether to include full-text search
        enable_reranking: Whether to apply LLM reranking (default: True)
        query_answer_types: Pre-detected answer types for boosting

    Returns:
        SearchResponse with ranked results
    """
    rankings: list[tuple[list[tuple[str, float]], float]] = []
    candidate_count = limit * 3  # Fetch more for fusion and reranking

    # Vector search on content embeddings
    if include_vector and query_embedding:
        content_results = await vector_search(
            session, query_embedding, game_id, limit=candidate_count
        )
        if content_results:
            rankings.append((content_results, CONTENT_WEIGHT))

        # Vector search on HyDE question embeddings
        question_results = await question_vector_search(
            session, query_embedding, game_id, limit=candidate_count // 2
        )
        if question_results:
            rankings.append((question_results, QUESTION_WEIGHT))

    # Full-text search
    if include_fts:
        fts_results = await fulltext_search(session, query, game_id, limit=candidate_count)
        if fts_results:
            rankings.append((fts_results, FTS_WEIGHT))

    # Combine with RRF
    if not rankings:
        return SearchResponse(results=[], query=query, game_id=game_id, answer_types=query_answer_types)

    combined_scores = reciprocal_rank_fusion(rankings)

    # Sort by combined score
    sorted_ids = sorted(combined_scores.keys(), key=lambda x: combined_scores[x], reverse=True)

    # Fetch fragment details
    if not sorted_ids:
        return SearchResponse(results=[], query=query, game_id=game_id, answer_types=query_answer_types)

    stmt = select(Fragment).where(Fragment.id.in_(sorted_ids))  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    fragments_by_id = {f.id: f for f in result.scalars()}

    # Fetch resource names for fragments
    resource_ids = list({f.resource_id for f in fragments_by_id.values()})
    res_stmt = select(Resource.id, Resource.name).where(Resource.id.in_(resource_ids))  # type: ignore[attr-defined]
    res_result = await session.execute(res_stmt)
    resource_names = {row.id: row.name for row in res_result}

    # Apply answer type boosting if query types were detected
    if query_answer_types:
        for frag_id, fragment in fragments_by_id.items():
            if frag_id is None:
                continue
            if fragment.answer_types:
                # Check if any query answer types match fragment answer types
                fragment_types = fragment.answer_types or []
                has_match = any(qt in fragment_types for qt in query_answer_types)
                if has_match:
                    # 30% boost for matching answer types
                    combined_scores[frag_id] *= 1.3

        # Re-sort after boosting
        sorted_ids = sorted(combined_scores.keys(), key=lambda x: combined_scores[x], reverse=True)

    # Build results in score order
    results: list[SearchResult] = []
    for fragment_id in sorted_ids:
        frag = fragments_by_id.get(fragment_id)
        if not frag:
            continue

        # Convert images from JSONB to ImageMetadata objects
        images: list[ImageMetadata] | None = None
        if frag.images:
            images = [
                ImageMetadata(
                    id=img.get("id", ""),
                    url=img.get("url", ""),
                    bbox=img.get("bbox"),
                    caption=img.get("caption"),
                    description=img.get("description"),
                    detected_type=img.get("detectedType"),
                    ocr_text=img.get("ocrText"),
                    is_relevant=img.get("isRelevant"),
                )
                for img in frag.images
                if img.get("url")
            ]

        results.append(
            SearchResult(
                fragment_id=fragment_id,
                content=frag.content,
                page_number=frag.page_number,
                section=frag.section,
                resource_id=frag.resource_id,
                resource_name=resource_names.get(frag.resource_id, "Unknown"),
                game_id=frag.game_id,
                score=combined_scores[fragment_id],
                match_type="hybrid",
                images=images if images else None,
                searchable_content=frag.searchable_content,
            )
        )

    # Apply LLM reranking before diversification
    if enable_reranking and results:
        # Rerank top candidates (limit to save API calls)
        top_candidates = results[:limit * 3]
        results = await rerank_with_cross_encoder(query, top_candidates)

    # Apply diversification
    results = diversify_results(results, limit=limit)

    return SearchResponse(results=results, query=query, game_id=game_id, answer_types=query_answer_types)


class SearchService:
    """Service for searching game content."""

    def __init__(self) -> None:
        """Initialize search service."""
        self._embedding_model = settings.openai_embedding_model

    async def get_embedding(self, text: str) -> list[float] | None:
        """Get embedding for text using OpenAI.

        Returns None if OpenAI is not configured.
        """
        if not settings.openai_api_key:
            return None

        try:
            client = get_openai_client()
            response = await client.embeddings.create(
                model=self._embedding_model,
                input=text,
            )
            return response.data[0].embedding
        except Exception:
            logger.warning(f"Failed to get embedding for text: {text[:100]!r}", exc_info=True)
            return None

    async def search(
        self,
        session: AsyncSession,
        query: str,
        game_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
        enable_reranking: bool = True,
        include_fts: bool = True,
    ) -> SearchResponse:
        """Search for relevant content.

        Args:
            session: Database session
            query: Search query
            game_id: Filter to specific game
            limit: Max results
            enable_reranking: Whether to apply LLM reranking (default: True)
            include_fts: Whether to include full-text search (default: True)

        Returns:
            SearchResponse with results
        """
        # Get query embedding
        # Note: Answer type detection was removed - it added ~2.3s latency but
        # fragment.answer_types was never populated, so the boost never triggered
        query_embedding = await self.get_embedding(query)

        return await hybrid_search(
            session=session,
            query=query,
            query_embedding=query_embedding,
            game_id=game_id,
            limit=limit,
            enable_reranking=enable_reranking,
            include_fts=include_fts,
        )


@dataclass
class PageResult:
    """A page result for parent document retrieval.

    DEPRECATED: Use SegmentResult instead. The pages table has been removed
    in favor of segments for parent document retrieval.
    """

    page_number: int
    content: str
    resource_id: str
    resource_name: str
    word_count: int | None = None


async def expand_chunks_to_pages(
    session: AsyncSession,
    results: list[SearchResult],
    max_pages: int = 5,
) -> list[PageResult]:
    """Expand search result chunks to full pages.

    DEPRECATED: Use expand_chunks_to_segments instead. The pages table has been
    removed in favor of segments for parent document retrieval.

    Args:
        session: Database session (unused)
        results: Search results (unused)
        max_pages: Maximum pages (unused)

    Returns:
        Empty list (pages table no longer exists)
    """
    logger.warning(
        "expand_chunks_to_pages is deprecated. Use expand_chunks_to_segments instead."
    )
    return []


@dataclass
class SegmentResult:
    """A segment result for parent document retrieval."""

    segment_id: str
    title: str
    hierarchy_path: str
    content: str
    resource_id: str
    resource_name: str
    page_start: int | None = None
    page_end: int | None = None
    word_count: int | None = None


# FlashRank reranker instance (lazy-loaded)
_flashrank_ranker = None


def get_flashrank_ranker():
    """Get or create the FlashRank reranker instance.

    FlashRank is a lightweight reranker (<100ms for 100 candidates)
    using ms-marco-MiniLM-L-12-v2 model (4MB, no torch/transformers needed).
    """
    global _flashrank_ranker
    if _flashrank_ranker is None:
        from flashrank import Ranker
        _flashrank_ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
    return _flashrank_ranker


def rerank_segments_with_flashrank(
    query: str,
    segments: list["SegmentResult"],
    top_k: int = 2,
) -> list["SegmentResult"]:
    """Rerank segments using FlashRank cross-encoder.

    Fast reranking (<100ms for typical candidate sets) that improves
    retrieval precision by scoring query-document pairs directly.

    Args:
        query: User's search query
        segments: Candidate segments to rerank
        top_k: Number of top results to return

    Returns:
        Top-k segments sorted by relevance score
    """
    if not segments:
        return []

    if len(segments) <= top_k:
        return segments

    from flashrank import RerankRequest

    ranker = get_flashrank_ranker()

    # Prepare passages for FlashRank
    # Truncate content to avoid excessive processing time
    passages = [
        {"id": s.segment_id, "text": s.content[:2000]}
        for s in segments
    ]

    request = RerankRequest(query=query, passages=passages)
    results = ranker.rerank(request)

    # Map back to SegmentResult objects
    id_to_segment = {s.segment_id: s for s in segments}
    reranked = []
    for r in results[:top_k]:
        segment = id_to_segment.get(r["id"])
        if segment:
            reranked.append(segment)

    logger.debug(f"FlashRank reranked {len(segments)} segments to top {len(reranked)}")
    return reranked


async def segment_summary_search(
    session: AsyncSession,
    query_embedding: list[float],
    game_id: str,
    limit: int = 5,
) -> list["SegmentResult"]:
    """Search segment summary embeddings, return full segments.

    This is the primary search function for the new RAG architecture.
    Searches on segment summaries (generated at index time) which are
    designed to match user queries better than chunk embeddings.

    Args:
        session: Database session
        query_embedding: Query embedding vector
        game_id: Game ID to filter by
        limit: Maximum number of segments to return

    Returns:
        List of SegmentResult with full segment content
    """
    # Search summary embeddings using inner product
    similarity = -Embedding.embedding.max_inner_product(query_embedding)  # type: ignore[attr-defined]

    stmt = (
        select(Embedding.segment_id, Embedding.summary_text, similarity.label("score"))  # type: ignore[call-overload]
        .where(Embedding.type == EmbeddingType.SUMMARY)
        .where(Embedding.game_id == game_id)
        .where(Embedding.segment_id.isnot(None))  # type: ignore[union-attr]
        .order_by(similarity.desc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = list(result)

    if not rows:
        return []

    segment_ids = [row.segment_id for row in rows]

    # Fetch full segment content
    segments_stmt = select(Segment).where(Segment.id.in_(segment_ids))  # type: ignore[attr-defined]
    segments_result = await session.execute(segments_stmt)
    segments_by_id = {seg.id: seg for seg in segments_result.scalars()}

    # Fetch resource names
    resource_ids = list({seg.resource_id for seg in segments_by_id.values()})
    if resource_ids:
        res_stmt = select(Resource.id, Resource.name).where(Resource.id.in_(resource_ids))  # type: ignore[attr-defined]
        res_result = await session.execute(res_stmt)
        resource_names = {row.id: row.name for row in res_result}
    else:
        resource_names = {}

    # Build results in score order
    segment_results: list[SegmentResult] = []
    for row in rows:
        segment = segments_by_id.get(row.segment_id)
        if not segment:
            continue

        segment_results.append(SegmentResult(
            segment_id=segment.id,
            title=segment.title,
            hierarchy_path=segment.hierarchy_path,
            content=segment.content,
            resource_id=segment.resource_id,
            resource_name=resource_names.get(segment.resource_id, "Unknown"),
            page_start=segment.page_start,
            page_end=segment.page_end,
            word_count=segment.word_count,
        ))

    logger.info(f"Segment summary search found {len(segment_results)} segments for game {game_id}")
    return segment_results


async def search_segments(
    session: AsyncSession,
    query: str,
    query_embedding: list[float],
    game_id: str,
    limit: int = 2,
    enable_reranking: bool = True,
) -> list[SegmentResult]:
    """Search and rerank segments for RAG.

    This is the main entry point for the new segment-summary search architecture.
    It:
    1. Searches segment summary embeddings (3x limit for reranking candidates)
    2. Reranks with FlashRank for precision
    3. Returns top segments

    Args:
        session: Database session
        query: User's search query (for reranking)
        query_embedding: Pre-computed query embedding
        game_id: Game ID to filter by
        limit: Number of segments to return (default: 2)
        enable_reranking: Whether to apply FlashRank reranking (default: True)

    Returns:
        List of top SegmentResult for RAG context
    """
    # Search segment summaries (retrieve 3x limit for reranking)
    candidates = await segment_summary_search(
        session, query_embedding, game_id, limit=limit * 3
    )

    if not candidates:
        logger.warning(f"No segment summaries found for game {game_id}")
        return []

    # Rerank with FlashRank
    if enable_reranking and len(candidates) > limit:
        candidates = rerank_segments_with_flashrank(query, candidates, top_k=limit)

    return candidates[:limit]


async def expand_chunks_to_segments(
    session: AsyncSession,
    results: list[SearchResult],
    max_segments: int = 5,
) -> list[SegmentResult]:
    """Expand search result chunks to full segments.

    For parent document retrieval: we search on small chunks for precision,
    but return full segments for better semantic context.

    Args:
        session: Database session
        results: Search results (from hybrid_search)
        max_segments: Maximum number of unique segments to return

    Returns:
        List of SegmentResult with full segment content, deduplicated
    """
    if not results:
        return []

    # Collect unique segment_ids from fragments, preserving search ranking order
    seen_segment_ids: set[str] = set()
    segment_ids: list[str] = []
    resource_names: dict[str, str] = {}  # segment_id -> resource_name

    # Get segment_ids for these fragments
    fragment_ids = [r.fragment_id for r in results]
    if not fragment_ids:
        return []

    # Fetch fragments with segment_ids
    stmt = select(Fragment.id, Fragment.segment_id, Fragment.resource_id).where(
        Fragment.id.in_(fragment_ids)  # type: ignore[attr-defined]
    )
    result = await session.execute(stmt)
    fragment_segments = {row.id: (row.segment_id, row.resource_id) for row in result}

    # Build ordered list of unique segment_ids (use resource_name from SearchResult)
    for search_result in results:
        segment_info = fragment_segments.get(search_result.fragment_id)
        if not segment_info or not segment_info[0]:
            continue

        segment_id, _ = segment_info
        if segment_id not in seen_segment_ids:
            seen_segment_ids.add(segment_id)
            segment_ids.append(segment_id)
            resource_names[segment_id] = search_result.resource_name

            if len(segment_ids) >= max_segments:
                break

    if not segment_ids:
        logger.warning("No segments found for search results - fragments may not have segment_id set")
        return []

    # Fetch full segment content
    segments_stmt = select(Segment).where(Segment.id.in_(segment_ids))  # type: ignore[attr-defined]
    segments_result = await session.execute(segments_stmt)
    segments_by_id = {seg.id: seg for seg in segments_result.scalars()}

    # Build results in original order
    segment_results: list[SegmentResult] = []
    for segment_id in segment_ids:
        segment = segments_by_id.get(segment_id)
        if not segment:
            continue

        segment_results.append(SegmentResult(
            segment_id=segment.id,
            title=segment.title,
            hierarchy_path=segment.hierarchy_path,
            content=segment.content,
            resource_id=segment.resource_id,
            resource_name=resource_names.get(segment_id, "Unknown"),
            page_start=segment.page_start,
            page_end=segment.page_end,
            word_count=segment.word_count,
        ))

    logger.info(
        f"Expanded {len(results)} chunks to {len(segment_results)} segments "
        f"(from {len(seen_segment_ids)} unique segment references)"
    )

    return segment_results


# Keep alias for backwards compatibility during transition
ChapterResult = SegmentResult
expand_chunks_to_chapters = expand_chunks_to_segments


# Global search service instance
search_service = SearchService()
