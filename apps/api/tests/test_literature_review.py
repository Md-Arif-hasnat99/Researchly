"""Tests for the literature review API (Part 12).

Covers:
    POST /api/research/literature-review

Plus unit tests for the structured review generation module.

Supabase, retrieval, and Gemini are all mocked — no network calls.
"""

import json
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
CHUNK_C = str(uuid4())


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


def _review_result(**overrides):
    """Build a LiteratureReviewResult for endpoint tests."""
    from app.rag.generation.literature_review import LiteratureReviewResult
    from app.schemas.research import (
        ComparePaperRef,
        ReviewCitation,
        ReviewSection,
    )

    defaults = {
        "title": "Attention and Retrieval in NLP",
        "papers": [
            ComparePaperRef(
                paper_id=PAPER_A,
                paper_title="Attention Is All You Need",
                publication_year=2017,
            ),
            ComparePaperRef(
                paper_id=PAPER_B,
                paper_title="Retrieval-Augmented Generation",
                publication_year=2020,
            ),
        ],
        "sections": [
            ReviewSection(
                heading="Introduction",
                content="Both papers address sequence modelling with attention.",
                citations=[
                    ReviewCitation(
                        paper_id=PAPER_A,
                        paper_title="Attention Is All You Need",
                        page_number=1,
                        chunk_id=CHUNK_A,
                    ),
                    ReviewCitation(
                        paper_id=PAPER_B,
                        paper_title="Retrieval-Augmented Generation",
                        page_number=2,
                        chunk_id=CHUNK_B,
                    ),
                ],
            ),
            ReviewSection(
                heading="Research Gaps",
                content="The retrieved context did not provide enough material.",
                citations=[],
                insufficient_context=True,
            ),
        ],
        "references": [
            ComparePaperRef(
                paper_id=PAPER_A,
                paper_title="Attention Is All You Need",
                publication_year=2017,
            ),
            ComparePaperRef(
                paper_id=PAPER_B,
                paper_title="Retrieval-Augmented Generation",
                publication_year=2020,
            ),
        ],
        "citations": [CHUNK_A, CHUNK_B],
    }
    defaults.update(overrides)
    return LiteratureReviewResult(**defaults)


# ---------------------------------------------------------------------------
# POST /api/research/literature-review — happy path
# ---------------------------------------------------------------------------


