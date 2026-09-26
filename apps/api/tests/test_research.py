"""Tests for the multi-paper research API (Part 11).

Covers:
    POST /api/research/compare

Plus unit tests for the comparison matrix generation module.

Supabase, retrieval, and Gemini are all mocked — no network calls.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_application

# ---------------------------------------------------------------------------
# Fixtures & shared constants
# ---------------------------------------------------------------------------

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}

PAPER_A = str(uuid4())
PAPER_B = str(uuid4())
PAPER_C = str(uuid4())
CHUNK_A = str(uuid4())
CHUNK_B = str(uuid4())


@pytest.fixture()
def client():
    return TestClient(create_application())


def _paper_row(paper_id: str, title: str, year: int = 2020) -> dict:
    return {
        "id": paper_id,
        "title": title,
        "publication_year": year,
        "status": "ready",
    }


def _chunk(paper_id: str, chunk_id: str, title: str, page: int, content: str):
    from app.schemas.search import SearchResultChunk

    return SearchResultChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        paper_title=title,
        page_number=page,
        section=None,
        content=content,
        similarity_score=0.8,
    )


def _stub_ownership(mock_db, rows: list[dict]) -> None:
    """Stub the papers ownership query in app.api.research."""
    query = (
        mock_db.table.return_value
        .select.return_value
        .in_.return_value
        .eq.return_value
    )
    query.execute.return_value = MagicMock(data=rows)


# ---------------------------------------------------------------------------
# POST /api/research/compare — happy path
# ---------------------------------------------------------------------------


class TestCompareEndpoint:
    @patch("app.api.research.generate_comparison")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_returns_comparison_matrix(
        self, mock_client_fn, mock_search, mock_gen, client
    ):
        """Two papers, both retrieved → matrix with one cell per paper."""
        from app.rag.generation.compare import ComparisonResult
        from app.schemas.research import CompareCell, ComparePaperRef, CompareRow

        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db,
            [_paper_row(PAPER_A, "Alpha Paper", 2017), _paper_row(PAPER_B, "Beta Paper", 2020)],
        )

        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Alpha Paper", 7, "Alpha uses WMT14.")],
            [_chunk(PAPER_B, CHUNK_B, "Beta Paper", 3, "Beta uses Natural Questions.")],
        ]

        mock_gen.return_value = ComparisonResult(
            papers=[
                ComparePaperRef(paper_id=PAPER_A, paper_title="Alpha Paper", publication_year=2017),
                ComparePaperRef(paper_id=PAPER_B, paper_title="Beta Paper", publication_year=2020),
            ],
            rows=[
                CompareRow(
                    aspect="Dataset",
                    cells=[
                        CompareCell(
                            paper_id=PAPER_A,
                            paper_title="Alpha Paper",
                            summary="WMT 2014 EN-DE.",
                            page_number=7,
                            chunk_id=CHUNK_A,
                        ),
                        CompareCell(
                            paper_id=PAPER_B,
                            paper_title="Beta Paper",
                            summary="Natural Questions.",
                            page_number=3,
                            chunk_id=CHUNK_B,
                        ),
                    ],
                )
            ],
            summary="Alpha is translation-focused; Beta is retrieval-based.",
            citations=[CHUNK_A, CHUNK_B],
        )

        resp = client.post(
            "/api/research/compare",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["papers"]) == 2
        assert body["rows"][0]["aspect"] == "Dataset"
        assert len(body["rows"][0]["cells"]) == 2
        assert body["rows"][0]["cells"][0]["page_number"] == 7
        assert body["summary"].startswith("Alpha is translation")
        assert len(body["citations"]) == 2

    @patch("app.api.research.generate_comparison")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_accepts_custom_aspects_and_focus(
        self, mock_client_fn, mock_search, mock_gen, client
    ):
        """Custom aspects and a focus string are forwarded to the generator."""
        from app.rag.generation.compare import ComparisonResult

        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(mock_db, [_paper_row(PAPER_A, "Alpha"), _paper_row(PAPER_B, "Beta")])
        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Alpha", 1, "a")],
            [_chunk(PAPER_B, CHUNK_B, "Beta", 2, "b")],
        ]
        mock_gen.return_value = ComparisonResult(papers=[], rows=[], summary="")

        resp = client.post(
            "/api/research/compare",
            json={
                "paper_ids": [PAPER_A, PAPER_B],
                "aspects": ["Training Regime"],
                "focus": "compare evaluation methodology",
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert mock_gen.call_args.kwargs["aspects"] == ["Training Regime"]
        assert mock_gen.call_args.kwargs["focus"] == "compare evaluation methodology"

    @patch("app.api.research.generate_comparison")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_retrieval_is_scoped_per_paper(
        self, mock_client_fn, mock_search, mock_gen, client
    ):
        """Each paper is retrieved independently to preserve source identity."""
        from app.rag.generation.compare import ComparisonResult

        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db,
            [
                _paper_row(PAPER_A, "Alpha"),
                _paper_row(PAPER_B, "Beta"),
                _paper_row(PAPER_C, "Gamma"),
            ],
        )
        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Alpha", 1, "a")],
            [_chunk(PAPER_B, CHUNK_B, "Beta", 2, "b")],
            [_chunk(PAPER_C, uuid4(), "Gamma", 3, "c")],
        ]
        mock_gen.return_value = ComparisonResult(papers=[], rows=[], summary="")

        resp = client.post(
            "/api/research/compare",
            json={"paper_ids": [PAPER_A, PAPER_B, PAPER_C]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert mock_search.call_count == 3
        for call in mock_search.call_args_list:
            assert len(call.kwargs["paper_ids"]) == 1
            assert call.kwargs["similarity_threshold"] == 0.0

    def test_unauthenticated_returns_401(self, client):
        resp = client.post(
            "/api/research/compare",
            json={"paper_ids": [PAPER_A, PAPER_B]},
        )
        assert resp.status_code == 401

    def test_single_paper_returns_422(self, client):
        resp = client.post(
            "/api/research/compare",
            json={"paper_ids": [PAPER_A]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_missing_paper_ids_returns_422(self, client):
        resp = client.post(
            "/api/research/compare",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/research/compare — error paths
# ---------------------------------------------------------------------------


class TestCompareErrors:
    @patch("app.api.research.get_supabase_client")
    def test_unowned_paper_returns_404(self, mock_client_fn, client):
        """A paper the caller does not own must not be revealed."""
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(mock_db, [_paper_row(PAPER_A, "Alpha")])

        resp = client.post(
            "/api/research/compare",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @patch("app.api.research.get_supabase_client")
    def test_unindexed_paper_returns_409(self, mock_client_fn, client):
        """Papers still processing cannot be compared."""
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        row_b = _paper_row(PAPER_B, "Beta")
        row_b["status"] = "processing"
        _stub_ownership(mock_db, [_paper_row(PAPER_A, "Alpha"), row_b])

        resp = client.post(
            "/api/research/compare",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409
        assert "indexed" in resp.json()["detail"].lower()

    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_409_when_fewer_than_two_papers_have_chunks(
        self, mock_client_fn, mock_search, client
    ):
        """One empty paper → 409 rather than a one-column matrix."""
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db, [_paper_row(PAPER_A, "Alpha"), _paper_row(PAPER_B, "Beta")]
        )
        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Alpha", 1, "a")],
            [],  # Beta has no indexed chunks
        ]

        resp = client.post(
            "/api/research/compare",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409

    @patch("app.api.research.generate_comparison")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_503_when_gemini_key_missing(
        self, mock_client_fn, mock_search, mock_gen, client
    ):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db, [_paper_row(PAPER_A, "Alpha"), _paper_row(PAPER_B, "Beta")]
        )
        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Alpha", 1, "a")],
            [_chunk(PAPER_B, CHUNK_B, "Beta", 2, "b")],
        ]
        mock_gen.side_effect = RuntimeError("GEMINI_API_KEY is not configured.")

        resp = client.post(
            "/api/research/compare",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 503

    @patch("app.api.research.generate_comparison")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_500_on_generation_error(
        self, mock_client_fn, mock_search, mock_gen, client
    ):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db, [_paper_row(PAPER_A, "Alpha"), _paper_row(PAPER_B, "Beta")]
        )
        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Alpha", 1, "a")],
            [_chunk(PAPER_B, CHUNK_B, "Beta", 2, "b")],
        ]
        mock_gen.side_effect = Exception("model exploded")

        resp = client.post(
            "/api/research/compare",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 500
        # Stack traces must never leak to the client
        assert "model exploded" not in resp.text


# ---------------------------------------------------------------------------
# Comparison matrix generation — unit tests
# ---------------------------------------------------------------------------


class TestGenerateComparison:
    def _contexts(self, count: int = 2):
        from app.rag.generation.compare import PaperContext

        return [
            PaperContext(
                paper_id=uuid4(),
                paper_title=f"Paper {i + 1}",
                publication_year=2000 + i + 1,
                chunks=[(i + 1, f"content for paper {i + 1}", uuid4()) for i in range(count)],
            )
            for i in range(count)
        ]

    def test_requires_two_papers(self):
        from app.rag.generation.compare import generate_comparison

        with pytest.raises(ValueError, match="At least two papers"):
            generate_comparison(contexts=self._contexts(1))

    def test_raises_without_gemini_key(self):
        from app.rag.generation.compare import generate_comparison

        with patch("app.rag.generation.compare.get_settings") as mock_settings:
            mock_settings.return_value.GEMINI_API_KEY = ""
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
                generate_comparison(contexts=self._contexts(2))

    @patch("app.rag.generation.compare.genai")
    @patch("app.rag.generation.compare.get_settings")
    def test_matrix_has_one_cell_per_paper_per_row(self, mock_settings, mock_genai):
        from app.rag.generation.compare import generate_comparison

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

        import json

        payload = {
            "rows": [
                {
                    "aspect": "Dataset",
                    "cells": [
                        {"paper_index": 1, "summary": "A uses X.", "page_number": 1},
                        {"paper_index": 2, "summary": "B uses Y.", "page_number": 2},
                    ],
                },
                {
                    "aspect": "Limitations",
                    "cells": [
                        {"paper_index": 1, "summary": "Slow.", "page_number": 1},
                        {"paper_index": 2, "not_reported": True, "summary": ""},
                    ],
                },
            ],
            "summary": "They differ on scale.",
        }
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps(payload)
        )

        result = generate_comparison(contexts=self._contexts(2))

        assert len(result.rows) == 6  # default aspect count
        assert all(len(row.cells) == 2 for row in result.rows)
        assert result.summary == "They differ on scale."
        assert result.papers[0].paper_title == "Paper 1"

    @patch("app.rag.generation.compare.genai")
    @patch("app.rag.generation.compare.get_settings")
    def test_missing_cells_become_not_reported(self, mock_settings, mock_genai):
        """A model that omits a cell must not leave a hole in the matrix."""
        import json

        from app.rag.generation.compare import generate_comparison

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

        # Only paper 1 answered; paper 2 omitted entirely.
        payload = {
            "rows": [
                {
                    "aspect": a,
                    "cells": [{"paper_index": 1, "summary": f"{a} for paper 1", "page_number": 1}],
                }
                for a in ["Dataset", "Model", "Method", "Metrics", "Results", "Limitations"]
            ],
            "summary": "s",
        }
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps(payload)
        )

        result = generate_comparison(contexts=self._contexts(2))

        for row in result.rows:
            assert row.cells[0].not_reported is False
            assert row.cells[1].not_reported is True
            assert row.cells[1].summary == "Not reported in the available context."

    @patch("app.rag.generation.compare.genai")
    @patch("app.rag.generation.compare.get_settings")
    def test_invalid_json_degrades_to_empty_matrix(self, mock_settings, mock_genai):
        """Malformed model output must not raise a 500."""
        from app.rag.generation.compare import generate_comparison

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text="not json at all"
        )

        result = generate_comparison(contexts=self._contexts(2))

        assert result.summary == ""
        assert len(result.rows) == 6
        assert all(cell.not_reported for row in result.rows for cell in row.cells)

    @patch("app.rag.generation.compare.genai")
    @patch("app.rag.generation.compare.get_settings")
    def test_citations_are_collected_and_deduplicated(
        self, mock_settings, mock_genai
    ):
        import json

        from app.rag.generation.compare import generate_comparison

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

        payload = {
            "rows": [
                {
                    "aspect": a,
                    "cells": [
                        {"paper_index": 1, "summary": "x", "page_number": 1},
                        {"paper_index": 2, "summary": "y", "page_number": 2},
                    ],
                }
                for a in ["Dataset", "Model", "Method", "Metrics", "Results", "Limitations"]
            ],
            "summary": "s",
        }
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps(payload)
        )

        result = generate_comparison(contexts=self._contexts(2))

        # Same page cited across six rows → exactly two unique chunk IDs
        assert len(result.citations) == 2
        assert result.citation_count == 2

    @patch("app.rag.generation.compare.genai")
    @patch("app.rag.generation.compare.get_settings")
    def test_honours_custom_aspects(self, mock_settings, mock_genai):
        from app.rag.generation.compare import generate_comparison

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text='{"rows": [], "summary": "s"}'
        )

        result = generate_comparison(
            contexts=self._contexts(2), aspects=["Training Regime", "Compute"]
        )

        assert [r.aspect for r in result.rows] == ["Training Regime", "Compute"]

    @patch("app.rag.generation.compare.genai")
    @patch("app.rag.generation.compare.get_settings")
    def test_context_groups_papers_separately(self, mock_settings, mock_genai):
        """Each paper gets its own labelled context group in the prompt."""
        from app.rag.generation.compare import generate_comparison

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"
        generate = MagicMock(return_value=MagicMock(text='{"rows": [], "summary": ""}'))
        mock_genai.Client.return_value.models.generate_content = generate

        generate_comparison(contexts=self._contexts(2))

        prompt = generate.call_args.kwargs["contents"][0].parts[0].text
        assert "--- PAPER 1: Paper 1 (2001) ---" in prompt
        assert "--- PAPER 2: Paper 2 (2002) ---" in prompt
        assert "content for paper 1" in prompt
        assert "content for paper 2" in prompt
