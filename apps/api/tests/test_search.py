"""Tests for the retrieval module (app.rag.retrieval.search) and
the POST /api/search endpoint.

All tests are fully deterministic — no real Gemini or Supabase calls
are made.  External calls are patched at the import boundary.
"""

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_application
from app.schemas.search import SearchResultChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_VECTOR = [0.1] * 768
USER_ID = "00000000-0000-0000-0000-000000000001"
PAPER_ID = str(uuid4())
CHUNK_ID = str(uuid4())

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}


def _make_rpc_row(
    chunk_id: str = CHUNK_ID,
    paper_id: str = PAPER_ID,
    paper_title: str = "Test Paper",
    page_number: int = 3,
    section: str | None = "Results",
    content: str = "Some relevant chunk content.",
    similarity: float = 0.88,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "paper_id": paper_id,
        "paper_title": paper_title,
        "page_number": page_number,
        "section": section,
        "content": content,
        "similarity": similarity,
    }


# ---------------------------------------------------------------------------
# Unit tests: app.rag.retrieval.search.similarity_search
# ---------------------------------------------------------------------------


class TestSimilaritySearch:
    @patch("app.rag.retrieval.search.get_supabase_client")
    @patch("app.rag.retrieval.search.embed_query")
    def test_returns_results(self, mock_embed, mock_client_fn):
        """Happy path: returns a list of SearchResultChunk."""
        mock_embed.return_value = FAKE_VECTOR

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_rpc = MagicMock()
        mock_client.rpc.return_value = mock_rpc
        mock_rpc.execute.return_value = MagicMock(data=[_make_rpc_row()])

        from app.rag.retrieval.search import similarity_search

        results = similarity_search(
            query="test query",
            user_id=USER_ID,
            top_k=8,
            similarity_threshold=0.65,
        )

        assert len(results) == 1
        r = results[0]
        assert isinstance(r, SearchResultChunk)
        assert r.chunk_id == UUID(CHUNK_ID)
        assert r.paper_id == UUID(PAPER_ID)
        assert r.paper_title == "Test Paper"
        assert r.page_number == 3
        assert r.section == "Results"
        assert r.similarity_score == 0.88

    @patch("app.rag.retrieval.search.get_supabase_client")
    @patch("app.rag.retrieval.search.embed_query")
    def test_empty_results(self, mock_embed, mock_client_fn):
        """Returns an empty list when there are no matching chunks."""
        mock_embed.return_value = FAKE_VECTOR

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_rpc = MagicMock()
        mock_client.rpc.return_value = mock_rpc
        mock_rpc.execute.return_value = MagicMock(data=[])

        from app.rag.retrieval.search import similarity_search

        results = similarity_search(query="nothing here", user_id=USER_ID)

        assert results == []

    @patch("app.rag.retrieval.search.get_supabase_client")
    @patch("app.rag.retrieval.search.embed_query")
    def test_paper_ids_passed_to_rpc(self, mock_embed, mock_client_fn):
        """When paper_ids is provided the RPC is called with those IDs."""
        mock_embed.return_value = FAKE_VECTOR

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_rpc = MagicMock()
        mock_client.rpc.return_value = mock_rpc
        mock_rpc.execute.return_value = MagicMock(data=[])

        pid = uuid4()

        from app.rag.retrieval.search import similarity_search

        similarity_search(
            query="q",
            user_id=USER_ID,
            paper_ids=[pid],
        )

        call_kwargs = mock_client.rpc.call_args
        rpc_params = call_kwargs[0][1]  # second positional arg to rpc()
        assert rpc_params["filter_paper_ids"] == [str(pid)]

    @patch("app.rag.retrieval.search.get_supabase_client")
    @patch("app.rag.retrieval.search.embed_query")
    def test_null_paper_ids_when_none(self, mock_embed, mock_client_fn):
        """When paper_ids is None the RPC receives filter_paper_ids=None."""
        mock_embed.return_value = FAKE_VECTOR

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_rpc = MagicMock()
        mock_client.rpc.return_value = mock_rpc
        mock_rpc.execute.return_value = MagicMock(data=[])

        from app.rag.retrieval.search import similarity_search

        similarity_search(query="q", user_id=USER_ID, paper_ids=None)

        call_kwargs = mock_client.rpc.call_args
        rpc_params = call_kwargs[0][1]
        assert rpc_params["filter_paper_ids"] is None

    @patch("app.rag.retrieval.search.embed_query")
    def test_propagates_embed_error(self, mock_embed):
        """RuntimeError from embed_query bubbles up unchanged."""
        mock_embed.side_effect = RuntimeError("GEMINI_API_KEY is not configured.")

        from app.rag.retrieval.search import similarity_search

        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            similarity_search(query="q", user_id=USER_ID)

    @patch("app.rag.retrieval.search.get_supabase_client")
    @patch("app.rag.retrieval.search.embed_query")
    def test_section_can_be_none(self, mock_embed, mock_client_fn):
        """section=None is valid and maps to None in the result."""
        mock_embed.return_value = FAKE_VECTOR

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_rpc = MagicMock()
        mock_client.rpc.return_value = mock_rpc
        mock_rpc.execute.return_value = MagicMock(data=[_make_rpc_row(section=None)])

        from app.rag.retrieval.search import similarity_search

        results = similarity_search(query="q", user_id=USER_ID)
        assert results[0].section is None


