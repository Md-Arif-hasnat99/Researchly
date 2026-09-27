"""Performance regressions.

Each test here locks in a *behaviour* that a performance change must not
break, and that would otherwise be invisible: a route silently going back
to blocking the event loop, an embedding response that no longer lines up
with its input, a query embedded once per paper, or a failed re-ingestion
that takes the paper's existing chunks with it.

The tests assert call counts and ordering rather than wall-clock timings,
so they are not flaky on a loaded machine.
"""

import inspect
import json
import threading
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_application

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}
USER_ID = "00000000-0000-0000-0000-000000000000"  # dev-token user


@pytest.fixture()
def client():
    return TestClient(create_application())


# ---------------------------------------------------------------------------
# The event loop
# ---------------------------------------------------------------------------


class TestRoutesDoNotBlockTheEventLoop:
    """Handlers that do blocking I/O must not be coroutines.

    An ``async def`` handler that calls a blocking client (Supabase,
    Gemini) runs that work *on the event loop*, so the whole API stops
    serving requests until it returns. FastAPI runs a plain ``def``
    handler in a threadpool instead. Nothing about the request changes
    from the caller's side, so nothing else in the suite would notice the
    regression — hence this explicit check.
    """

    # (module path, attribute) for every route that performs blocking I/O.
    BLOCKING_ROUTES = [
        ("app.api.chat", "chat"),
        ("app.api.chat", "chat_stream"),
        ("app.api.chat", "list_conversations"),
        ("app.api.chat", "get_conversation"),
        ("app.api.chat", "delete_conversation"),
        ("app.api.search", "search_papers"),
        ("app.api.research", "compare_papers"),
        ("app.api.research", "generate_review"),
        ("app.api.research", "find_gaps"),
        ("app.api.papers", "list_papers"),
        ("app.api.papers", "get_paper"),
        ("app.api.papers", "delete_paper"),
        ("app.api.papers", "list_chunks"),
        ("app.api.papers", "trigger_ingestion"),
    ]

    @pytest.mark.parametrize("module_path,attr", BLOCKING_ROUTES)
    def test_route_is_not_a_coroutine_function(self, module_path, attr):
        import importlib

        handler = getattr(importlib.import_module(module_path), attr)
        assert not inspect.iscoroutinefunction(handler), (
            f"{module_path}.{attr} is `async def` but performs blocking I/O. "
            "It would run on the event loop and stall every other request. "
            "Make it a plain `def` so FastAPI threadpools it."
        )

    def test_upload_endpoint_stays_async(self):
        """The one exception: it awaits the upload body, so it must not
        become a sync handler (FastAPI cannot await inside a threadpool)."""
        from app.api import papers

        assert inspect.iscoroutinefunction(papers.upload_paper_endpoint)

    def test_health_endpoint_stays_async(self):
        """Readiness probes use an async HTTP client; they are not blocking."""
        from app.api import health

        assert inspect.iscoroutinefunction(health.get_readiness)


# ---------------------------------------------------------------------------
# Embedding batching
# ---------------------------------------------------------------------------


def _gemini_client_with_vectors(call_sizes: list[int]) -> MagicMock:
    """A Gemini client whose embed_content returns one vector per input."""
    client = MagicMock()

    def _embed(model, contents, config=None):
        call_sizes.append(len(contents))
        return MagicMock(
            embeddings=[MagicMock(values=[0.1] * 768) for _ in contents]
        )

    client.models.embed_content.side_effect = _embed
    return client


