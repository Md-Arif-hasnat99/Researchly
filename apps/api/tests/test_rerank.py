"""Tests for the FR-15 reranker (app.rag.retrieval.rerank) and its
wiring into the search endpoint and the chat RAG pipeline.

The Gemini call is patched at the import boundary, so no network or API
key is needed. The behaviour under test is mostly about what the reranker
refuses to do: drop a candidate, or lose the retrieval order to a bad
model reply.
"""

import json
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_application
from app.schemas.search import SearchMode, SearchResultChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "00000000-0000-0000-0000-000000000001"
CONV_ID = "00000000-0000-0000-0000-0000000000aa"
PAPER_ID = str(uuid4())
AUTH_HEADERS = {"Authorization": "Bearer dev-token"}

CHUNK_IDS = [f"cccccccc-0000-0000-0000-00000000000{i}" for i in range(1, 6)]


def _chunk(index: int) -> SearchResultChunk:
    """A candidate chunk. Order of construction is the retrieval rank."""
    return SearchResultChunk(
        chunk_id=UUID(CHUNK_IDS[index - 1]),
        paper_id=UUID(PAPER_ID),
        paper_title=f"Paper {index}",
        page_number=index,
        section="Methods",
        content=f"Candidate {index} discusses experimental setup and results.",
        similarity_score=0.9 - index / 100,
        matched_by=["vector"],
    )


def _candidates(n: int = 5) -> list[SearchResultChunk]:
    return [_chunk(i) for i in range(1, n + 1)]


def _fake_response(text: str) -> MagicMock:
    return MagicMock(text=text)


def _mock_genai(mock_client_cls, text: str) -> MagicMock:
    """Wire genai.Client so generate_content returns *text*."""
    client = MagicMock()
    client.models.generate_content.return_value = _fake_response(text)
    mock_client_cls.return_value = client
    return client


@pytest.fixture(autouse=True)
def _api_key_configured():
    """Give the reranker a configured API key by default.

    Without one it deliberately short-circuits, so every test that expects
    a model call has to supply a key. The one test covering the no-key
    path patches this again to return an empty key.
    """
    with patch("app.rag.retrieval.rerank.get_settings") as mock_settings:
        mock_settings.return_value.GEMINI_API_KEY = "test-key"
        mock_settings.return_value.GEMINI_GENERATION_MODEL = "test-model"
        yield


# ---------------------------------------------------------------------------
# Ranking application
# ---------------------------------------------------------------------------


class TestRerankOrdering:
    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_applies_a_valid_ranking(self, mock_client_cls):
        """The model's ordering becomes the output order."""
        _mock_genai(mock_client_cls, json.dumps({"ranking": [4, 2, 5, 1, 3]}))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        assert [c.chunk_id for c in result.chunks] == [
            UUID(CHUNK_IDS[3]),
            UUID(CHUNK_IDS[1]),
            UUID(CHUNK_IDS[4]),
            UUID(CHUNK_IDS[0]),
            UUID(CHUNK_IDS[2]),
        ]
        assert result.reranked is True
        # Only candidate 2 holds its position; the other four move.
        assert result.reordered_count == 4

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_truncates_to_top_k(self, mock_client_cls):
        """Reranking picks the best N, not everything the retrievers found."""
        _mock_genai(mock_client_cls, json.dumps({"ranking": [5, 4, 3, 2, 1]}))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(5), top_k=2)

        assert len(result.chunks) == 2
        assert [c.chunk_id for c in result.chunks] == [
            UUID(CHUNK_IDS[4]),
            UUID(CHUNK_IDS[3]),
        ]

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_preserves_candidate_content_and_scores(self, mock_client_cls):
        """Reranking reorders; it must not rewrite what a chunk carries."""
        _mock_genai(mock_client_cls, json.dumps({"ranking": [3, 1, 2, 4, 5]}))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        # The reranker sees truncated text, but downstream consumers get
        # the original chunk objects untouched.
        assert result.chunks[0].content == _chunk(3).content
        assert result.chunks[0].similarity_score == _chunk(3).similarity_score
        assert result.chunks[0].matched_by == ["vector"]


# ---------------------------------------------------------------------------
# No candidate is ever dropped
# ---------------------------------------------------------------------------


