"""PDF text extraction using PyMuPDF (fitz).

Extracts text page-by-page, preserving page numbers.
Each page returns a dict with ``page_number`` (1-indexed) and ``text``.
"""

import logging
from dataclasses import dataclass

import fitz  # PyMuPDF

logger = logging.getLogger("researchly")


@dataclass
class PageText:
    """Text content for a single PDF page."""

    page_number: int  # 1-indexed
    text: str


def extract_pages(pdf_bytes: bytes) -> list[PageText]:
    """Extract text from every page of a PDF.

    Args:
        pdf_bytes: Raw PDF file contents.

    Returns:
        List of ``PageText`` objects in page order.
        Pages with no extractable text are included with an empty string
        so that page numbering remains correct.

    Raises:
        ValueError: If the bytes do not represent a valid PDF.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {exc}") from exc

    pages: list[PageText] = []
    with doc:
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            text = page.get_text("text") or ""
            pages.append(PageText(page_number=page_index + 1, text=text.strip()))

    logger.debug("Extracted %d pages from PDF", len(pages))
    return pages