class TestEmbedBatching:
    def test_batches_respect_the_api_limit(self):
        """250 inputs must go out as 100 + 100 + 50, never one 250-item call."""
        from app.rag.embeddings import gemini

        call_sizes: list[int] = []
        with (
            patch.object(gemini, "get_settings") as mock_settings,
            patch.object(
                gemini, "_get_client", return_value=_gemini_client_with_vectors(call_sizes)
            ),
        ):
            mock_settings.return_value.GEMINI_API_KEY = "k"
            mock_settings.return_value.GEMINI_EMBEDDING_MODEL = "m"
            vectors = gemini.embed_texts([f"t{i}" for i in range(250)])

        assert call_sizes == [100, 100, 50]
        assert len(vectors) == 250

    def test_order_is_preserved_across_batches(self):
        """Batches run concurrently, so completion order is not input order.

        The slow batch is first and deliberately sleeps, so a naive
        "collect as they finish" implementation would return chunk 0's
        vector last — misaligning every chunk in the paper.
        """
        from app.rag.embeddings import gemini

        client = MagicMock()

        def _embed(model, contents, config=None):
            # The first batch is slow; later batches finish first.
            if contents[0] == "chunk-0":
                time.sleep(0.25)
            return MagicMock(
                embeddings=[
                    MagicMock(values=[float(contents[i].split("-")[1])] * 768)
                    for i in range(len(contents))
                ]
            )

        client.models.embed_content.side_effect = _embed

        texts = [f"chunk-{i}" for i in range(200)]
        with (
            patch.object(gemini, "get_settings") as mock_settings,
            patch.object(gemini, "_get_client", return_value=client),
        ):
            mock_settings.return_value.GEMINI_API_KEY = "k"
            mock_settings.return_value.GEMINI_EMBEDDING_MODEL = "m"
            vectors = gemini.embed_texts(texts)

        assert len(vectors) == 200
        assert [v[0] for v in vectors] == [float(i) for i in range(200)]

    def test_batches_are_embedded_concurrently(self):
        """Independent batches should overlap rather than run one after another.

        Asserted with a barrier, not a duration: each batch records that it
        started and then waits for the others. A serial implementation can
        never satisfy the barrier, and this fails by timing out rather than
        by being marginally slow on a busy machine.
        """
        from app.rag.embeddings import gemini

        batch_count = 3
        barrier = threading.Barrier(batch_count, timeout=2.0)
        client = MagicMock()

        def _embed(model, contents, config=None):
            barrier.wait()  # raises BrokenBarrierError if run serially
            return MagicMock(
                embeddings=[MagicMock(values=[0.1] * 768) for _ in contents]
            )

        client.models.embed_content.side_effect = _embed

        with (
            patch.object(gemini, "get_settings") as mock_settings,
            patch.object(gemini, "_get_client", return_value=client),
        ):
            mock_settings.return_value.GEMINI_API_KEY = "k"
            mock_settings.return_value.GEMINI_EMBEDDING_MODEL = "m"
            vectors = gemini.embed_texts([f"t{i}" for i in range(250)])

        assert len(vectors) == 250

    def test_short_response_is_rejected(self):
        """A short batch must fail loudly, not silently misalign.

        Callers zip chunks with vectors positionally, so a truncated
        response would attach each chunk to another chunk's vector — and
        quietly drop the remainder of the paper.
        """
        from app.rag.embeddings import gemini

        client = MagicMock()
        client.models.embed_content.return_value = MagicMock(
            embeddings=[MagicMock(values=[0.1] * 768)]  # 1 vector for 2 inputs
        )

        with (
            patch.object(gemini, "get_settings") as mock_settings,
            patch.object(gemini, "_get_client", return_value=client),
        ):
            mock_settings.return_value.GEMINI_API_KEY = "k"
            mock_settings.return_value.GEMINI_EMBEDDING_MODEL = "m"
            with pytest.raises(ValueError, match="misalign"):
                gemini.embed_texts(["a", "b"])

    def test_empty_input_short_circuits(self):
        from app.rag.embeddings import gemini

        with patch.object(gemini, "get_settings") as mock_settings:
            mock_settings.return_value.GEMINI_API_KEY = "k"
            assert gemini.embed_texts([]) == []

    def test_width_is_pinned_to_the_vector_column(self):
        """The embed call must ask for 768 dimensions explicitly.

        paper_chunks.embedding is a vector(768) column. The embedding
        model supports several output widths, so relying on its default
        means a model upgrade can change the width and turn every
        ingestion into a Postgres insert failure at the very end.
        """
        from app.rag.embeddings import gemini

        seen: list[dict] = []
        client = MagicMock()

        def _embed(model, contents, config=None):
            seen.append(
                {
                    "task_type": getattr(config, "task_type", None),
                    "output_dimensionality": getattr(config, "output_dimensionality", None),
                }
            )
            return MagicMock(
                embeddings=[MagicMock(values=[0.1] * 768) for _ in contents]
            )

        client.models.embed_content.side_effect = _embed

        with (
            patch.object(gemini, "get_settings") as mock_settings,
            patch.object(gemini, "_get_client", return_value=client),
        ):
            mock_settings.return_value.GEMINI_API_KEY = "k"
            mock_settings.return_value.GEMINI_EMBEDDING_MODEL = "m"
            gemini.embed_texts(["a"])
            gemini.embed_query("a")

        assert seen[0]["output_dimensionality"] == gemini.EMBEDDING_DIM
        assert seen[0]["task_type"] == "RETRIEVAL_DOCUMENT"
        # The query side must match the document side, or a query vector
        # is not comparable with the vectors stored against chunks.
        assert seen[1]["output_dimensionality"] == gemini.EMBEDDING_DIM
        assert seen[1]["task_type"] == "RETRIEVAL_QUERY"