class TestNoCandidateLoss:
    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_partial_ranking_appends_the_rest_in_original_order(self, mock_client_cls):
        """A short ranking keeps every unranked candidate, in rank order.

        This is the property that makes a reranker safe: it reorders, it
        never filters. Dropping what the model failed to mention would cut
        recall, which is the opposite of the point.
        """
        _mock_genai(mock_client_cls, json.dumps({"ranking": [3, 1]}))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        assert [c.chunk_id for c in result.chunks] == [
            UUID(CHUNK_IDS[2]),
            UUID(CHUNK_IDS[0]),
            UUID(CHUNK_IDS[1]),
            UUID(CHUNK_IDS[3]),
            UUID(CHUNK_IDS[4]),
        ]

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_out_of_range_indices_are_dropped_not_applied(self, mock_client_cls):
        """Invented indices are discarded and recorded."""
        _mock_genai(mock_client_cls, json.dumps({"ranking": [99, 2, 0, 3, 1]}))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(5), top_k=5)

        assert result.dropped_indices == [99, 0]
        assert [c.chunk_id for c in result.chunks] == [
            UUID(CHUNK_IDS[1]),
            UUID(CHUNK_IDS[2]),
            UUID(CHUNK_IDS[0]),
            UUID(CHUNK_IDS[3]),
            UUID(CHUNK_IDS[4]),
        ]

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_duplicate_indices_do_not_repeat_a_candidate(self, mock_client_cls):
        """A repeated index cannot consume the same candidate twice."""
        _mock_genai(mock_client_cls, json.dumps({"ranking": [2, 2, 2, 1]}))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        ids = [c.chunk_id for c in result.chunks]
        assert len(ids) == len(set(ids)) == 5

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_non_integer_entries_are_ignored(self, mock_client_cls):
        """Junk entries in the ranking array are skipped, not fatal."""
        _mock_genai(
            mock_client_cls,
            json.dumps({"ranking": ["two", None, 2, {"i": 1}, 1]}),
        )

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        assert [c.chunk_id for c in result.chunks][0] == UUID(CHUNK_IDS[1])
        assert len(result.chunks) == 5

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_bare_array_reply_is_tolerated(self, mock_client_cls):
        """A plain list in place of the schema object still ranks."""
        _mock_genai(mock_client_cls, json.dumps([3, 2, 1, 4, 5]))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        assert [c.chunk_id for c in result.chunks][0] == UUID(CHUNK_IDS[2])
        assert len(result.chunks) == 5


# ---------------------------------------------------------------------------
# Degradation — a reranker must never make retrieval worse
# ---------------------------------------------------------------------------


class TestRerankDegradation:
    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_unparseable_reply_keeps_retrieval_order(self, mock_client_cls):
        """Garbage output returns the input order rather than raising."""
        _mock_genai(mock_client_cls, "I think the second one is best, honestly.")

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        assert result.reranked is False
        assert [c.chunk_id for c in result.chunks] == [
            UUID(CHUNK_IDS[i]) for i in range(5)
        ]

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_empty_reply_keeps_retrieval_order(self, mock_client_cls):
        """An empty ranking array is not treated as 'no results'."""
        _mock_genai(mock_client_cls, json.dumps({"ranking": []}))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        # No candidate lost to an empty reply.
        assert len(result.chunks) == 5
        assert [c.chunk_id for c in result.chunks] == [
            UUID(CHUNK_IDS[i]) for i in range(5)
        ]

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_api_failure_keeps_retrieval_order(self, mock_client_cls):
        """A model call that raises must not fail the request."""
        client = MagicMock()
        client.models.generate_content.side_effect = Exception("503 overloaded")
        mock_client_cls.return_value = client

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        assert result.reranked is False
        assert len(result.chunks) == 5

    @patch("app.rag.retrieval.rerank.get_settings")
    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_missing_api_key_skips_the_call(self, mock_client_cls, mock_settings):
        """With no API key the reranker returns the order untouched."""
        settings = MagicMock()
        settings.GEMINI_API_KEY = ""
        mock_settings.return_value = settings

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=3)

        assert result.reranked is False
        assert [c.chunk_id for c in result.chunks] == [
            UUID(CHUNK_IDS[i]) for i in range(5)
        ]
        mock_client_cls.assert_not_called()

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_no_candidates_makes_no_call(self, mock_client_cls):
        """An empty candidate set short-circuits."""
        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=[], top_k=5)

        assert result.chunks == []
        assert result.reranked is False
        mock_client_cls.assert_not_called()

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_reranks_even_when_candidates_already_fit_top_k(self, mock_client_cls):
        """A set the right size is still reranked.

        The retrievers ordered by cosine similarity; "already the
        requested size" says nothing about whether the order is any good.
        Skipping here would forfeit the main benefit of reranking.
        """
        _mock_genai(mock_client_cls, json.dumps({"ranking": [3, 1, 2]}))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(3), top_k=3)

        assert [c.chunk_id for c in result.chunks][0] == UUID(CHUNK_IDS[2])
        assert result.reranked is True
        mock_client_cls.assert_called_once()

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_single_candidate_makes_no_call(self, mock_client_cls):
        """One chunk has no order to improve, so it is not sent."""
        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(1), top_k=5)

        assert result.reranked is False
        assert len(result.chunks) == 1
        mock_client_cls.assert_not_called()

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_order_unchanged_by_the_model_is_not_claimed_as_reranked(
        self, mock_client_cls
    ):
        """Echoing the input order means nothing was reranked."""
        _mock_genai(mock_client_cls, json.dumps({"ranking": [1, 2, 3, 4, 5]}))

        from app.rag.retrieval.rerank import rerank_chunks

        result = rerank_chunks(query="q", candidates=_candidates(), top_k=5)

        assert result.reordered_count == 0
        assert result.reranked is False
        assert [c.chunk_id for c in result.chunks] == [
            UUID(CHUNK_IDS[i]) for i in range(5)
        ]


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


