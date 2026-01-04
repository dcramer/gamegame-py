"""LLM-based segment extraction for parent document retrieval.

Extracts segments from markdown documents using LLM semantic understanding.
Segments are used to provide complete context to the LLM during RAG.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from gamegame.models.model_config import get_model
from gamegame.services.openai_client import create_chat_completion

logger = logging.getLogger(__name__)

# JSON schema for structured segment extraction output
SEGMENT_EXTRACTION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "segment_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Short descriptive title for this segment",
                            },
                            "hierarchy_path": {
                                "type": "string",
                                "description": "Full hierarchy path like 'Parent > Child > Title'",
                            },
                            "start_line": {
                                "type": "integer",
                                "description": "First line number of this segment (1-indexed, inclusive)",
                            },
                            "end_line": {
                                "type": "integer",
                                "description": "Last line number of this segment (1-indexed, inclusive)",
                            },
                        },
                        "required": ["title", "hierarchy_path", "start_line", "end_line"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["segments"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class SegmentData:
    """Data for a segment extracted from markdown."""

    id: str | None = None
    level: int = 1
    title: str = ""
    hierarchy_path: str = ""
    content: str = ""
    start_line: int = 0
    end_line: int = 0
    page_start: int | None = None
    page_end: int | None = None
    word_count: int = 0
    char_count: int = 0
    parent_id: str | None = None
    order_index: int = 0


SEGMENT_EXTRACTION_PROMPT = """You are analyzing a document to identify logical sections/segments.

Your task: Identify distinct segments that group related content together. Each segment should be a complete, self-contained unit that covers a specific topic.

Guidelines:
- Create segments for major topics: Setup, Gameplay, Turn Structure, Combat, Victory, etc.
- Use hierarchy_path for nested sections: "Gameplay > Combat > Ranged Attacks"
- Target segment size: 500-3000 characters (can be larger for complex topics)
- SKIP these entirely - do not create segments for:
  - Table of Contents
  - Index pages
  - Page number listings
  - Empty sections
- Merge tiny sections (<200 chars) into their parent or neighboring segment
- Max hierarchy depth: 3 levels (e.g., "A > B > C")
- Segments must be contiguous - no gaps between segments
- First segment should start at line 1
- start_line and end_line are inclusive (1-indexed)
- Segments must cover the entire document without gaps

{resource_context}

