"""Tests for the retrieval module (app.rag.retrieval.search) and
the POST /api/search endpoint.

Covers vector search, keyword search, Reciprocal Rank Fusion, and the
hybrid endpoint (Part 14, FR-14).

All tests are fully deterministic — no real Gemini or Supabase calls
are made.  External calls are patched at the import boundary.  The
SQL-side behaviour of the two Postgres functions is not exercised here;
it lives in supabase/migrations and is covered by integration testing.
"""

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_application
from app.rag.retrieval.search import SearchOutcome
from app.schemas.search import SearchMode, SearchResultChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_VECTOR = [0.1] * 768
USER_ID = "00000000-0000-0000-0000-000000000001"
PAPER_ID = str(uuid4())
CHUNK_ID = str(uuid4())

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}


def _make_chunk(
    chunk_id: str,
    *,
    title: str = "Test Paper",
    page: int = 1,
    similarity: float | None = 0.8,
    sources: list[str] | None = None,
) -> SearchResultChunk:
    """Build a SearchResultChunk for fusion tests.

    The chunk_id is passed in rather than generated so tests can control
    which chunks both retrievers agree on.
    """
    return SearchResultChunk(
        chunk_id=UUID(chunk_id),
        paper_id=UUID(PAPER_ID),
        paper_title=title,
        page_number=page,
        section="Methods",
        content=f"Content for {chunk_id}",
        similarity_score=similarity,
        matched_by=sources or [],
    )


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
        # Vector hits are tagged so the UI can explain provenance.
        assert r.matched_by == ["vector"]

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
                matched_by=["vector"],
            )
        ]

        resp = client.post(
            "/api/search",
            json={"query": "what datasets were used?", "mode": "vector"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "what datasets were used?"
        assert body["total_results"] == 1
        assert body["mode"] == "vector"
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
            json={"query": "obscure topic with no matches", "mode": "vector"},
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

    def test_whitespace_only_query_rejected(self, client):
        """Returns 422 for a whitespace-only query.

        min_length=1 admits " ", which embeds to noise and yields an empty
        tsquery. A 422 beats an empty 200 that reads like "nothing in your
        library matches".
        """
        resp = client.post(
            "/api/search",
            json={"query": "   "},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_invalid_mode_rejected(self, client):
        """Returns 422 for an unrecognised retrieval mode."""
        resp = client.post(
            "/api/search",
            json={"query": "test", "mode": "telepathy"},
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
            json={"query": "test", "mode": "vector", "paper_ids": [pid]},
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
            json={"query": "test", "mode": "vector"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 503

    @patch("app.api.search.similarity_search")
    def test_500_on_unexpected_error(self, mock_search, client):
        """Returns 500 on any unexpected exception."""
        mock_search.side_effect = Exception("DB connection refused")

        resp = client.post(
            "/api/search",
            json={"query": "test", "mode": "vector"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Part 14: keyword retrieval
# ---------------------------------------------------------------------------


def _make_keyword_row(
    chunk_id: str = CHUNK_ID,
    paper_id: str = PAPER_ID,
    paper_title: str = "Test Paper",
    page_number: int = 5,
    section: str | None = "Architecture",
    content: str = "We fine-tune BERT-base on ImageNet.",
    keyword_rank: float = 1.25,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "paper_id": paper_id,
        "paper_title": paper_title,
        "page_number": page_number,
        "section": section,
        "content": content,
        "keyword_rank": keyword_rank,
    }


def _mock_supabase(mock_client_fn, data: list[dict]):
    """Wire get_supabase_client to a mock whose rpc(...).execute() returns *data*."""
    mock_client = MagicMock()
    mock_client_fn.return_value = mock_client
    mock_rpc = MagicMock()
    mock_client.rpc.return_value = mock_rpc
    mock_rpc.execute.return_value = MagicMock(data=data)
    return mock_client


class TestKeywordSearch:
    @patch("app.rag.retrieval.search.get_supabase_client")
    @patch("app.rag.retrieval.search.embed_query")
    def test_returns_results_without_similarity_score(self, mock_embed, mock_client_fn):
        """Keyword hits carry matched_by=['keyword'] and no vector score.

        There is no vector comparison behind a keyword hit, so
        similarity_score stays None rather than borrowing ts_rank and
        presenting a lexical score as a semantic one.
        """
        _mock_supabase(mock_client_fn, [_make_keyword_row()])

        from app.rag.retrieval.search import keyword_search

        results = keyword_search(query="ImageNet", user_id=USER_ID)

        assert len(results) == 1
        r = results[0]
        assert r.chunk_id == UUID(CHUNK_ID)
        assert r.paper_title == "Test Paper"
        assert r.page_number == 5
        assert r.matched_by == ["keyword"]
        assert r.similarity_score is None
        assert r.fusion_score is None

    @patch("app.rag.retrieval.search.get_supabase_client")
    @patch("app.rag.retrieval.search.embed_query")
    def test_never_embeds_the_query(self, mock_embed, mock_client_fn):
        """Keyword search must not call Gemini.

        This is what makes keyword mode usable with no API key configured.
        """
        _mock_supabase(mock_client_fn, [_make_keyword_row()])

        from app.rag.retrieval.search import keyword_search

        keyword_search(query="ImageNet", user_id=USER_ID)

        mock_embed.assert_not_called()

    @patch("app.rag.retrieval.search.get_supabase_client")
    def test_calls_keyword_rpc_with_params(self, mock_client_fn):
        """The keyword RPC receives the query text, depth, and owner."""
        mock_client = _mock_supabase(mock_client_fn, [])

        from app.rag.retrieval.search import keyword_search

        keyword_search(query="BERT-base", user_id=USER_ID, top_k=5)

        assert mock_client.rpc.call_args[0][0] == "search_paper_chunks_by_keyword"
        rpc_params = mock_client.rpc.call_args[0][1]
        assert rpc_params["query_text"] == "BERT-base"
        assert rpc_params["match_count"] == 5
        assert rpc_params["filter_user_id"] == USER_ID
        assert rpc_params["filter_paper_ids"] is None

    @patch("app.rag.retrieval.search.get_supabase_client")
    def test_paper_ids_passed_to_keyword_rpc(self, mock_client_fn):
        """paper_ids restrict the keyword search to those papers."""
        mock_client = _mock_supabase(mock_client_fn, [])
        pid = uuid4()

        from app.rag.retrieval.search import keyword_search

        keyword_search(query="q", user_id=USER_ID, paper_ids=[pid])

        rpc_params = mock_client.rpc.call_args[0][1]
        assert rpc_params["filter_paper_ids"] == [str(pid)]

    @patch("app.rag.retrieval.search.get_supabase_client")
    def test_empty_results(self, mock_client_fn):
        """A query with no lexical match returns an empty list."""
        _mock_supabase(mock_client_fn, [])

        from app.rag.retrieval.search import keyword_search

        assert keyword_search(query="nothing", user_id=USER_ID) == []


# ---------------------------------------------------------------------------
# Part 14: Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


class TestRRFFusion:
    def test_agreement_between_retrievers_wins(self):
        """A chunk both retrievers found outranks one only the best retriever found.

        This is the whole point of FR-14: the retrievers are individually
        weak exactly where the other is strong, so agreement beats a
        single confident first place.
        """
        from app.rag.retrieval.search import rrf_fuse

        shared = _make_chunk("11111111-1111-1111-1111-111111111111")
        vector_only_top = _make_chunk("22222222-2222-2222-2222-222222222222")

        # vector: [shared(rank 2), vector_only_top(rank 1)]
        # keyword: [shared(rank 1)]
        # shared  = 1/62 + 1/61 ≈ 0.03252
        # top     = 1/61          ≈ 0.01639
        fused = rrf_fuse(
            vector_hits=[vector_only_top, shared],
            keyword_hits=[shared],
            top_k=5,
        )

        assert [str(r.chunk_id) for r in fused] == [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]
        assert fused[0].matched_by == ["vector", "keyword"]

    def test_keyword_only_hit_is_rescued_into_the_results(self):
        """A chunk the vector threshold discarded can still surface via keyword."""
        from app.rag.retrieval.search import rrf_fuse

        # No vector hit for this chunk at all — exactly what happens when
        # an exact dataset name scores below the cosine threshold.
        exact_term = _make_chunk(
            "33333333-3333-3333-3333-333333333333", similarity=None
        )
        semantic = _make_chunk("44444444-4444-4444-4444-444444444444")

        fused = rrf_fuse(
            vector_hits=[semantic],
            keyword_hits=[exact_term],
            top_k=5,
        )

        assert len(fused) == 2
        rescued = next(
            r
            for r in fused
            if str(r.chunk_id) == "33333333-3333-3333-3333-333333333333"
        )
        assert rescued.matched_by == ["keyword"]
        # similarity_score is preserved as None: no vector score was
        # ever computed for this hit.
        assert rescued.similarity_score is None

    def test_fusion_score_is_not_a_similarity_score(self):
        """fusion_score and similarity_score are distinct values.

        Conflating a rank-fusion score with a cosine similarity would
        let the UI print a meaningless "96% similar" for a chunk that was
        only ever ranked, never compared.
        """
        from app.rag.retrieval.search import rrf_fuse

        shared = _make_chunk("55555555-5555-5555-5555-555555555555", similarity=0.42)

        fused = rrf_fuse(vector_hits=[shared], keyword_hits=[shared], top_k=5)

        assert fused[0].similarity_score == 0.42
        assert fused[0].fusion_score is not None
        assert fused[0].fusion_score != fused[0].similarity_score

    def test_truncates_to_top_k(self):
        """Only the requested number of fused results is returned."""
        from app.rag.retrieval.search import rrf_fuse

        vector_hits = [
            _make_chunk(f"{i:08d}-0000-0000-0000-000000000000")
            for i in range(1, 8)
        ]
        keyword_hits = [
            _make_chunk(f"{i:08d}-0000-0000-0000-000000000000")
            for i in range(4, 10)
        ]

        fused = rrf_fuse(vector_hits=vector_hits, keyword_hits=keyword_hits, top_k=3)

        assert len(fused) == 3

    def test_duplicate_within_one_list_counted_once(self):
        """A chunk repeated inside a single retriever's list is not double-scored."""
        from app.rag.retrieval.search import rrf_fuse

        dup = _make_chunk("66666666-6666-6666-6666-666666666666")
        other = _make_chunk("77777777-7777-7777-7777-777777777777")

        single = rrf_fuse(vector_hits=[dup, other], keyword_hits=[], top_k=5)
        doubled = rrf_fuse(
            vector_hits=[dup, dup, other], keyword_hits=[], top_k=5
        )

        assert len(doubled) == 2
        assert str(doubled[0].chunk_id) == "66666666-6666-6666-6666-666666666666"
        # A duplicate must not out-score a clean single-list ranking.
        assert doubled[0].fusion_score == single[0].fusion_score

    def test_empty_inputs(self):
        """Fusing nothing yields nothing rather than raising."""
        from app.rag.retrieval.search import rrf_fuse

        assert rrf_fuse([], [], top_k=5) == []

    def test_single_list_fusion_preserves_its_order(self):
        """With only one retriever contributing, its ordering survives fusion."""
        from app.rag.retrieval.search import rrf_fuse

        first = _make_chunk("88888888-8888-8888-8888-000000000001")
        second = _make_chunk("88888888-8888-8888-8888-000000000002")
        third = _make_chunk("88888888-8888-8888-8888-000000000003")

        fused = rrf_fuse(
            vector_hits=[first, second, third], keyword_hits=[], top_k=5
        )

        assert [str(r.chunk_id) for r in fused] == [
            str(first.chunk_id),
            str(second.chunk_id),
            str(third.chunk_id),
        ]

    def test_ties_break_deterministically(self):
        """Equally scored results are ordered by title then page, not by dict order.

        Scores: A-early 1/63+1/61 and B 1/61+1/63 tie exactly; A-late
        1/62+1/62 is fractionally lower and must sort last despite
        sharing a title with the winner.
        """
        from app.rag.retrieval.search import rrf_fuse

        b = _make_chunk("99999999-0000-0000-0000-000000000002", title="B Paper", page=1)
        a_late = _make_chunk("99999999-0000-0000-0000-000000000001", title="A Paper", page=9)
        a_early = _make_chunk("99999999-0000-0000-0000-000000000003", title="A Paper", page=2)

        # Each retriever returns these in a different order, so the only
        # thing making the output stable is the tie-break.
        fused = rrf_fuse(
            vector_hits=[b, a_late, a_early],
            keyword_hits=[a_early, a_late, b],
            top_k=5,
        )

        assert [(r.paper_title, r.page_number) for r in fused] == [
            ("A Paper", 2),
            ("B Paper", 1),
            ("A Paper", 9),
        ]


# ---------------------------------------------------------------------------
# Part 14: hybrid orchestration
# ---------------------------------------------------------------------------


class TestHybridSearch:
    @patch("app.rag.retrieval.search.keyword_search")
    @patch("app.rag.retrieval.search.similarity_search")
    def test_queries_both_retrievers_deeper_than_top_k(
        self, mock_vector, mock_keyword
    ):
        """Each retriever is asked for more candidates than the caller wants.

        Fusing truncated lists is what FR-14's candidate set is for: a
        chunk one retriever placed 15th may be the other's top hit.
        """
        mock_vector.return_value = []
        mock_keyword.return_value = []

        from app.rag.retrieval.search import hybrid_search

        outcome = hybrid_search(query="q", user_id=USER_ID, top_k=4)

        assert mock_vector.call_args[1]["top_k"] > 4
        assert mock_keyword.call_args[1]["top_k"] > 4
        assert outcome.mode is SearchMode.hybrid
        assert outcome.keyword_degraded is False

    @patch("app.rag.retrieval.search.keyword_search")
    @patch("app.rag.retrieval.search.similarity_search")
    def test_forwards_similarity_threshold_to_vector_side(
        self, mock_vector, mock_keyword
    ):
        """The threshold guards the vector candidates only.

        The point of keyword search is to rescue an exact term that is
        lexically perfect but cosinely distant, so applying the cosine
        threshold to the keyword side would defeat it.
        """
        mock_vector.return_value = []
        mock_keyword.return_value = []

        from app.rag.retrieval.search import hybrid_search

        hybrid_search(query="q", user_id=USER_ID, similarity_threshold=0.9)

        assert mock_vector.call_args[1]["similarity_threshold"] == 0.9

    @patch("app.rag.retrieval.search.keyword_search")
    @patch("app.rag.retrieval.search.similarity_search")
    def test_fuses_and_truncates_to_top_k(self, mock_vector, mock_keyword):
        """The fused result set is truncated to the requested count."""
        mock_vector.return_value = [
            _make_chunk(f"{i:08d}-0000-0000-0000-000000000000")
            for i in range(1, 6)
        ]
        mock_keyword.return_value = [
            _make_chunk(f"{i:08d}-0000-0000-0000-000000000000")
            for i in range(4, 9)
        ]

        from app.rag.retrieval.search import hybrid_search

        outcome = hybrid_search(query="q", user_id=USER_ID, top_k=3)

        assert len(outcome.results) == 3
        # The chunk at index 4 is in both lists, so it is fused rather
        # than dropped by either side's truncation.
        assert any(
            r.matched_by == ["vector", "keyword"] for r in outcome.results
        )

    @patch("app.rag.retrieval.search.keyword_search")
    @patch("app.rag.retrieval.search.similarity_search")
    def test_degrades_to_vector_only_when_keyword_fails(
        self, mock_vector, mock_keyword
    ):
        """A keyword failure degrades the search instead of failing it.

        The likely cause is the migration not being applied to a given
        environment, which must not take search down entirely.
        """
        mock_vector.return_value = [
            _make_chunk("aaaaaaaa-0000-0000-0000-000000000001")
        ]
        mock_keyword.side_effect = Exception("function does not exist")

        from app.rag.retrieval.search import hybrid_search

        outcome = hybrid_search(query="q", user_id=USER_ID)

        assert outcome.keyword_degraded is True
        assert outcome.mode is SearchMode.vector
        assert len(outcome.results) == 1
        assert outcome.results[0].matched_by == ["vector"]

    @patch("app.rag.retrieval.search.keyword_search")
    @patch("app.rag.retrieval.search.similarity_search")
    def test_vector_failure_is_not_swallowed(self, mock_vector, mock_keyword):
        """A vector failure propagates so the API can report 503.

        Degrading is only reasonable for keyword search, which is the
        optional half. A missing API key or a dead database is not
        something to paper over.
        """
        mock_vector.side_effect = RuntimeError("GEMINI_API_KEY is not configured.")

        from app.rag.retrieval.search import hybrid_search

        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            hybrid_search(query="q", user_id=USER_ID)
        mock_keyword.assert_not_called()

    @patch("app.rag.retrieval.search.keyword_search")
    @patch("app.rag.retrieval.search.similarity_search")
    def test_keyword_results_survive_an_empty_vector_side(
        self, mock_vector, mock_keyword
    ):
        """An exact term that fails the cosine threshold still comes back.

        A high-threshold vector search that matches nothing must not mean
        "no results" when the keyword retriever found something.
        """
        mock_vector.return_value = []
        mock_keyword.return_value = [
            _make_chunk("bbbbbbbb-0000-0000-0000-000000000001", similarity=None)
        ]

        from app.rag.retrieval.search import hybrid_search

        outcome = hybrid_search(query="ImageNet", user_id=USER_ID, top_k=8)

        assert len(outcome.results) == 1
        assert outcome.results[0].matched_by == ["keyword"]

    @patch("app.rag.retrieval.search.keyword_search")
    @patch("app.rag.retrieval.search.similarity_search")
    def test_no_matches_from_either_retriever(self, mock_vector, mock_keyword):
        """No matches anywhere returns an empty set, still reporting hybrid."""
        mock_vector.return_value = []
        mock_keyword.return_value = []

        from app.rag.retrieval.search import hybrid_search

        outcome = hybrid_search(query="q", user_id=USER_ID)

        assert outcome.results == []
        assert outcome.mode is SearchMode.hybrid


# ---------------------------------------------------------------------------
# Part 14: endpoint mode dispatch
# ---------------------------------------------------------------------------


class TestSearchModeDispatch:
    @patch("app.api.search.hybrid_search")
    def test_default_mode_is_hybrid(self, mock_hybrid, client):
        """Omitting mode runs hybrid retrieval (FR-14's default)."""
        mock_hybrid.return_value = SearchOutcome(
            results=[
                SearchResultChunk(
                    chunk_id=UUID(CHUNK_ID),
                    paper_id=UUID(PAPER_ID),
                    paper_title="Test Paper",
                    page_number=2,
                    content="c",
                    similarity_score=0.7,
                    matched_by=["vector", "keyword"],
                    fusion_score=0.032,
                )
            ],
            mode=SearchMode.hybrid,
        )

        resp = client.post(
            "/api/search", json={"query": "ImageNet"}, headers=AUTH_HEADERS
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "hybrid"
        assert body["results"][0]["matched_by"] == ["vector", "keyword"]
        assert body["results"][0]["fusion_score"] == 0.032

    @patch("app.api.search.similarity_search")
    @patch("app.api.search.hybrid_search")
    def test_vector_mode_does_not_use_hybrid(
        self, mock_hybrid, mock_vector, client
    ):
        """mode=vector runs the vector retriever alone."""
        mock_vector.return_value = []

        resp = client.post(
            "/api/search",
            json={"query": "q", "mode": "vector"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert resp.json()["mode"] == "vector"
        mock_hybrid.assert_not_called()

    @patch("app.api.search.similarity_search")
    @patch("app.api.search.keyword_search")
    def test_keyword_mode_never_embeds(self, mock_keyword, mock_vector, client):
        """mode=keyword works with no embedding call at all."""
        mock_keyword.return_value = [
            SearchResultChunk(
                chunk_id=UUID(CHUNK_ID),
                paper_id=UUID(PAPER_ID),
                paper_title="Test Paper",
                page_number=4,
                content="c",
                matched_by=["keyword"],
            )
        ]

        resp = client.post(
            "/api/search",
            json={"query": "ImageNet", "mode": "keyword"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "keyword"
        assert body["results"][0]["similarity_score"] is None
        assert body["results"][0]["matched_by"] == ["keyword"]
        mock_vector.assert_not_called()

    @patch("app.api.search.similarity_search")
    @patch("app.api.search.keyword_search")
    def test_keyword_mode_works_without_api_key(
        self, mock_keyword, mock_vector, client
    ):
        """Keyword search still answers when Gemini is unconfigured."""
        mock_keyword.return_value = []

        resp = client.post(
            "/api/search",
            json={"query": "ImageNet", "mode": "keyword"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert resp.json()["total_results"] == 0

    @patch("app.api.search.hybrid_search")
    def test_degraded_hybrid_reports_vector_mode(self, mock_hybrid, client):
        """A degraded hybrid search says so in the response mode.

        Reporting 'hybrid' when only the vector retriever ran would let
        the UI imply keyword matching it never did.
        """
        mock_hybrid.return_value = SearchOutcome(
            results=[],
            mode=SearchMode.vector,
            keyword_degraded=True,
        )

        resp = client.post(
            "/api/search",
            json={"query": "q", "mode": "hybrid"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert resp.json()["mode"] == "vector"

    @patch("app.api.search.hybrid_search")
    def test_503_on_hybrid_runtime_error(self, mock_hybrid, client):
        """A missing API key on the default path still returns 503."""
        mock_hybrid.side_effect = RuntimeError("GEMINI_API_KEY is not configured.")

        resp = client.post(
            "/api/search", json={"query": "q"}, headers=AUTH_HEADERS
        )

        assert resp.status_code == 503

    @patch("app.api.search.hybrid_search")
    def test_500_on_hybrid_unexpected_error(self, mock_hybrid, client):
        """Unexpected hybrid failures do not leak internals."""
        mock_hybrid.side_effect = Exception("connection pool exhausted")

        resp = client.post(
            "/api/search", json={"query": "q"}, headers=AUTH_HEADERS
        )

        assert resp.status_code == 500
        assert "connection pool" not in resp.json()["error"]["message"]