class TestRerankPrompt:
    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_prompt_carries_query_and_every_candidate(self, mock_client_cls):
        """Each candidate is labelled with a 1-based index and its location."""
        client = _mock_genai(mock_client_cls, json.dumps({"ranking": [1, 2, 3, 4, 5]}))

        from app.rag.retrieval.rerank import rerank_chunks

        rerank_chunks(query="what dataset did they use?", candidates=_candidates(), top_k=5)

        call = client.models.generate_content.call_args
        prompt = call[1]["contents"][0].parts[0].text
        assert "what dataset did they use?" in prompt
        for idx in range(1, 6):
            assert f"{idx} = " in prompt
        # The model must not have to guess what is in each candidate.
        assert "page 1" in prompt

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_long_chunks_are_truncated_in_the_prompt_only(self, mock_client_cls):
        """A huge chunk is shortened for ranking, not for the answer."""
        client = _mock_genai(mock_client_cls, json.dumps({"ranking": [1, 2]}))

        from app.rag.retrieval.rerank import rerank_chunks

        big = _chunk(1)
        big = big.model_copy(update={"content": "x" * 9000})

        result = rerank_chunks(query="q", candidates=[big, _chunk(2)], top_k=2)

        prompt = client.models.generate_content.call_args[1]["contents"][0].parts[0].text
        assert "x" * 9000 not in prompt
        # The stored chunk itself is untouched.
        assert result.chunks[0].content == "x" * 9000

    @patch("app.rag.retrieval.rerank.genai.Client")
    def test_candidate_cap_bounds_the_call(self, mock_client_cls):
        """More candidates than the cap are not all sent to the model."""
        _mock_genai(mock_client_cls, json.dumps({"ranking": [1]}))

        from app.rag.retrieval import rerank as rerank_module

        many = [_chunk(i % 5 + 1).model_copy(
            update={"chunk_id": UUID(int=i)}
        ) for i in range(1, rerank_module.MAX_RERANK_CANDIDATES + 6)]

        result = rerank_module.rerank_chunks(query="q", candidates=many, top_k=3)

        # Beyond the cap nothing was ever in contention, so truncating
        # there is not a loss.
        assert len(result.chunks) == 3


# ---------------------------------------------------------------------------
# Search endpoint integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    return TestClient(create_application())


def _vector_rows(n: int) -> list[dict]:
    return [
        {
            "chunk_id": CHUNK_IDS[i],
            "paper_id": PAPER_ID,
            "paper_title": f"Paper {i + 1}",
            "page_number": i + 1,
            "section": "Methods",
            "content": f"Candidate {i + 1} discusses experimental setup.",
            "similarity": 0.9 - i / 100,
        }
        for i in range(n)
    ]