class TestLiteratureReviewEndpoint:
    @patch("app.api.research.generate_literature_review")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_returns_structured_sections(self, mock_client_fn, mock_search, mock_gen, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db,
            [
                _paper_row(PAPER_A, "Attention Is All You Need", 2017),
                _paper_row(PAPER_B, "Retrieval-Augmented Generation", 2020),
            ],
        )
        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Attention Is All You Need", 1, "a")],
            [_chunk(PAPER_B, CHUNK_B, "Retrieval-Augmented Generation", 2, "b")],
        ]
        mock_gen.return_value = _review_result()

        resp = client.post(
            "/api/research/literature-review",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "Attention and Retrieval in NLP"
        assert [s["heading"] for s in body["sections"]] == ["Introduction", "Research Gaps"]
        assert body["sections"][0]["citations"][0]["page_number"] == 1
        assert body["sections"][1]["insufficient_context"] is True
        assert len(body["references"]) == 2
        assert body["citations"] == [CHUNK_A, CHUNK_B]

    @patch("app.api.research.generate_literature_review")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_forwards_title_focus_and_sections(
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
        mock_gen.return_value = _review_result()

        resp = client.post(
            "/api/research/literature-review",
            json={
                "paper_ids": [PAPER_A, PAPER_B],
                "title": "My Review",
                "focus": "evaluation methodology",
                "sections": ["Introduction", "Limitations"],
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert mock_gen.call_args.kwargs["title"] == "My Review"
        assert mock_gen.call_args.kwargs["focus"] == "evaluation methodology"
        assert mock_gen.call_args.kwargs["sections"] == ["Introduction", "Limitations"]

    @patch("app.api.research.generate_literature_review")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_retrieval_is_scoped_per_paper(
        self, mock_client_fn, mock_search, mock_gen, client
    ):
        """Each paper is retrieved independently so source identity survives."""
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
            [_chunk(PAPER_C, CHUNK_C, "Gamma", 3, "c")],
        ]
        mock_gen.return_value = _review_result()

        resp = client.post(
            "/api/research/literature-review",
            json={"paper_ids": [PAPER_A, PAPER_B, PAPER_C]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert mock_search.call_count == 3
        for call in mock_search.call_args_list:
            assert len(call.kwargs["paper_ids"]) == 1
            assert call.kwargs["similarity_threshold"] == 0.0
        # Without a focus, the review's own neutral probe is embedded.
        assert "limitations" in mock_search.call_args_list[0].kwargs["query"]

    def test_unauthenticated_returns_401(self, client):
        resp = client.post(
            "/api/research/literature-review",
            json={"paper_ids": [PAPER_A, PAPER_B]},
        )
        assert resp.status_code == 401

    def test_single_paper_returns_422(self, client):
        resp = client.post(
            "/api/research/literature-review",
            json={"paper_ids": [PAPER_A]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_missing_paper_ids_returns_422(self, client):
        resp = client.post(
            "/api/research/literature-review",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/research/literature-review — error paths
# ---------------------------------------------------------------------------


class TestLiteratureReviewErrors:
    @patch("app.api.research.get_supabase_client")
    def test_unowned_paper_returns_404(self, mock_client_fn, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(mock_db, [_paper_row(PAPER_A, "Alpha")])

        resp = client.post(
            "/api/research/literature-review",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @patch("app.api.research.get_supabase_client")
    def test_unindexed_paper_returns_409(self, mock_client_fn, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        row_b = _paper_row(PAPER_B, "Beta")
        row_b["status"] = "processing"
        _stub_ownership(mock_db, [_paper_row(PAPER_A, "Alpha"), row_b])

        resp = client.post(
            "/api/research/literature-review",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409
        # The 409 message is review-specific, not compare-specific.
        assert "synthesized" in resp.json()["detail"].lower()

    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_409_when_fewer_than_two_papers_have_chunks(
        self, mock_client_fn, mock_search, client
    ):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db, [_paper_row(PAPER_A, "Alpha"), _paper_row(PAPER_B, "Beta")]
        )
        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Alpha", 1, "a")],
            [],
        ]

        resp = client.post(
            "/api/research/literature-review",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409

    @patch("app.api.research.generate_literature_review")
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
            "/api/research/literature-review",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 503

    @patch("app.api.research.generate_literature_review")
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
            "/api/research/literature-review",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 500
        assert "model exploded" not in resp.text


# ---------------------------------------------------------------------------
# Literature review generation — unit tests
# ---------------------------------------------------------------------------


class TestGenerateLiteratureReview:
    def _contexts(self, count: int = 2):
        """Build `count` paper contexts, each with exactly one chunk."""
        from app.rag.generation.compare import PaperContext

        return [
            PaperContext(
                paper_id=uuid4(),
                paper_title=f"Paper {i + 1}",
                publication_year=2000 + i + 1,
                chunks=[(i + 1, f"content for paper {i + 1}", uuid4())],
            )
            for i in range(count)
        ]

    def test_requires_two_papers(self):
        from app.rag.generation.literature_review import generate_literature_review

        with pytest.raises(ValueError, match="At least two papers"):
            generate_literature_review(contexts=self._contexts(1))

    def test_raises_without_gemini_key(self):
        from app.rag.generation.literature_review import generate_literature_review

        with patch("app.rag.generation.literature_review.get_settings") as mock_settings:
            mock_settings.return_value.GEMINI_API_KEY = ""
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
                generate_literature_review(contexts=self._contexts(2))

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_sections_follow_the_fr12_order(self, mock_settings, mock_genai):
        from app.rag.generation.literature_review import generate_literature_review
        from app.schemas.research import DEFAULT_REVIEW_SECTIONS

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

        # Model returns sections out of order; output must still be ordered.
        payload = {
            "title": "Synthesized Title",
            "sections": [
                {
                    "heading": "Research Gaps",
                    "content": "Few address retrieval freshness.",
                    "paper_indices": [1, 2],
                },
                {
                    "heading": "Introduction",
                    "content": "Both use attention.",
                    "paper_indices": [1, 2],
                },
            ],
        }
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps(payload)
        )

        result = generate_literature_review(contexts=self._contexts(2))

        assert result.title == "Synthesized Title"
        assert [s.heading for s in result.sections] == DEFAULT_REVIEW_SECTIONS
        # The model omitted four sections; they must appear as flagged stubs.
        stubbed = [s for s in result.sections if s.insufficient_context]
        assert len(stubbed) == 5
        assert all("did not provide enough material" in s.content for s in stubbed)

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_citations_map_paper_indices_to_real_chunk_ids(
        self, mock_settings, mock_genai
    ):
        from app.rag.generation.literature_review import generate_literature_review

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

        contexts = self._contexts(2)
        chunk_a = contexts[0].chunks[0][2]
        chunk_b = contexts[1].chunks[0][2]

        payload = {
            "title": "T",
            "sections": [
                {
                    "heading": "Introduction",
                    "content": "Grounded content.",
                    "paper_indices": [1, 2],
                }
            ],
        }
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps(payload)
        )

        result = generate_literature_review(
            contexts=contexts, sections=["Introduction"]
        )

        section = result.sections[0]
        assert section.insufficient_context is False
        assert [c.chunk_id for c in section.citations] == [chunk_a, chunk_b]
        assert [c.page_number for c in section.citations] == [1, 2]
        assert result.citations == [chunk_a, chunk_b]
        assert len(result.references) == 2

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_invalid_indices_are_ignored(self, mock_settings, mock_genai):
        """Out-of-range or non-numeric indices must not resolve to citations."""
        from app.rag.generation.literature_review import generate_literature_review

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

        payload = {
            "title": "T",
            "sections": [
                {
                    "heading": "Introduction",
                    "content": "Grounded.",
                    "paper_indices": [0, 99, "x", None, 1],
                }
            ],
        }
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps(payload)
        )

        result = generate_literature_review(
            contexts=self._contexts(2), sections=["Introduction"]
        )

        assert len(result.sections[0].citations) == 1

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_insufficient_context_flag_overrides_padded_content(
        self, mock_settings, mock_genai
    ):
        """A flagged section is surfaced as a stub, not as model prose."""
        from app.rag.generation.literature_review import generate_literature_review

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

        payload = {
            "title": "T",
            "sections": [
                {
                    "heading": "Results",
                    "content": "Paper A achieved 28.4 BLEU on WMT14.",
                    "paper_indices": [1],
                    "insufficient_context": True,
                }
            ],
        }
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps(payload)
        )

        result = generate_literature_review(
            contexts=self._contexts(2), sections=["Results"]
        )

        section = result.sections[0]
        assert section.insufficient_context is True
        assert "BLEU" not in section.content
        assert section.citations == []

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_empty_content_is_treated_as_ungrounded(self, mock_settings, mock_genai):
        from app.rag.generation.literature_review import generate_literature_review

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

        payload = {
            "title": "T",
            "sections": [{"heading": "Introduction", "content": "   "}],
        }
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps(payload)
        )

        result = generate_literature_review(
            contexts=self._contexts(2), sections=["Introduction"]
        )

        assert result.sections[0].insufficient_context is True

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_malformed_json_degrades_to_all_stubs(self, mock_settings, mock_genai):
        from app.rag.generation.literature_review import generate_literature_review
        from app.schemas.research import DEFAULT_REVIEW_SECTIONS

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text="not json at all"
        )

        result = generate_literature_review(contexts=self._contexts(2))

        assert len(result.sections) == len(DEFAULT_REVIEW_SECTIONS)
        assert all(s.insufficient_context for s in result.sections)
        # Falls back to a generated title rather than an empty document.
        assert result.title
        assert result.citations == []

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_requested_title_wins_when_model_omits_one(self, mock_settings, mock_genai):
        from app.rag.generation.literature_review import generate_literature_review

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps({"title": "", "sections": []})
        )

        result = generate_literature_review(
            contexts=self._contexts(2), title="Requested Title"
        )

        assert result.title == "Requested Title"

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_honours_custom_sections(self, mock_settings, mock_genai):
        from app.rag.generation.literature_review import generate_literature_review

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps({"title": "T", "sections": []})
        )

        result = generate_literature_review(
            contexts=self._contexts(2), sections=["Data Provenance", "Compute Cost"]
        )

        assert [s.heading for s in result.sections] == ["Data Provenance", "Compute Cost"]

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_context_groups_papers_separately(self, mock_settings, mock_genai):
        from app.rag.generation.literature_review import generate_literature_review

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"
        payload = json.dumps({"title": "T", "sections": []})
        generate = MagicMock(return_value=MagicMock(text=payload))
        mock_genai.Client.return_value.models.generate_content = generate

        generate_literature_review(contexts=self._contexts(2))

        prompt = generate.call_args.kwargs["contents"][0].parts[0].text
        assert "--- PAPER 1: Paper 1 (2001) ---" in prompt
        assert "--- PAPER 2: Paper 2 (2002) ---" in prompt
        assert "content for paper 1" in prompt
        assert "content for paper 2" in prompt

    @patch("app.rag.generation.literature_review.genai")
    @patch("app.rag.generation.literature_review.get_settings")
    def test_references_only_include_cited_papers(self, mock_settings, mock_genai):
        """A paper the model never drew on must not appear in references."""
        from app.rag.generation.literature_review import generate_literature_review

        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

        payload = {
            "title": "T",
            "sections": [
                {
                    "heading": "Introduction",
                    "content": "Only paper one here.",
                    "paper_indices": [1],
                }
            ],
        }
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=json.dumps(payload)
        )

        result = generate_literature_review(
            contexts=self._contexts(2), sections=["Introduction"]
        )

        assert len(result.papers) == 2
        assert len(result.references) == 1
        assert result.references[0].paper_title == "Paper 1"

    def test_to_response_projects_all_fields(self):
        result = _review_result()
        response = result.to_response()

        assert response.title == result.title
        assert len(response.sections) == len(result.sections)
        # Pydantic coerces the string constants to UUID on the schema.
        assert str(response.sections[0].citations[0].chunk_id) == CHUNK_A
        assert response.sections[1].insufficient_context is True
        assert [str(c) for c in response.citations] == [CHUNK_A, CHUNK_B]