Document with line numbers:
```
{numbered_markdown}
```"""


def _number_lines(markdown: str) -> tuple[str, list[str]]:
    """Add line numbers to markdown for LLM reference.

    Returns (numbered_text, original_lines).
    """
    lines = markdown.split("\n")
    numbered_lines = []
    for i, line in enumerate(lines, 1):
        numbered_lines.append(f"{i:4d}| {line}")
    return "\n".join(numbered_lines), lines


def _calculate_page_range(
    start_char: int,
    end_char: int,
    page_boundaries: list[tuple[int, int]] | None,
) -> tuple[int | None, int | None]:
    """Map character positions to page numbers.

    Args:
        start_char: Starting character position
        end_char: Ending character position
        page_boundaries: List of (start, end) char positions per page

    Returns:
        (page_start, page_end) tuple
    """
    if not page_boundaries:
        return None, None

    page_start = None
    page_end = None

    for page_num, (p_start, p_end) in enumerate(page_boundaries, 1):
        # Find first page containing start_char
        if page_start is None and p_start <= start_char < p_end:
            page_start = page_num
        # Find last page containing end_char
        if p_start <= end_char < p_end:
            page_end = page_num
        elif end_char >= p_end and page_num == len(page_boundaries):
            # Past the end - use last page
            page_end = page_num

    return page_start, page_end


def _parse_segment_response(
    response_text: str,
    lines: list[str],
    page_boundaries: list[tuple[int, int]] | None,
) -> list[SegmentData]:
    """Parse LLM response and build SegmentData objects.

    Args:
        response_text: JSON response from LLM
        lines: Original document lines
        page_boundaries: Character positions per page

    Returns:
        List of SegmentData objects
    """
    # Clean up response - sometimes LLM adds markdown code blocks
    response_text = response_text.strip()
    if response_text.startswith("```"):
        # Remove markdown code block
        response_text = re.sub(r"^```(?:json)?\n?", "", response_text)
        response_text = re.sub(r"\n?```$", "", response_text)

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse segment extraction response: {e}")
        logger.debug(f"Response was: {response_text[:500]}...")
        raise ValueError(f"Invalid JSON in segment extraction response: {e}") from e

    segments_data = data.get("segments", [])
    if not segments_data:
        logger.warning("LLM returned no segments")
        return []

    segments: list[SegmentData] = []

    # Calculate character positions for each line
    line_positions: list[tuple[int, int]] = []
    current_pos = 0
    for line in lines:
        line_len = len(line)
        line_positions.append((current_pos, current_pos + line_len))
        current_pos += line_len + 1  # +1 for newline

    for idx, seg in enumerate(segments_data):
        title = seg.get("title", "")
        hierarchy_path = seg.get("hierarchy_path", title)
        start_line = seg.get("start_line", 1)
        end_line = seg.get("end_line", len(lines))

        # Validate line numbers
        start_line = max(1, min(start_line, len(lines)))
        end_line = max(start_line, min(end_line, len(lines)))

        # Extract content (lines are 1-indexed)
        content_lines = lines[start_line - 1:end_line]
        content = "\n".join(content_lines)

        # Calculate character positions
        start_char = line_positions[start_line - 1][0] if start_line <= len(line_positions) else 0
        end_char = line_positions[end_line - 1][1] if end_line <= len(line_positions) else len("\n".join(lines))

        # Calculate page range
        page_start, page_end = _calculate_page_range(start_char, end_char, page_boundaries)

        # Determine level from hierarchy path
        level = hierarchy_path.count(">") + 1

        segments.append(SegmentData(
            level=level,
            title=title,
            hierarchy_path=hierarchy_path,
            content=content,
            start_line=start_line,
            end_line=end_line,
            page_start=page_start,
            page_end=page_end if page_end != page_start else None,
            word_count=len(content.split()),
            char_count=len(content),
            order_index=idx,
        ))

    logger.info(f"Parsed {len(segments)} segments from LLM response")
    return segments


async def _extract_segments_single_batch(
    numbered_markdown: str,
    lines: list[str],
    page_boundaries: list[tuple[int, int]] | None,
    resource_context: str,
    line_offset: int = 0,
) -> list[SegmentData]:
    """Extract segments from a single batch of content.

    Args:
        numbered_markdown: Content with line numbers
        lines: Original lines for this batch
        page_boundaries: Full document page boundaries
        resource_context: Context string for prompt
        line_offset: Offset to add to line numbers (for batched processing)

    Returns:
        List of SegmentData objects with adjusted line numbers
    """
    prompt = SEGMENT_EXTRACTION_PROMPT.format(
        resource_context=resource_context,
        numbered_markdown=numbered_markdown,
    )

    response = await create_chat_completion(
        model=get_model("reasoning"),
        messages=[{"role": "user", "content": prompt}],
        response_format=SEGMENT_EXTRACTION_SCHEMA,
        temperature=1.0,  # GPT-5 requires temperature 1.0
        max_completion_tokens=4000,
    )

    response_text = response.choices[0].message.content or ""

    if not response_text.strip():
        return []

    segments = _parse_segment_response(response_text, lines, page_boundaries)

    # Adjust line numbers by offset for batched processing
    if line_offset > 0:
        for seg in segments:
            seg.start_line += line_offset
            seg.end_line += line_offset

    return segments


def _split_into_batches(
    lines: list[str],
    max_chars: int = 80_000,
    overlap_lines: int = 50,
) -> list[tuple[int, int]]:
    """Split document into batches by line ranges.

    Args:
        lines: All document lines
        max_chars: Maximum characters per batch (including line numbers)
        overlap_lines: Number of lines to overlap between batches

    Returns:
        List of (start_line, end_line) tuples (0-indexed)
    """
    batches: list[tuple[int, int]] = []
    current_start = 0

    while current_start < len(lines):
        # Find end of this batch
        current_chars = 0
        current_end = current_start

        for i in range(current_start, len(lines)):
            # Estimate line with number prefix: "1234| content\n"
            line_chars = len(lines[i]) + 7
            if current_chars + line_chars > max_chars and i > current_start:
                break
            current_chars += line_chars
            current_end = i + 1

        batches.append((current_start, current_end))

        # Next batch starts with overlap
        if current_end >= len(lines):
            break
        current_start = max(current_start + 1, current_end - overlap_lines)

    return batches


def _merge_batch_segments(
    all_segments: list[list[SegmentData]],
    batch_ranges: list[tuple[int, int]],
) -> list[SegmentData]:
    """Merge segments from multiple batches, handling overlaps.

    Args:
        all_segments: List of segment lists from each batch
        batch_ranges: The (start, end) line ranges for each batch

    Returns:
        Merged and deduplicated segment list
    """
    if not all_segments:
        return []

    if len(all_segments) == 1:
        return all_segments[0]

    merged: list[SegmentData] = []

    for batch_idx, segments in enumerate(all_segments):
        if batch_idx == 0:
            # First batch: take all segments
            merged.extend(segments)
        else:
            # Subsequent batches: skip segments that overlap with previous
            prev_end = batch_ranges[batch_idx - 1][1]
            for seg in segments:
                # Only add if segment starts after the previous batch's non-overlap region
                # (i.e., in the unique portion of this batch)
                if seg.start_line >= prev_end - 25:  # Half of overlap
                    # Check if we already have a segment covering this range
                    overlapping = False
                    for existing in merged:
                        if (existing.start_line <= seg.start_line <= existing.end_line or
                            existing.start_line <= seg.end_line <= existing.end_line):
                            overlapping = True
                            break
                    if not overlapping:
                        merged.append(seg)

    # Sort by start line and re-index
    merged.sort(key=lambda c: c.start_line)
    for idx, seg in enumerate(merged):
        seg.order_index = idx

    return merged


async def extract_segments_llm(
    markdown: str,
    page_boundaries: list[tuple[int, int]] | None = None,
    resource_name: str | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list[SegmentData]:
    """Extract segments using LLM analysis.

    For large documents, processes in batches and merges results.

    Args:
        markdown: Full markdown content of the document
        page_boundaries: List of (start_char, end_char) per page for page annotation
        resource_name: Optional resource name for context
        on_progress: Optional callback for progress updates (current, total)

    Returns:
        List of SegmentData objects
    """
    if not markdown or not markdown.strip():
        return []

    lines = markdown.split("\n")

    # Build context about the resource
    resource_context = ""
    if resource_name:
        resource_context = f"Document: {resource_name}"

    # Check if we need batched processing
    numbered_markdown, _ = _number_lines(markdown)
    max_chars_for_single = 80_000

    if len(numbered_markdown) <= max_chars_for_single:
        # Small enough for single LLM call
        logger.info(f"Extracting segments via LLM ({len(lines)} lines, {len(markdown)} chars)")

        try:
            segments = await _extract_segments_single_batch(
                numbered_markdown, lines, page_boundaries, resource_context
            )

            # Report progress (1/1 for single batch)
            if on_progress:
                await on_progress(1, 1)

            if not segments:
                logger.warning("LLM returned no segments, falling back to heuristic method")
                return extract_segments_heuristic(markdown, page_boundaries)

            # Validate coverage
            _validate_segment_coverage(segments, len(lines))
            return segments

        except Exception as e:
            logger.warning(f"LLM segment extraction failed: {e}, falling back to heuristic method")
            return extract_segments_heuristic(markdown, page_boundaries)

    # Large document: process in batches
    batch_ranges = _split_into_batches(lines, max_chars=max_chars_for_single)
    logger.info(
        f"Extracting segments via LLM in {len(batch_ranges)} batches "
        f"({len(lines)} lines, {len(markdown)} chars)"
    )

    all_segments: list[list[SegmentData]] = []

    try:
        for batch_idx, (start, end) in enumerate(batch_ranges):
            batch_lines = lines[start:end]
            # Number lines starting from 1 for each batch (LLM sees consistent numbering)
            batch_numbered, _ = _number_lines("\n".join(batch_lines))

            logger.info(f"Processing batch {batch_idx + 1}/{len(batch_ranges)} (lines {start + 1}-{end})")

            batch_segments = await _extract_segments_single_batch(
                batch_numbered,
                batch_lines,
                page_boundaries,
                resource_context,
                line_offset=start,  # Adjust line numbers to global
            )

            all_segments.append(batch_segments)

            # Report progress after each batch
            if on_progress:
                await on_progress(batch_idx + 1, len(batch_ranges))

        # Merge results from all batches
        merged = _merge_batch_segments(all_segments, batch_ranges)

        if not merged:
            logger.warning("LLM returned no segments from batches, falling back to heuristic method")
            return extract_segments_heuristic(markdown, page_boundaries)

        # Re-extract content with correct global line numbers
        for seg in merged:
            seg.content = "\n".join(lines[seg.start_line - 1:seg.end_line])
            seg.word_count = len(seg.content.split())
            seg.char_count = len(seg.content)

        logger.info(f"Merged {len(merged)} segments from {len(batch_ranges)} batches")
        _validate_segment_coverage(merged, len(lines))
        return merged

    except Exception as e:
        logger.warning(f"Batched LLM segment extraction failed: {e}, falling back to heuristic method")
        return extract_segments_heuristic(markdown, page_boundaries)


def _validate_segment_coverage(segments: list[SegmentData], total_lines: int) -> None:
    """Log warnings about gaps in segment coverage."""
    sorted_segments = sorted(segments, key=lambda c: c.start_line)
    expected_start = 1
    for seg in sorted_segments:
        if seg.start_line > expected_start:
            logger.warning(
                f"Gap in segments: lines {expected_start}-{seg.start_line - 1} not covered"
            )
        expected_start = seg.end_line + 1

    if expected_start <= total_lines:
        logger.warning(
            f"End of document not covered: lines {expected_start}-{total_lines}"
        )


# Keep the simple heuristic function as a fallback
def extract_segments_heuristic(
    markdown: str,
    page_boundaries: list[tuple[int, int]] | None = None,
) -> list[SegmentData]:
    """Simple heuristic segment extraction based on markdown headings.

    This is a fallback for cases where LLM extraction fails or for testing.
    """
    if not markdown or not markdown.strip():
        return []

    lines = markdown.split("\n")
    segments: list[SegmentData] = []
    current_segment_start = 0
    current_title = "Introduction"
    current_hierarchy: dict[int, str] = {}

    # Calculate character positions for each line (for page mapping)
    line_positions: list[tuple[int, int]] = []
    current_pos = 0
    for line in lines:
        line_len = len(line)
        line_positions.append((current_pos, current_pos + line_len))
        current_pos += line_len + 1  # +1 for newline

    def save_segment(end_line: int) -> None:
        if end_line > current_segment_start:
            content = "\n".join(lines[current_segment_start:end_line])
            if len(content.strip()) >= 100:  # Skip tiny segments
                path_parts: list[str] = [
                    v for i in sorted(current_hierarchy.keys())
                    if (v := current_hierarchy.get(i)) is not None
                ]
                hierarchy_path = " > ".join(path_parts) if path_parts else current_title

                # Calculate page range
                start_char = line_positions[current_segment_start][0] if current_segment_start < len(line_positions) else 0
                end_char = line_positions[end_line - 1][1] if end_line <= len(line_positions) else len(markdown)
                page_start, page_end = _calculate_page_range(start_char, end_char, page_boundaries)

                segments.append(SegmentData(
                    level=len(path_parts) or 1,
                    title=current_title,
                    hierarchy_path=hierarchy_path,
                    content=content,
                    start_line=current_segment_start + 1,
                    end_line=end_line,
                    page_start=page_start,
                    page_end=page_end if page_end != page_start else None,
                    word_count=len(content.split()),
                    char_count=len(content),
                    order_index=len(segments),
                ))

    for i, line in enumerate(lines):
        # Check for markdown heading
        match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if match:
            # Save previous segment
            save_segment(i)

            # Start new segment
            level = len(match.group(1))
            title = match.group(2).strip()
            current_title = title
            current_segment_start = i

            # Update hierarchy
            current_hierarchy[level] = title
            # Clear deeper levels
            for lvl in list(current_hierarchy.keys()):
                if lvl > level:
                    del current_hierarchy[lvl]

    # Save final segment
    save_segment(len(lines))

    # Re-index
    for idx, seg in enumerate(segments):
        seg.order_index = idx

    logger.info(f"Heuristic extraction found {len(segments)} segments")
    return segments