class TestReadinessChecksConfiguredModels:
    """A retired model must show up as a failed readiness probe.

    The probe used to GET /v1beta/models, which answers 200 for any
    valid key. That stayed green — reporting a healthy deployment — while
    every generation and embedding call 404'd. It has to ask for the
    configured model by name, which is the thing that must exist.
    """

    def test_probe_asks_for_each_configured_model(self):
        import asyncio

        from app.api import health

        requested: list[str] = []
        states = iter(["reachable", "reachable"])

        async def fake_probe(url, headers=None):
            requested.append(url)
            return next(states)

        with (
            patch.object(health, "_probe", fake_probe),
            patch.object(health, "get_settings") as mock_settings,
        ):
            mock_settings.return_value.GEMINI_API_KEY = "k"
            mock_settings.return_value.GEMINI_GENERATION_MODEL = "models/gen-model"
            mock_settings.return_value.GEMINI_EMBEDDING_MODEL = "models/emb-model"
            state = asyncio.run(health.check_gemini())

        assert state == "reachable"
        assert len(requested) == 2
        assert requested[0].endswith("/models/gen-model")
        assert requested[1].endswith("/models/emb-model")
        # The bare listing endpoint must not be what is checked.
        assert not any(url.endswith("/models") for url in requested)

    def test_unavailable_model_is_reported_with_its_name(self):
        import asyncio

        from app.api import health

        async def fake_probe(url, headers=None):
            return "unhealthy (404)"

        with (
            patch.object(health, "_probe", fake_probe),
            patch.object(health, "get_settings") as mock_settings,
        ):
            mock_settings.return_value.GEMINI_API_KEY = "k"
            mock_settings.return_value.GEMINI_GENERATION_MODEL = "models/retired"
            mock_settings.return_value.GEMINI_EMBEDDING_MODEL = "models/emb"
            state = asyncio.run(health.check_gemini())

        assert "404" in state
        assert "retired" in state


# ---------------------------------------------------------------------------
# One query embedding per request, not per paper
# ---------------------------------------------------------------------------


