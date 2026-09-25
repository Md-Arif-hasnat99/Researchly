"""Tests for the RAG generation module and the full RAG pipeline.

All external calls (Gemini SDK, Supabase) are mocked.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.search import SearchResultChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_VECTOR = [0.1] * 768


def _make_chunk(
    paper_title: str = "Test Paper",
    page_number: int = 3,
    section: str | None = "Results",
    content: str = "The model achieved 94% accuracy on the benchmark.",
    similarity_score: float = 0.91,
) -> SearchResultChunk:
    return SearchResultChunk(
        chunk_id=uuid4(),
        paper_id=uuid4(),
        paper_title=paper_title,
        page_number=page_number,
        section=section,
        content=content,
        similarity_score=similarity_score,
    )


# ---------------------------------------------------------------------------
# Unit tests: app.rag.generation.gemini
# ---------------------------------------------------------------------------


class TestGenerationModule:
    @patch("app.rag.generation.gemini.get_settings")
    def test_no_api_key_raises(self, mock_settings):
        mock_settings.return_value.GEMINI_API_KEY = ""

        from app.rag.generation.gemini import generate_answer

        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            generate_answer("test?", [_make_chunk()])

    @patch("app.rag.generation.gemini.get_settings")
    def test_empty_chunks_returns_fallback(self, mock_settings):
        mock_settings.return_value.GEMINI_API_KEY = "key"

        from app.rag.generation.gemini import generate_answer

        result = generate_answer("test?", [])

        assert "could not find" in result.answer.lower()
        assert result.cited_chunks == []

    @patch("app.rag.generation.gemini.get_settings")
    @patch("app.rag.generation.gemini.genai.Client")
    def test_returns_model_answer(self, mock_client_cls, mock_settings):
        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "gemini-test"

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "The accuracy was 94% [1]."
        mock_client.models.generate_content.return_value = mock_response

        chunk = _make_chunk()

        from app.rag.generation.gemini import generate_answer

        result = generate_answer("What was the accuracy?", [chunk])

        assert result.answer == "The accuracy was 94% [1]."
        assert len(result.cited_chunks) == 1
        assert result.cited_chunks[0] is chunk
        mock_client.models.generate_content.assert_called_once()

    @patch("app.rag.generation.gemini.get_settings")
    @patch("app.rag.generation.gemini.genai.Client")
    def test_multiple_chunks_passed_in_context(self, mock_client_cls, mock_settings):
        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "gemini-test"

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "Answer with [1] and [2]."
        mock_client.models.generate_content.return_value = mock_response

        chunks = [_make_chunk(paper_title=f"Paper {i}") for i in range(3)]

        from app.rag.generation.gemini import generate_answer

        result = generate_answer("q", chunks)

        assert len(result.cited_chunks) == 3
        # Verify the prompt contained all three papers
        call_args = mock_client.models.generate_content.call_args
        prompt_text = call_args[1]["contents"][0].parts[0].text
        assert "Paper 0" in prompt_text
        assert "Paper 1" in prompt_text
        assert "Paper 2" in prompt_text

    def test_build_context_block_format(self):
        """Context block should have correct [N] headers."""
        from app.rag.generation.gemini import _build_context_block

        chunks = [
            _make_chunk(paper_title="Alpha", page_number=1, section="Intro"),
            _make_chunk(paper_title="Beta", page_number=5, section=None),
        ]
        block = _build_context_block(chunks)
        assert "[1] Alpha — page 1, Intro" in block
        assert "[2] Beta — page 5" in block
        assert ", None" not in block  # section=None should not appear


# ---------------------------------------------------------------------------
# Unit tests: app.rag.pipeline
# ---------------------------------------------------------------------------


class TestRAGPipeline:
    @patch("app.rag.pipeline.generate_answer")
    @patch("app.rag.pipeline.similarity_search")
    def test_happy_path(self, mock_search, mock_generate):
        chunk = _make_chunk()
        mock_search.return_value = [chunk]

        from app.rag.generation.gemini import GeneratedAnswer

        mock_generate.return_value = GeneratedAnswer(
            answer="Test answer [1].",
            cited_chunks=[chunk],
        )

        from app.rag.pipeline import run_rag

        result = run_rag(query="q", user_id="user-1")

        assert result.answer == "Test answer [1]."
        assert result.retrieved_count == 1
        assert len(result.cited_chunks) == 1

        mock_search.assert_called_once_with(
            query="q",
            user_id="user-1",
            top_k=8,
            similarity_threshold=0.65,
            paper_ids=None,
        )
        mock_generate.assert_called_once_with(query="q", chunks=[chunk])

    @patch("app.rag.pipeline.generate_answer")
    @patch("app.rag.pipeline.similarity_search")
    def test_empty_retrieval_gives_fallback(self, mock_search, mock_generate):
        mock_search.return_value = []

        from app.rag.generation.gemini import GeneratedAnswer

        mock_generate.return_value = GeneratedAnswer(
            answer="I could not find information about this in the provided papers.",
            cited_chunks=[],
        )

        from app.rag.pipeline import run_rag

        result = run_rag(query="q", user_id="user-1")

        assert result.retrieved_count == 0
        assert result.cited_chunks == []
        assert "could not find" in result.answer.lower()

    @patch("app.rag.pipeline.similarity_search")
    def test_propagates_runtime_error(self, mock_search):
        mock_search.side_effect = RuntimeError("GEMINI_API_KEY is not configured.")

        from app.rag.pipeline import run_rag

        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            run_rag(query="q", user_id="user-1")

    @patch("app.rag.pipeline.generate_answer")
    @patch("app.rag.pipeline.similarity_search")
    def test_paper_ids_forwarded(self, mock_search, mock_generate):
        mock_search.return_value = []
        from app.rag.generation.gemini import GeneratedAnswer

        mock_generate.return_value = GeneratedAnswer(answer="x", cited_chunks=[])

        pid = uuid4()

        from app.rag.pipeline import run_rag

        run_rag(query="q", user_id="u", paper_ids=[pid])

        assert mock_search.call_args[1]["paper_ids"] == [pid]
