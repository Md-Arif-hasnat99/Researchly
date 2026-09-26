"""Tests for the research gap API (Part 13).

Covers:
    POST /api/research/gaps

Plus unit tests for the gap extraction module.

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


def _gap_result(**overrides):
    """Build a GapResult for endpoint tests."""
    from app.rag.generation.gaps import GapResult
    from app.schemas.research import (
        ComparePaperRef,
        GapCategory,
        GapCitation,
        GapCluster,
        ResearchGap,
    )

    defaults = {
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
        "clusters": [
            GapCluster(
                category=GapCategory.limitation,
                gaps=[
                    ResearchGap(
                        title="Quadratic attention cost",
                        category=GapCategory.limitation,
                        description="Self-attention scales quadratically with length.",
                        evidence="The authors note computation grows quickly with length.",
                        suggested_direction="Explore sparse attention patterns.",
                        paper_ids=[PAPER_A, PAPER_B],
                        citations=[
                            GapCitation(
                                paper_id=PAPER_A,
                                paper_title="Attention Is All You Need",
                                page_number=6,
                                chunk_id=CHUNK_A,
                            ),
                            GapCitation(
                                paper_id=PAPER_B,
                                paper_title="Retrieval-Augmented Generation",
                                page_number=8,
                                chunk_id=CHUNK_B,
                            ),
                        ],
                        recurrence=2,
                    )
                ],
            )
        ],
        "summary": "Both papers flag compute cost as a shared limitation.",
        "citations": [CHUNK_A, CHUNK_B],
    }
    defaults.update(overrides)
    return GapResult(**defaults)


# ---------------------------------------------------------------------------
# POST /api/research/gaps — happy path
# ---------------------------------------------------------------------------


class TestGapsEndpoint:
    @patch("app.api.research.identify_research_gaps")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_returns_clustered_gaps(self, mock_client_fn, mock_search, mock_gen, client):
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
            [_chunk(PAPER_A, CHUNK_A, "Attention Is All You Need", 6, "a")],
            [_chunk(PAPER_B, CHUNK_B, "Retrieval-Augmented Generation", 8, "b")],
        ]
        mock_gen.return_value = _gap_result()

        resp = client.post(
            "/api/research/gaps",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["clusters"][0]["category"] == "Limitation"
        gap = body["clusters"][0]["gaps"][0]
        assert gap["recurrence"] == 2
        assert len(gap["citations"]) == 2
        assert gap["citations"][0]["page_number"] == 6
        assert gap["evidence"]
        assert body["summary"].startswith("Both papers flag")
        assert body["citations"] == [CHUNK_A, CHUNK_B]

    @patch("app.api.research.identify_research_gaps")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_forwards_categories_and_focus(
        self, mock_client_fn, mock_search, mock_gen, client
    ):
        from app.schemas.research import GapCategory

        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db, [_paper_row(PAPER_A, "Alpha"), _paper_row(PAPER_B, "Beta")]
        )
        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Alpha", 1, "a")],
            [_chunk(PAPER_B, CHUNK_B, "Beta", 2, "b")],
        ]
        mock_gen.return_value = _gap_result()

        resp = client.post(
            "/api/research/gaps",
            json={
                "paper_ids": [PAPER_A, PAPER_B],
                "categories": ["Future Work", "Methodological Gap"],
                "focus": "reproducibility",
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert mock_gen.call_args.kwargs["categories"] == [
            GapCategory.future_work,
            GapCategory.methodological_gap,
        ]
        assert mock_gen.call_args.kwargs["focus"] == "reproducibility"

    @patch("app.api.research.identify_research_gaps")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_omits_categories_when_not_requested(
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
        mock_gen.return_value = _gap_result()

        resp = client.post(
            "/api/research/gaps",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert mock_gen.call_args.kwargs["categories"] is None

    @patch("app.api.research.identify_research_gaps")
    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_retrieval_uses_the_gap_probe(self, mock_client_fn, mock_search, mock_gen, client):
        """Without a focus, gap analysis embeds its own limitations probe."""
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db, [_paper_row(PAPER_A, "Alpha"), _paper_row(PAPER_B, "Beta")]
        )
        mock_search.side_effect = [
            [_chunk(PAPER_A, CHUNK_A, "Alpha", 1, "a")],
            [_chunk(PAPER_B, CHUNK_B, "Beta", 2, "b")],
        ]
        mock_gen.return_value = _gap_result()

        resp = client.post(
            "/api/research/gaps",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        query = mock_search.call_args_list[0].kwargs["query"]
        assert "limitations" in query
        assert "future work" in query
        for call in mock_search.call_args_list:
            assert len(call.kwargs["paper_ids"]) == 1

    def test_unauthenticated_returns_401(self, client):
        resp = client.post(
            "/api/research/gaps",
            json={"paper_ids": [PAPER_A]},
        )
        assert resp.status_code == 401

    def test_missing_paper_ids_returns_422(self, client):
        resp = client.post(
            "/api/research/gaps",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_too_many_papers_returns_422(self, client):
        resp = client.post(
            "/api/research/gaps",
            json={"paper_ids": [str(uuid4()) for _ in range(11)]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_invalid_category_returns_422(self, client):
        resp = client.post(
            "/api/research/gaps",
            json={"paper_ids": [PAPER_A], "categories": ["Vibes"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_single_paper_is_allowed(self, mock_client_fn, mock_search, client):
        """Unlike compare/review, gap analysis works on one paper."""
        from app.schemas.research import GapCategory

        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(mock_db, [_paper_row(PAPER_A, "Alpha")])
        mock_search.return_value = [_chunk(PAPER_A, CHUNK_A, "Alpha", 3, "a")]

        with patch("app.api.research.identify_research_gaps") as mock_gen:
            mock_gen.return_value = _gap_result(clusters=[], citations=[])
            resp = client.post(
                "/api/research/gaps",
                json={"paper_ids": [PAPER_A]},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["clusters"] == []
        assert mock_gen.call_args.kwargs["categories"] is None
        assert GapCategory.limitation.value == "Limitation"


# ---------------------------------------------------------------------------
# POST /api/research/gaps — error paths
# ---------------------------------------------------------------------------


class TestGapsErrors:
    @patch("app.api.research.get_supabase_client")
    def test_unowned_paper_returns_404(self, mock_client_fn, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(mock_db, [_paper_row(PAPER_A, "Alpha")])

        resp = client.post(
            "/api/research/gaps",
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
            "/api/research/gaps",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409
        # The 409 message is gap-specific, not compare-specific.
        assert "analysed" in resp.json()["detail"].lower()

    @patch("app.api.research.similarity_search")
    @patch("app.api.research.get_supabase_client")
    def test_409_when_no_paper_has_chunks(self, mock_client_fn, mock_search, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        _stub_ownership(
            mock_db, [_paper_row(PAPER_A, "Alpha"), _paper_row(PAPER_B, "Beta")]
        )
        mock_search.side_effect = [[], []]

        resp = client.post(
            "/api/research/gaps",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409
        assert "no indexed content" in resp.json()["detail"].lower()

    @patch("app.api.research.identify_research_gaps")
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
            "/api/research/gaps",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 503

    @patch("app.api.research.identify_research_gaps")
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
            "/api/research/gaps",
            json={"paper_ids": [PAPER_A, PAPER_B]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 500
        assert "model exploded" not in resp.text


# ---------------------------------------------------------------------------
# Gap extraction — unit tests
# ---------------------------------------------------------------------------


class TestIdentifyResearchGaps:
    def _contexts(self, count: int = 2):
        """Build `count` paper contexts, each with one chunk on page `i+1`."""
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

    def _mock_model(self, mock_genai, payload: str):
        mock_genai.Client.return_value.models.generate_content.return_value = MagicMock(
            text=payload
        )

    def _settings(self, mock_settings):
        mock_settings.return_value.GEMINI_API_KEY = "key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"

    def test_requires_at_least_one_paper(self):
        from app.rag.generation.gaps import identify_research_gaps

        with pytest.raises(ValueError, match="At least one paper"):
            identify_research_gaps(contexts=[])

    def test_raises_without_gemini_key(self):
        from app.rag.generation.gaps import identify_research_gaps

        with patch("app.rag.generation.gaps.get_settings") as mock_settings:
            mock_settings.return_value.GEMINI_API_KEY = ""
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
                identify_research_gaps(contexts=self._contexts(2))

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_gaps_are_clustered_by_category(self, mock_settings, mock_genai):
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        payload = {
            "gaps": [
                {
                    "title": "Quadratic cost",
                    "category": "Limitation",
                    "description": "Cost grows with length.",
                    "evidence": "Authors note it.",
                    "suggested_direction": "Try sparse attention.",
                    "paper_indices": [1, 2],
                    "page_numbers": [1, 2],
                },
                {
                    "title": "No robustness tests",
                    "category": "Methodological Gap",
                    "description": "Robustness is untested.",
                    "evidence": "No perturbation study.",
                    "paper_indices": [1],
                    "page_numbers": [1],
                },
            ],
            "summary": "Two recurring gaps.",
        }
        self._mock_model(mock_genai, json.dumps(payload))

        result = identify_research_gaps(contexts=self._contexts(2))

        assert [c.category.value for c in result.clusters] == [
            "Limitation",
            "Methodological Gap",
        ]
        assert result.gap_count == 2
        assert result.summary == "Two recurring gaps."

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_citations_resolve_to_real_chunk_ids(self, mock_settings, mock_genai):
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        contexts = self._contexts(2)
        chunk_a = contexts[0].chunks[0][2]
        chunk_b = contexts[1].chunks[0][2]

        payload = {
            "gaps": [
                {
                    "title": "Shared limitation",
                    "category": "Limitation",
                    "description": "Both flag it.",
                    "paper_indices": [1, 2],
                    "page_numbers": [1, 2],
                }
            ],
            "summary": "s",
        }
        self._mock_model(mock_genai, json.dumps(payload))

        result = identify_research_gaps(contexts=contexts)

        gap = result.clusters[0].gaps[0]
        assert [str(c.chunk_id) for c in gap.citations] == [str(chunk_a), str(chunk_b)]
        assert [c.page_number for c in gap.citations] == [1, 2]
        assert result.citations == [chunk_a, chunk_b]
        assert gap.recurrence == 2

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_unattributed_gaps_are_dropped(self, mock_settings, mock_genai):
        """A gap with no supplied paper behind it must not be reported."""
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        payload = {
            "gaps": [
                {
                    "title": "Hallucinated gap",
                    "category": "Limitation",
                    "description": "Nothing in context supports this.",
                    "paper_indices": [99],
                    "page_numbers": [1],
                },
                {
                    "title": "Grounded gap",
                    "category": "Limitation",
                    "description": "Supported by paper 1.",
                    "paper_indices": [1],
                    "page_numbers": [1],
                },
            ],
            "summary": "s",
        }
        self._mock_model(mock_genai, json.dumps(payload))

        result = identify_research_gaps(contexts=self._contexts(2))

        assert result.gap_count == 1
        assert result.clusters[0].gaps[0].title == "Grounded gap"

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_unrequested_category_is_dropped(self, mock_settings, mock_genai):
        from app.rag.generation.gaps import GapCategory, identify_research_gaps

        self._settings(mock_settings)
        payload = {
            "gaps": [
                {
                    "title": "Future work item",
                    "category": "Future Work",
                    "description": "Deferred to future research.",
                    "paper_indices": [1],
                    "page_numbers": [1],
                },
                {
                    "title": "A limitation",
                    "category": "Limitation",
                    "description": "Acknowledged weakness.",
                    "paper_indices": [1],
                    "page_numbers": [1],
                },
            ],
            "summary": "s",
        }
        self._mock_model(mock_genai, json.dumps(payload))

        result = identify_research_gaps(
            contexts=self._contexts(2), categories=[GapCategory.limitation]
        )

        assert result.gap_count == 1
        assert result.clusters[0].gaps[0].title == "A limitation"

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_most_recurring_gaps_sort_first(self, mock_settings, mock_genai):
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        payload = {
            "gaps": [
                {
                    "title": "One-off remark",
                    "category": "Limitation",
                    "description": "Single paper.",
                    "paper_indices": [1],
                    "page_numbers": [1],
                },
                {
                    "title": "Widely reported",
                    "category": "Limitation",
                    "description": "All papers.",
                    "paper_indices": [1, 2],
                    "page_numbers": [1, 2],
                },
            ],
            "summary": "s",
        }
        self._mock_model(mock_genai, json.dumps(payload))

        result = identify_research_gaps(contexts=self._contexts(2))

        titles = [g.title for g in result.clusters[0].gaps]
        assert titles == ["Widely reported", "One-off remark"]

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_empty_gap_list_is_valid(self, mock_settings, mock_genai):
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        self._mock_model(mock_genai, json.dumps({"gaps": [], "summary": "No gaps found."}))

        result = identify_research_gaps(contexts=self._contexts(2))

        assert result.gap_count == 0
        assert result.clusters == []
        assert result.citations == []
        assert result.summary == "No gaps found."

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_malformed_json_returns_no_gaps(self, mock_settings, mock_genai):
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        self._mock_model(mock_genai, "not json at all")

        result = identify_research_gaps(contexts=self._contexts(2))

        assert result.gap_count == 0
        assert result.summary == ""

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_pages_outside_retrieved_chunks_fall_back(self, mock_settings, mock_genai):
        """A model-cited page with no retrieved chunk must not be trusted."""
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        payload = {
            "gaps": [
                {
                    "title": "Gap with bogus page",
                    "category": "Limitation",
                    "description": "d",
                    "paper_indices": [1],
                    "page_numbers": [999],
                }
            ],
            "summary": "s",
        }
        self._mock_model(mock_genai, json.dumps(payload))

        result = identify_research_gaps(contexts=self._contexts(2))

        citation = result.clusters[0].gaps[0].citations[0]
        # Falls back to the only retrieved page (1), not the model's 999.
        assert citation.page_number == 1

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_category_matching_is_case_insensitive(self, mock_settings, mock_genai):
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        payload = {
            "gaps": [
                {
                    "title": "A gap",
                    "category": "dataset limitation",
                    "description": "d",
                    "paper_indices": [1],
                    "page_numbers": [1],
                }
            ],
            "summary": "s",
        }
        self._mock_model(mock_genai, json.dumps(payload))

        result = identify_research_gaps(contexts=self._contexts(2))

        assert result.clusters[0].category.value == "Dataset Limitation"

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_gaps_missing_required_fields_are_skipped(self, mock_settings, mock_genai):
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        payload = {
            "gaps": [
                {"category": "Limitation", "description": "no title"},
                {"title": "no description", "category": "Limitation"},
                {"title": "bad category", "description": "d", "category": "Nonsense"},
                "not even an object",
                {
                    "title": "Good",
                    "description": "d",
                    "category": "Limitation",
                    "paper_indices": [1],
                    "page_numbers": [1],
                },
            ],
            "summary": "s",
        }
        self._mock_model(mock_genai, json.dumps(payload))

        result = identify_research_gaps(contexts=self._contexts(2))

        assert result.gap_count == 1
        assert result.clusters[0].gaps[0].title == "Good"

    @patch("app.rag.generation.gaps.genai")
    @patch("app.rag.generation.gaps.get_settings")
    def test_context_groups_papers_separately(self, mock_settings, mock_genai):
        from app.rag.generation.gaps import identify_research_gaps

        self._settings(mock_settings)
        generate = MagicMock(
            return_value=MagicMock(text=json.dumps({"gaps": [], "summary": ""}))
        )
        mock_genai.Client.return_value.models.generate_content = generate

        identify_research_gaps(contexts=self._contexts(2))

        prompt = generate.call_args.kwargs["contents"][0].parts[0].text
        assert "--- PAPER 1: Paper 1 (2001) ---" in prompt
        assert "--- PAPER 2: Paper 2 (2002) ---" in prompt
        assert "content for paper 1" in prompt
        assert "content for paper 2" in prompt

    def test_to_response_projects_all_fields(self):
        from app.schemas.research import GapCategory

        result = _gap_result()
        response = result.to_response()

        assert len(response.clusters) == 1
        assert response.clusters[0].category == GapCategory.limitation
        assert response.clusters[0].gaps[0].recurrence == 2
        assert [str(c) for c in response.citations] == [CHUNK_A, CHUNK_B]
        assert result.citation_count == 2
        assert result.gap_count == 1