# ---------------------------------------------------------------------------
# Integration tests: POST /api/search endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    app = create_application()
    return TestClient(app)


class TestSearchEndpoint:
    @patch("app.api.search.similarity_search")
    def test_success(self, mock_search, client):
        """POST /api/search returns 200 with results."""
        mock_search.return_value = [
            SearchResultChunk(
                chunk_id=UUID(CHUNK_ID),
                paper_id=UUID(PAPER_ID),
                paper_title="Test Paper",
                page_number=3,
                section="Results",
                content="Some content",
                similarity_score=0.88,
            )
        ]

        resp = client.post(
            "/api/search",
            json={"query": "what datasets were used?"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "what datasets were used?"
        assert body["total_results"] == 1
        r = body["results"][0]
        assert r["paper_title"] == "Test Paper"
        assert r["page_number"] == 3
        assert r["similarity_score"] == 0.88

    @patch("app.api.search.similarity_search")
    def test_empty_results(self, mock_search, client):
        """Returns 200 with an empty list when nothing matches."""
        mock_search.return_value = []

        resp = client.post(
            "/api/search",
            json={"query": "obscure topic with no matches"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_results"] == 0
        assert body["results"] == []

    def test_unauthenticated(self, client):
        """Returns 401 when no Authorization header is provided."""
        resp = client.post("/api/search", json={"query": "test"})
        assert resp.status_code == 401

    def test_empty_query_rejected(self, client):
        """Returns 422 when query is an empty string."""
        resp = client.post(
            "/api/search",
            json={"query": ""},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_top_k_out_of_range(self, client):
        """Returns 422 when top_k exceeds maximum (20)."""
        resp = client.post(
            "/api/search",
            json={"query": "test", "top_k": 99},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_similarity_threshold_out_of_range(self, client):
        """Returns 422 when similarity_threshold > 1."""
        resp = client.post(
            "/api/search",
            json={"query": "test", "similarity_threshold": 1.5},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    @patch("app.api.search.similarity_search")
    def test_paper_ids_filter_passed_through(self, mock_search, client):
        """paper_ids are forwarded to similarity_search."""
        mock_search.return_value = []
        pid = str(uuid4())

        client.post(
            "/api/search",
            json={"query": "test", "paper_ids": [pid]},
            headers=AUTH_HEADERS,
        )

        call_kwargs = mock_search.call_args[1]
        assert call_kwargs["paper_ids"] is not None
        assert str(call_kwargs["paper_ids"][0]) == pid

    @patch("app.api.search.similarity_search")
    def test_503_on_runtime_error(self, mock_search, client):
        """Returns 503 when GEMINI_API_KEY is not configured."""
        mock_search.side_effect = RuntimeError("GEMINI_API_KEY is not configured.")

        resp = client.post(
            "/api/search",
            json={"query": "test"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 503

    @patch("app.api.search.similarity_search")
    def test_500_on_unexpected_error(self, mock_search, client):
        """Returns 500 on any unexpected exception."""
        mock_search.side_effect = Exception("DB connection refused")

        resp = client.post(
            "/api/search",
            json={"query": "test"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 500