class TestResearchEmbedsQueryOnce:
    def test_six_papers_cost_one_embedding(self, client):
        """The retrieval query is identical for every paper, so it is
        embedded once and the vector reused. Previously each paper's
        search re-embedded it: a six-paper comparison paid for six
        identical paid Gemini round-trips.
        """
        from app.rag.generation.compare import ComparisonResult
        from app.schemas.research import ComparePaperRef
        from app.schemas.search import SearchResultChunk

        paper_ids = [str(uuid4()) for _ in range(6)]
        rows = [
            {
                "id": pid,
                "user_id": USER_ID,
                "title": f"Paper {i}",
                "publication_year": 2020,
                "status": "ready",
            }
            for i, pid in enumerate(paper_ids)
        ]

        def _chunk(paper_id, idx):
            return SearchResultChunk(
                chunk_id=str(uuid4()),
                paper_id=paper_id,
                paper_title="P",
                page_number=idx,
                section=None,
                content=f"chunk {idx}",
                similarity_score=0.5,
                matched_by=["vector"],
            )

        db = MagicMock()
        (
            db.table.return_value.select.return_value.in_.return_value.eq.return_value.execute.return_value.data
        ) = rows

        with (
            patch("app.api.research.get_supabase_client", return_value=db),
            patch("app.api.research.embed_query", return_value=[0.0] * 768) as mock_embed,
            patch("app.api.research.similarity_search") as mock_search,
            patch("app.api.research.generate_comparison") as mock_gen,
        ):
            mock_search.side_effect = [
                [_chunk(pid, i)] for i, pid in enumerate(paper_ids)
            ]
            mock_gen.return_value = ComparisonResult(
                papers=[
                    ComparePaperRef(
                        paper_id=pid, paper_title=f"Paper {i}", publication_year=2020
                    )
                    for i, pid in enumerate(paper_ids)
                ],
                rows=[],
                summary="ok",
            )

            resp = client.post(
                "/api/research/compare",
                json={"paper_ids": paper_ids},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200, resp.text
        assert mock_search.call_count == 6, "each paper should still be searched"
        assert mock_embed.call_count == 1, (
            f"query embedded {mock_embed.call_count} times for 6 papers; "
            "it must be embedded once and reused"
        )
        # And the same vector must be what reached every search.
        for call in mock_search.call_args_list:
            assert call.kwargs["query_vector"] == [0.0] * 768


# ---------------------------------------------------------------------------
# Ingestion must not destroy prior results on failure
# ---------------------------------------------------------------------------


class TestIngestionFailureSafety:
    def test_embedding_failure_leaves_existing_chunks_alone(self):
        """Re-ingestion used to delete the old chunks *before* embedding.

        A failure in the (expensive, failure-prone) embedding step then
        left the paper with no chunks at all — a retry made it worse
        instead of better. The pipeline swallows the error and marks the
        paper failed, so the assertion is on the data, not the raise.
        """
        from app.rag.ingestion import pipeline

        paper_id = str(uuid4())
        chunk = MagicMock(
            paper_id=paper_id,
            content="text",
            page_number=1,
            section=None,
            chunk_index=0,
        )

        db = MagicMock()
        table = db.table.return_value
        with (
            patch.object(pipeline, "extract_pages", return_value=[b"page one"]),
            patch.object(pipeline, "chunk_pages", return_value=[chunk]),
            patch.object(pipeline, "get_supabase_client", return_value=db),
            patch.object(pipeline, "embed_texts", side_effect=RuntimeError("quota")),
        ):
            stored = pipeline.run_ingestion(paper_id, b"%PDF-1.4")

        assert stored == 0
        assert not table.delete.called, (
            "existing chunks were deleted before embeddings succeeded"
        )
        assert not table.insert.called
        # and the paper is marked failed, not silently left processing
        statuses = [
            call.args[0].get("status") for call in table.update.call_args_list
        ]
        assert statuses[-1] == "failed"

    def test_embedding_count_mismatch_fails_before_writing(self):
        from app.rag.ingestion import pipeline

        paper_id = str(uuid4())
        chunks = [
            MagicMock(
                paper_id=paper_id,
                content=f"c{i}",
                page_number=1,
                section=None,
                chunk_index=i,
            )
            for i in range(3)
        ]

        db = MagicMock()
        with (
            patch.object(pipeline, "extract_pages", return_value=[b"page"]),
            patch.object(pipeline, "chunk_pages", return_value=chunks),
            patch.object(pipeline, "get_supabase_client", return_value=db),
            # 2 vectors for 3 chunks
            patch.object(pipeline, "embed_texts", return_value=[[0.1] * 768] * 2),
        ):
            stored = pipeline.run_ingestion(paper_id, b"%PDF-1.4")

        assert stored == 0
        assert not db.table.return_value.delete.called
        assert not db.table.return_value.insert.called


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs."""
    events = []
    for frame in text.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        name, data = None, None
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name is not None and data is not None:
            events.append((name, data))
    return events


def _retrieved_chunk(paper_id: str, index: int):
    from app.schemas.search import SearchResultChunk

    return SearchResultChunk(
        chunk_id=str(uuid4()),
        paper_id=paper_id,
        paper_title="Alpha",
        page_number=index,
        section=None,
        content=f"chunk {index}",
        similarity_score=0.5,
        matched_by=["vector"],
    )


class TestChatStreaming:
    def _stub_context(self, mock_retrieve, chunks):
        from app.rag.pipeline import RetrievedContext

        mock_retrieve.return_value = RetrievedContext(
            chunks=chunks, retrieved_count=len(chunks), reranked=False
        )

    def test_streams_tokens_then_done(self, client):
        paper_id = str(uuid4())
        conv_id = str(uuid4())
        msg_id = str(uuid4())

        with (
            patch("app.api.chat._get_or_create_conversation", return_value=conv_id),
            patch("app.api.chat._persist_message", return_value=msg_id),
            patch("app.api.chat._persist_citations"),
            patch("app.api.chat.retrieve_context") as mock_retrieve,
            patch("app.api.chat.stream_answer", return_value=iter(["Hel", "lo ", "[1]"])),
        ):
            self._stub_context(mock_retrieve, [_retrieved_chunk(paper_id, 1)])

            resp = client.post(
                "/api/chat/stream", json={"query": "what?"}, headers=AUTH_HEADERS
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        # Proxies must not buffer, or the tokens arrive all at once.
        assert resp.headers["x-accel-buffering"] == "no"

        events = _parse_sse(resp.text)
        names = [name for name, _ in events]
        assert names == ["citations", "token", "token", "token", "done"]

        answer = "".join(d["text"] for n, d in events if n == "token")
        assert answer == "Hello [1]"

        done = dict(events)["done"]
        assert done["message_id"] == msg_id
        assert done["reranked"] is False

    def test_citations_arrive_before_any_text(self, client):
        """Sources are known from retrieval, so the client can show them
        while the answer is still being written."""
        paper_id = str(uuid4())

        with (
            patch("app.api.chat._get_or_create_conversation", return_value=str(uuid4())),
            patch("app.api.chat._persist_message", return_value=str(uuid4())),
            patch("app.api.chat._persist_citations"),
            patch("app.api.chat.retrieve_context") as mock_retrieve,
            patch("app.api.chat.stream_answer", return_value=iter(["x"])),
        ):
            self._stub_context(mock_retrieve, [_retrieved_chunk(paper_id, 1)])

            resp = client.post(
                "/api/chat/stream", json={"query": "q"}, headers=AUTH_HEADERS
            )

        events = _parse_sse(resp.text)
        assert events[0][0] == "citations"
        first_citation = events[0][1]["citations"][0]
        assert first_citation["paper_id"] == paper_id
        assert first_citation["content"] == "chunk 1"

    def test_generation_failure_reports_in_band(self, client):
        """Once the status line is sent, a failure cannot change it, so it
        must be reported in the body — and the client must not be left
        believing the answer is complete."""
        with (
            patch("app.api.chat._get_or_create_conversation", return_value=str(uuid4())),
            patch("app.api.chat._persist_message", return_value=str(uuid4())),
            patch("app.api.chat._persist_citations"),
            patch("app.api.chat.retrieve_context") as mock_retrieve,
            patch(
                "app.api.chat.stream_answer",
                side_effect=RuntimeError("GEMINI_API_KEY is not configured"),
            ),
        ):
            self._stub_context(mock_retrieve, [_retrieved_chunk(str(uuid4()), 1)])

            resp = client.post(
                "/api/chat/stream", json={"query": "q"}, headers=AUTH_HEADERS
            )

        # Still 200: the headers were already flushed. The error is in-band.
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        assert events[-1][0] == "error"
        # The internal reason must not leak into the body.
        assert "GEMINI_API_KEY" not in resp.text
        assert events[-1][1]["code"] == "GENERATION_FAILED"
        assert not any(name == "done" for name, _ in events)

    def test_retrieval_failure_keeps_its_http_status(self, client):
        """Anything that fails before the first byte must still be a real
        HTTP error, not a 200 stream containing an error event."""
        with (
            patch("app.api.chat._get_or_create_conversation", return_value=str(uuid4())),
            patch("app.api.chat._persist_message"),
            patch("app.api.chat.retrieve_context", side_effect=RuntimeError("no key")),
        ):
            resp = client.post(
                "/api/chat/stream", json={"query": "q"}, headers=AUTH_HEADERS
            )

        assert resp.status_code == 503
        assert "GEMINI" not in resp.text and "no key" not in resp.text

    def test_persist_failure_is_surfaced(self, client):
        """The user has the text, but it will not be in their history;
        saying so beats a silent inconsistency."""
        with (
            patch("app.api.chat._get_or_create_conversation", return_value=str(uuid4())),
            patch(
                "app.api.chat._persist_message",
                side_effect=[str(uuid4()), RuntimeError("db down")],
            ),
            patch("app.api.chat._persist_citations"),
            patch("app.api.chat.retrieve_context") as mock_retrieve,
            patch("app.api.chat.stream_answer", return_value=iter(["a", "b"])),
        ):
            self._stub_context(mock_retrieve, [_retrieved_chunk(str(uuid4()), 1)])

            resp = client.post(
                "/api/chat/stream", json={"query": "q"}, headers=AUTH_HEADERS
            )

        events = _parse_sse(resp.text)
        assert events[-1][0] == "error"
        assert events[-1][1]["code"] == "PERSIST_FAILED"

    def test_no_context_yields_the_fallback_answer(self, client):
        """With no retrieved chunks, the generator returns a complete
        answer without calling Gemini at all."""
        with (
            patch("app.api.chat._get_or_create_conversation", return_value=str(uuid4())),
            patch("app.api.chat._persist_message", return_value=str(uuid4())),
            patch("app.api.chat._persist_citations"),
            patch("app.api.chat.retrieve_context") as mock_retrieve,
        ):
            self._stub_context(mock_retrieve, [])

            resp = client.post(
                "/api/chat/stream", json={"query": "q"}, headers=AUTH_HEADERS
            )

        events = _parse_sse(resp.text)
        assert [n for n, _ in events] == ["citations", "token", "done"]
        assert "could not find information" in events[1][1]["text"]
