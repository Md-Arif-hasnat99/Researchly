"""Text chunking for extracted PDF pages.

Splits page text into overlapping chunks suitable for embedding.
Each chunk carries metadata so it can be traced back to its source.
"""

import logging
import re
from dataclasses import dataclass

from app.rag.ingestion.extractor import PageText

logger = logging.getLogger("researchly")

# Default chunking parameters
DEFAULT_CHUNK_SIZE = 800      # target characters per chunk
DEFAULT_CHUNK_OVERLAP = 150  # overlap between consecutive chunks

# Heading patterns used for naive section detection
_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\s+)?(?:abstract|introduction|related work|background|"
    r"methodology|method|approach|experiments?|results?|evaluation|"
    r"discussion|conclusion|references?|acknowledgements?)\b",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class TextChunk:
    """A single chunk of text with source metadata."""

    paper_id: str
    page_number: int
    section: str | None
    chunk_index: int    # global index across the whole document
    content: str


def _detect_section(text: str) -> str | None:
    """Return the first heading-like line found in *text*, or None."""
    match = _HEADING_RE.search(text)
    if match:
        return match.group(0).strip().title()
    return None


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split *text* into overlapping character-level windows.

    Attempts to break on sentence boundaries (`. `) when possible.

    Raises:
        ValueError: If ``chunk_size`` <= 0 or ``overlap`` is outside
                    ``0 <= overlap < chunk_size``.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    if not (0 <= overlap < chunk_size):
        raise ValueError(
            f"overlap must satisfy 0 <= overlap < chunk_size, "
            f"got overlap={overlap}, chunk_size={chunk_size}"
        )

    if not text:
        return []

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        segment = text[start:end]
        is_final = end >= text_len

        # Only try sentence-boundary splitting for non-final windows so we
        # never drop trailing content from the last chunk.
        if not is_final:
            last_sentence = segment.rfind(". ")
            if last_sentence > chunk_size // 2:
                end = start + last_sentence + 1
                segment = text[start:end]

        segment = segment.strip()
        if segment:
            chunks.append(segment)

        if is_final:
            break

        start = end - overlap

    return chunks



def chunk_pages(
    pages: list[PageText],
    paper_id: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Convert a list of ``PageText`` objects into ``TextChunk`` objects.

    Args:
        pages:      Ordered list of page texts from the extractor.
        paper_id:   UUID string of the parent paper row.
        chunk_size: Target character length for each chunk.
        overlap:    Character overlap between consecutive chunks.

    Returns:
        Flat list of ``TextChunk`` objects in document order.
    """
    chunks: list[TextChunk] = []
    chunk_index = 0
    current_section: str | None = None

    for page in pages:
        if not page.text:
            continue

        # Update running section tracker
        detected = _detect_section(page.text)
        if detected:
            current_section = detected

        for segment in _split_text(page.text, chunk_size, overlap):
            chunks.append(
                TextChunk(
                    paper_id=paper_id,
                    page_number=page.page_number,
                    section=current_section,
                    chunk_index=chunk_index,
                    content=segment,
                )
            )
            chunk_index += 1

    logger.debug(
        "Chunked paper %s into %d chunks across %d pages",
        paper_id,
        len(chunks),
        len(pages),
    )
    return chunks
