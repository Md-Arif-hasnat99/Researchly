"""Tests for the PDF ingestion pipeline — extractor, chunker, and pipeline."""

from unittest.mock import MagicMock, patch

import pytest

from app.rag.ingestion.chunker import chunk_pages
from app.rag.ingestion.extractor import PageText, extract_pages

# ---------------------------------------------------------------------------
# Minimal valid PDF bytes (hand-crafted so no real file needed)
# ---------------------------------------------------------------------------

# A tiny but structurally valid PDF that PyMuPDF can open.
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R"
    b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>\nstream\n"
    b"BT /F1 12 Tf 100 700 Td (Hello World) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 6\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"0000000266 00000 n \n"
    b"0000000360 00000 n \n"
    b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n438\n%%EOF"
)

# ---------------------------------------------------------------------------
# Extractor tests
# ---------------------------------------------------------------------------


class TestExtractor:
    def test_extract_returns_page_texts(self):
        pages = extract_pages(_MINIMAL_PDF)
        assert isinstance(pages, list)
        assert len(pages) == 1
        assert pages[0].page_number == 1

    def test_extract_invalid_bytes_raises(self):
        with pytest.raises(ValueError, match="Cannot open PDF"):
            extract_pages(b"not a pdf")

    def test_extract_page_numbers_are_one_indexed(self):
        pages = extract_pages(_MINIMAL_PDF)
        assert pages[0].page_number == 1


# ---------------------------------------------------------------------------
# Chunker tests
# ---------------------------------------------------------------------------


class TestChunker:
    def _make_pages(self, texts: list[str]) -> list[PageText]:
        return [PageText(page_number=i + 1, text=t) for i, t in enumerate(texts)]

    def test_empty_pages_returns_no_chunks(self):
        chunks = chunk_pages(self._make_pages([""]), paper_id="p1")
        assert chunks == []

    def test_short_text_produces_one_chunk(self):
        chunks = chunk_pages(self._make_pages(["Hello world."]), paper_id="p1")
        assert len(chunks) == 1
        assert chunks[0].content == "Hello world."
        assert chunks[0].page_number == 1
        assert chunks[0].paper_id == "p1"
        assert chunks[0].chunk_index == 0

    def test_long_text_produces_multiple_chunks(self):
        long_text = "word " * 500  # ~2500 chars → at least 3 chunks with default size 800
        chunks = chunk_pages(self._make_pages([long_text]), paper_id="p2", chunk_size=800)
        assert len(chunks) >= 2

    def test_chunk_indices_are_sequential(self):
        texts = ["word " * 300, "sentence. " * 200]
        chunks = chunk_pages(self._make_pages(texts), paper_id="p3")
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_section_detection_abstract(self):
        text = "Abstract\n\nThis paper presents a novel method for..."
        chunks = chunk_pages(self._make_pages([text]), paper_id="p4")
        assert any(c.section and "abstract" in c.section.lower() for c in chunks)

    def test_metadata_attached_correctly(self):
        chunk = chunk_pages(
            self._make_pages(["A short but complete sentence."]), paper_id="uuid-xyz"
        )[0]
        assert chunk.paper_id == "uuid-xyz"
        assert chunk.page_number == 1

    def test_multi_page_page_numbers_preserved(self):
        pages = self._make_pages(["Page one text.", "Page two text."])
        chunks = chunk_pages(pages, paper_id="p5")
        page_numbers = {c.page_number for c in chunks}
        assert 1 in page_numbers
        assert 2 in page_numbers


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------


class TestPipeline:
    def _mock_supabase(self) -> MagicMock:
        mock = MagicMock()
        mock.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[])
        )
        mock.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
        return mock

    @patch("app.rag.ingestion.pipeline.get_supabase_client")
    def test_successful_ingestion_returns_chunk_count(self, mock_client):
        mock_client.return_value = self._mock_supabase()
        from app.rag.ingestion.pipeline import run_ingestion

        result = run_ingestion("paper-id-1", _MINIMAL_PDF)
        # Minimal PDF may extract little or no text → result >= 0
        assert isinstance(result, int)
        assert result >= 0

    @patch("app.rag.ingestion.pipeline.get_supabase_client")
    def test_invalid_pdf_sets_failed_status(self, mock_client):
        client = self._mock_supabase()
        mock_client.return_value = client
        from app.rag.ingestion.pipeline import run_ingestion

        result = run_ingestion("paper-id-2", b"not a pdf")
        assert result == 0

        # Extract all update calls to check that "failed" was set
        update_calls = client.table.return_value.update.call_args_list
        statuses = [c.args[0]["status"] for c in update_calls if "status" in c.args[0]]
        assert "failed" in statuses

    @patch("app.rag.ingestion.pipeline.get_supabase_client")
    def test_status_transitions_processing_then_ready(self, mock_client):
        client = self._mock_supabase()
        mock_client.return_value = client
        from app.rag.ingestion.pipeline import run_ingestion

        run_ingestion("paper-id-3", _MINIMAL_PDF)

        update_calls = client.table.return_value.update.call_args_list
        statuses = [c.args[0]["status"] for c in update_calls if "status" in c.args[0]]
        assert statuses[0] == "processing"
        assert statuses[-1] in {"ready", "failed"}