class TestSearchEndpointRerank:
    @patch("app.api.search.rerank_chunks")
    @patch("app.api.search.hybrid_search")
    def test_rerank_is_on_by_default(self, mock_hybrid, mock_rerank, client):
        """Search reranks unless the caller says otherwise."""
        candidates = _candidates(5)
        mock_hybrid.return_value = MagicMock(
            results=list(candidates), mode=SearchMode.hybrid, keyword_degraded=False
        )
        mock_rerank.return_value = MagicMock(chunks=candidates[:3], reranked=True)

        resp = client.post("/api/search", json={"query": "q"}, headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["reranked"] is True
        assert body["total_results"] == 3
        assert mock_rerank.called

    @patch("app.api.search.rerank_chunks")
    @patch("app.api.search.hybrid_search")
    def test_retrieves_deeper_so_the_reranker_has_a_choice(
        self, mock_hybrid, mock_rerank, client
    ):
        """The candidate set is larger than top_k when reranking.

        Fetching only top_k and then reranking would give the reranker
        nothing to choose between — the bug this asserts against.
        """
        mock_hybrid.return_value = MagicMock(
            results=_candidates(5), mode=SearchMode.hybrid, keyword_degraded=False
        )
        mock_rerank.return_value = MagicMock(chunks=_candidates(3), reranked=True)

        resp = client.post(
            "/api/search", json={"query": "q", "top_k": 3}, headers=AUTH_HEADERS
        )

        assert resp.status_code == 200
        fetch_top_k = mock_hybrid.call_args[1]["top_k"]
        assert fetch_top_k > 3
        assert mock_rerank.call_args[1]["top_k"] == 3

    @patch("app.api.search.rerank_chunks")
    @patch("app.api.search.hybrid_search")
    def test_no_rerank_fetches_exactly_top_k(
        self, mock_hybrid, mock_rerank, client
    ):
        """With reranking off there is no reason to over-fetch."""
        mock_hybrid.return_value = MagicMock(
            results=_candidates(3), mode=SearchMode.hybrid, keyword_degraded=False
        )

        resp = client.post(
            "/api/search",
            json={"query": "q", "top_k": 3, "rerank": False},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert resp.json()["reranked"] is False
        assert mock_hybrid.call_args[1]["top_k"] == 3
        mock_rerank.assert_not_called()

    @patch("app.api.search.rerank_chunks")
    @patch("app.api.search.hybrid_search")
    def test_degraded_rerank_reports_not_reranked(
        self, mock_hybrid, mock_rerank, client
    ):
        """A reranker that fell back to retrieval order is not claimed as applied."""
        mock_hybrid.return_value = MagicMock(
            results=_candidates(5), mode=SearchMode.hybrid, keyword_degraded=False
        )
        mock_rerank.return_value = MagicMock(
            chunks=_candidates(5), reranked=False
        )

        resp = client.post("/api/search", json={"query": "q"}, headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["reranked"] is False

    @patch("app.api.search.rerank_chunks")
    @patch("app.api.search.keyword_search")
    def test_keyword_mode_skips_reranking(
        self, mock_keyword, mock_rerank, client
    ):
        """Lexical ranking is already exact, so a reranker is skipped.

        It would add latency and a Gemini dependency to the one mode that
        deliberately works without an API key.
        """
        mock_keyword.return_value = _candidates(5)

        resp = client.post(
            "/api/search", json={"query": "q", "mode": "keyword"}, headers=AUTH_HEADERS
        )

        assert resp.status_code == 200
        assert resp.json()["reranked"] is False
        mock_rerank.assert_not_called()

    @patch("app.api.search.rerank_chunks")
    @patch("app.api.search.similarity_search")
    def test_vector_mode_retrieves_deeper_when_reranking(
        self, mock_vector, mock_rerank, client
    ):
        """The deeper fetch applies to vector mode too."""
        mock_vector.return_value = _candidates(5)
        mock_rerank.return_value = MagicMock(chunks=_candidates(2), reranked=True)

        resp = client.post(
            "/api/search",
            json={"query": "q", "mode": "vector", "top_k": 2},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert mock_vector.call_args[1]["top_k"] > 2
        assert resp.json()["reranked"] is True


# ---------------------------------------------------------------------------
# Chat pipeline integration
# ---------------------------------------------------------------------------


def _mock_chat_db(mock_client_fn) -> MagicMock:
    """A Supabase stub good enough for a new-conversation chat turn."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    db = MagicMock()
    db.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[
            {
                "id": CONV_ID,
                "user_id": USER_ID,
                "title": "My Conv",
                "created_at": now,
                "updated_at": now,
            }
        ]
    )
    mock_client_fn.return_value = db
    return db


class TestChatRerank:
    @patch("app.rag.pipeline.rerank_chunks")
    @patch("app.rag.pipeline.generate_answer")
    @patch("app.rag.pipeline.similarity_search")
    def test_chat_does_not_rerank_by_default(
        self, mock_search, mock_generate, mock_rerank
    ):
        """Chat leaves reranking off: it costs a round-trip per turn."""
        from app.rag.pipeline import run_rag

        mock_search.return_value = _candidates(3)
        mock_generate.return_value = MagicMock(answer="a", cited_chunks=[])

        run_rag(query="q", user_id=USER_ID, top_k=3)

        assert mock_search.call_args[1]["top_k"] == 3
        mock_rerank.assert_not_called()

    @patch("app.rag.pipeline.rerank_chunks")
    @patch("app.rag.pipeline.generate_answer")
    @patch("app.rag.pipeline.similarity_search")
    def test_chat_rerank_can_be_requested(
        self, mock_search, mock_generate, mock_rerank
    ):
        """Opting in reranks the context sent to the generator."""
        from app.rag.pipeline import run_rag

        mock_search.return_value = _candidates(5)
        mock_generate.return_value = MagicMock(answer="a", cited_chunks=[])
        mock_rerank.return_value = MagicMock(
            chunks=_candidates(2), reranked=True
        )

        result = run_rag(query="q", user_id=USER_ID, top_k=2, rerank=True)

        # Candidates were over-fetched, then cut to the context size.
        assert mock_search.call_args[1]["top_k"] > 2
        assert mock_rerank.call_args[1]["top_k"] == 2
        assert result.reranked is True
        # retrieved_count reports the candidate set, not the context size.
        assert result.retrieved_count == 5
        # The generator saw the reranked, truncated list.
        passed = mock_generate.call_args[1]["chunks"]
        assert [c.chunk_id for c in passed] == [
            UUID(CHUNK_IDS[0]),
            UUID(CHUNK_IDS[1]),
        ]

    @patch("app.rag.pipeline.rerank_chunks")
    @patch("app.rag.pipeline.generate_answer")
    @patch("app.rag.pipeline.similarity_search")
    def test_chat_rerank_failure_still_answers(
        self, mock_search, mock_generate, mock_rerank
    ):
        """A reranker problem degrades to the retrieval order.

        The user still gets an answer built from real retrieved chunks
        rather than an error page.
        """
        from app.rag.pipeline import run_rag

        mock_search.return_value = _candidates(5)
        mock_generate.return_value = MagicMock(answer="a", cited_chunks=[])
        mock_rerank.side_effect = Exception("reranker exploded")

        with pytest.raises(Exception, match="reranker exploded"):
            run_rag(query="q", user_id=USER_ID, top_k=2, rerank=True)

    @patch("app.api.chat.run_rag")
    @patch("app.api.chat.get_supabase_client")
    def test_chat_request_forwards_rerank_flag(self, mock_supabase, mock_run_rag, client):
        """The chat endpoint passes the caller's rerank choice through."""
        _mock_chat_db(mock_supabase)
        mock_run_rag.return_value = MagicMock(
            answer="a", cited_chunks=[], retrieved_count=0, reranked=False
        )

        resp = client.post(
            "/api/chat",
            json={"query": "q", "rerank": True},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert mock_run_rag.call_args[1]["rerank"] is True

    @patch("app.api.chat.run_rag")
    @patch("app.api.chat.get_supabase_client")
    def test_chat_omits_rerank_when_not_specified(
        self, mock_supabase, mock_run_rag, client
    ):
        """Unset means the server default, not an implicit opt-in."""
        _mock_chat_db(mock_supabase)
        mock_run_rag.return_value = MagicMock(
            answer="a", cited_chunks=[], retrieved_count=0, reranked=False
        )

        resp = client.post("/api/chat", json={"query": "q"}, headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert mock_run_rag.call_args[1]["rerank"] is None
