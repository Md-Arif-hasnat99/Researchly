"""Reliability tests: retries, error envelope, request logging, health.

Part 17 covers errors, retries, logging and observability. The tests
inject failures rather than mocking the retry machinery, so what is
verified is the behaviour callers depend on: how many times a call was
attempted, what surfaced to the user, and what landed in the logs.
"""

import logging
import re
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.retry import is_transient, with_retry
from app.main import create_application

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Transient(Exception):
    """Stand-in for a rate limit or gateway error: ``code`` says retry."""

    def __init__(self, code: int = 503):
        super().__init__(f"HTTP {code}")
        self.code = code


def _client_with_route(handler, path: str = "/api/__boom__", **kwargs) -> TestClient:
    app = create_application()
    app.add_api_route(path, handler, methods=["GET"], **kwargs)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_application())


# ---------------------------------------------------------------------------
# Retry: classification
# ---------------------------------------------------------------------------


class TestTransientClassification:
    @pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
    def test_gateway_and_rate_limit_statuses_retry(self, code):
        assert is_transient(_Transient(code)) is True

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 422])
    def test_client_statuses_fail_immediately(self, code):
        # Retrying these costs quota and delays the real error while
        # reaching the identical conclusion.
        assert is_transient(_Transient(code)) is False

    def test_transport_failures_retry(self):
        class ConnectError(Exception):
            pass

        assert is_transient(ConnectError("refused")) is True
        assert is_transient(TimeoutError()) is True
        assert is_transient(ConnectionError()) is True

    def test_ordinary_errors_are_not_transient(self):
        assert is_transient(ValueError("bad payload")) is False
        assert is_transient(TypeError()) is False


# ---------------------------------------------------------------------------
# Retry: behaviour
# ---------------------------------------------------------------------------


class TestWithRetry:
    def test_recovers_after_transient_failures(self):
        sleeps: list[float] = []
        attempts: list[int] = []

        def flaky() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise _Transient(429)
            return "ok"

        assert with_retry(flaky, sleep=sleeps.append, label="test") == "ok"
        assert len(attempts) == 3
        # Exponential: base delay, then doubled.
        assert sleeps == [1.0, 2.0]

    def test_raises_last_failure_once_exhausted(self):
        attempts: list[int] = []

        def always_fails():
            attempts.append(1)
            raise _Transient(503)

        with pytest.raises(_Transient):
            with_retry(always_fails, retries=2, sleep=lambda _: None, label="test")
        assert len(attempts) == 3  # retries + 1

    def test_non_transient_failure_is_not_retried(self):
        attempts: list[int] = []
        sleeps: list[float] = []

        def rejected():
            attempts.append(1)
            raise ValueError("invalid argument")

        with pytest.raises(ValueError):
            with_retry(rejected, sleep=sleeps.append, label="test")
        assert len(attempts) == 1
        assert sleeps == []

    def test_fewer_retries_bounds_the_wait(self):
        """An interactive path may cap its own attempts."""
        attempts: list[int] = []

        def flaky():
            attempts.append(1)
            raise _Transient(503)

        with pytest.raises(_Transient):
            with_retry(flaky, retries=1, sleep=lambda _: None, label="test")
        assert len(attempts) == 2

    def test_retry_is_logged_with_its_label(self, caplog):
        caplog.set_level(logging.WARNING, logger="researchly")

        with pytest.raises(_Transient):
            with_retry(
                lambda: (_ for _ in ()).throw(_Transient(429)),
                retries=1,
                sleep=lambda _: None,
                label="chat answer",
            )
        lines = [rec.getMessage() for rec in caplog.records if "chat answer" in rec.getMessage()]
        assert lines, "each retry attempt must be logged"
        assert "attempt 1/2" in lines[0]


# ---------------------------------------------------------------------------
# Retries are wired into the Gemini call sites
# ---------------------------------------------------------------------------


class TestCallSitesRetry:
    def test_generate_answer_retries_a_transient_failure(self, monkeypatch):
        from app.rag.generation import gemini as gemini_module

        attempts: list[int] = []
        sleeps: list[float] = []

        class _Models:
            def generate_content(self, **kwargs):
                attempts.append(1)
                if len(attempts) == 1:
                    raise _Transient(503)
                return SimpleNamespace(text="The factor is 0.5 [1].")

        class _Client:
            def __init__(self, api_key=None):
                self.models = _Models()

        monkeypatch.setattr(gemini_module, "genai", SimpleNamespace(Client=_Client))
        monkeypatch.setattr(gemini_module, "get_settings", lambda: SimpleNamespace(
            GEMINI_API_KEY="test-key",
            GEMINI_GENERATION_MODEL="test-model",
        ))
        monkeypatch.setattr(time, "sleep", sleeps.append)

        from app.schemas.search import SearchResultChunk

        chunk = SearchResultChunk(
            chunk_id=str(uuid4()),
            paper_id=str(uuid4()),
            paper_title="Densité",
            page_number=3,
            section="Eq 1",
            content="theta = 0.5",
            similarity_score=0.9,
            matched_by=["vector"],
        )
        result = gemini_module.generate_answer("what is theta?", [chunk])

        assert result.answer == "The factor is 0.5 [1]."
        assert len(attempts) == 2
        assert sleeps == [1.0]

    def test_generate_answer_does_not_retry_quota_errors(self, monkeypatch):
        """A 429 carries the provider's own backoff, so retrying it only
        burns more quota and delays the honest answer."""
        from app.rag.generation import gemini as gemini_module

        attempts: list[int] = []
        sleeps: list[float] = []

        class _QuotaExceeded(Exception):
            code = 429

            def __str__(self) -> str:
                return (
                    "429 RESOURCE_EXHAUSTED. Quota exceeded for metric "
                    "generate_content_free_tier_requests. Please retry in 47s."
                )

        class _Models:
            def generate_content(self, **kwargs):
                attempts.append(1)
                raise _QuotaExceeded()

        class _Client:
            def __init__(self, api_key=None):
                self.models = _Models()

        monkeypatch.setattr(gemini_module, "genai", SimpleNamespace(Client=_Client))
        monkeypatch.setattr(gemini_module, "get_settings", lambda: SimpleNamespace(
            GEMINI_API_KEY="test-key",
            GEMINI_GENERATION_MODEL="test-model",
        ))
        monkeypatch.setattr(time, "sleep", sleeps.append)

        from app.schemas.search import SearchResultChunk

        chunk = SearchResultChunk(
            chunk_id=str(uuid4()),
            paper_id=str(uuid4()),
            paper_title="Test Paper",
            page_number=1,
            section=None,
            content="some content",
            similarity_score=0.9,
            matched_by=["vector"],
        )
        with pytest.raises(_QuotaExceeded):
            gemini_module.generate_answer("what is this?", [chunk])

        assert len(attempts) == 1
        assert sleeps == []

    def test_stream_answer_does_not_retry_quota_errors(self, monkeypatch):
        """Same rule for the streaming path: fail fast on quota errors."""
        from app.rag.generation import gemini as gemini_module

        attempts: list[int] = []
        sleeps: list[float] = []

        class _QuotaExceeded(Exception):
            code = 429

            def __str__(self) -> str:
                return "429 RESOURCE_EXHAUSTED. Please retry in 47s."

        class _Models:
            def generate_content_stream(self, **kwargs):
                attempts.append(1)
                raise _QuotaExceeded()

        class _Client:
            def __init__(self, api_key=None):
                self.models = _Models()

        monkeypatch.setattr(gemini_module, "genai", SimpleNamespace(Client=_Client))
        monkeypatch.setattr(gemini_module, "get_settings", lambda: SimpleNamespace(
            GEMINI_API_KEY="test-key",
            GEMINI_GENERATION_MODEL="test-model",
        ))
        monkeypatch.setattr(time, "sleep", sleeps.append)

        from app.schemas.search import SearchResultChunk

        chunk = SearchResultChunk(
            chunk_id=str(uuid4()),
            paper_id=str(uuid4()),
            paper_title="Test Paper",
            page_number=1,
            section=None,
            content="some content",
            similarity_score=0.9,
            matched_by=["vector"],
        )
        with pytest.raises(_QuotaExceeded):
            list(gemini_module.stream_answer("what is this?", [chunk]))

        assert len(attempts) == 1
        assert sleeps == []

    def test_rerank_falls_back_when_the_call_keeps_failing(self, monkeypatch):
        """A failed reranker must not fail the search — retries first, then order."""
        from app.rag.retrieval import rerank as rerank_module

        attempts: list[int] = []

        class _Models:
            def generate_content(self, **kwargs):
                attempts.append(1)
                raise _Transient(503)

        class _Client:
            def __init__(self, api_key=None):
                self.models = _Models()

        monkeypatch.setattr(rerank_module, "genai", SimpleNamespace(Client=_Client))
        monkeypatch.setattr(rerank_module, "get_settings", lambda: SimpleNamespace(
            GEMINI_API_KEY="test-key",
            GEMINI_GENERATION_MODEL="test-model",
        ))
        monkeypatch.setattr(time, "sleep", lambda _: None)

        from app.schemas.search import SearchResultChunk

        def _candidate():
            return SearchResultChunk(
                chunk_id=str(uuid4()),
                paper_id=str(uuid4()),
                paper_title="Paper",
                page_number=1,
                section=None,
                content="content",
                similarity_score=0.9,
                matched_by=["vector"],
            )

        # Two: a single candidate is never sent to the model, because
        # there is no order for a reranker to improve.
        candidates = [_candidate(), _candidate()]

        result = rerank_module.rerank_chunks(query="q", candidates=candidates, top_k=1)

        assert result.reranked is False
        assert result.chunks == candidates
        # retries=1: the interactive search path gets a short leash.
        assert len(attempts) == 2


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    def test_unknown_route_uses_the_shared_shape(self, client):
        resp = client.get("/api/no-such-route")

        assert resp.status_code == 404
        body = resp.json()
        assert "detail" not in body
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["message"]

    def test_validation_errors_read_as_a_sentence(self, client):
        resp = client.post("/api/chat", json={}, headers=AUTH_HEADERS)

        assert resp.status_code == 422
        body = resp.json()
        assert "detail" not in body
        assert body["error"]["code"] == "VALIDATION_ERROR"
        message = body["error"]["message"]
        assert message.startswith("Request validation failed:")
        assert "query" in message

    def test_route_level_errors_keep_their_code_and_message(self, client):
        resp = client.post("/api/chat", json={}, headers=AUTH_HEADERS)
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_unhandled_exception_returns_the_shape_with_a_traceback(self, caplog):
        def boom():
            raise ValueError("kaboom internals")

        app_client = _client_with_route(boom)
        caplog.set_level(logging.ERROR, logger="researchly")

        resp = app_client.get("/api/__boom__", headers={"X-Request-ID": "deadbeef01"})

        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
        # Internal exception text stays out of the response.
        assert "kaboom" not in resp.text

        unhandled = [
            rec for rec in caplog.records
            if "Unhandled error processing" in rec.getMessage()
        ]
        assert unhandled, "the unhandled error must be logged"
        record = unhandled[0]
        assert record.exc_info is not None, "the traceback must be captured"
        assert "ValueError" in (record.exc_info[0].__name__ if record.exc_info[0] else "")
        # The id survives even though the middleware that minted it has
        # already unwound by the time this handler runs.
        assert "request_id=deadbeef01" in record.getMessage()
        assert "kaboom" in record.getMessage()


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------


class TestRequestLogging:
    def test_echoes_the_request_id_header(self, client):
        resp = client.get("/api/health", headers={"X-Request-ID": "my-trace-1"})
        assert resp.headers["X-Request-ID"] == "my-trace-1"

    def test_unsafe_caller_ids_are_replaced(self, client):
        resp = client.get(
            "/api/health", headers={"X-Request-ID": "bad id {script}"}
        )
        supplied = resp.headers["X-Request-ID"]
        assert supplied != "bad id {script}"
        assert re.fullmatch(r"[0-9a-f]{16}", supplied), supplied

    def test_overlong_caller_ids_are_replaced(self, client):
        resp = client.get("/api/health", headers={"X-Request-ID": "x" * 200})
        assert re.fullmatch(r"[0-9a-f]{16}", resp.headers["X-Request-ID"])

    def test_request_line_carrying_the_id(self, client, caplog):
        caplog.set_level(logging.INFO, logger="researchly")

        # A non-health path: health probes log below INFO on purpose.
        client.get("/api/no-such-route", headers={"X-Request-ID": "trace42"})

        lines = [rec for rec in caplog.records if "request |" in rec.getMessage()]
        assert lines, "a request must produce one summary line"
        line = lines[-1]
        message = line.getMessage()
        assert "GET /api/no-such-route status=404" in message
        assert "duration_ms=" in message
        assert line.request_id == "trace42", "the filter must attach the id"

    def test_query_strings_are_never_logged(self, client, caplog):
        caplog.set_level(logging.DEBUG, logger="researchly")

        client.get("/api/health", params={"secret": "value"})

        assert not [
            rec for rec in caplog.records if "value" in rec.getMessage()
        ], "query strings must not reach the logs"

    def test_health_probes_log_at_debug(self, client, caplog):
        caplog.set_level(logging.DEBUG, logger="researchly")

        client.get("/api/health")

        probe_lines = [
            rec for rec in caplog.records if "/api/health" in rec.getMessage()
            and "request |" in rec.getMessage()
        ]
        assert probe_lines
        assert all(rec.levelno == logging.DEBUG for rec in probe_lines)

    def test_server_errors_log_at_error(self, caplog):
        def boom():
            raise RuntimeError("again")

        app_client = _client_with_route(boom)
        caplog.set_level(logging.INFO, logger="researchly")

        app_client.get("/api/__boom__")

        failing = [
            rec for rec in caplog.records
            if "request | GET /api/__boom__" in rec.getMessage()
            and rec.levelno == logging.ERROR
        ]
        assert failing, "a 5xx request line must be an ERROR"

    def test_client_errors_are_not_treated_as_server_faults(self, client, caplog):
        caplog.set_level(logging.INFO, logger="researchly")

        client.get("/api/no-such-route")

        error_lines = [
            rec for rec in caplog.records
            if "request |" in rec.getMessage() and rec.levelno >= logging.ERROR
        ]
        assert error_lines == []


# ---------------------------------------------------------------------------
# Health: liveness vs readiness
# ---------------------------------------------------------------------------


class TestReadiness:
    @staticmethod
    def _stub_checks(monkeypatch, supabase: str, gemini: str):
        async def fake_supabase():
            return supabase

        async def fake_gemini():
            return gemini

        monkeypatch.setattr("app.api.health.check_supabase", fake_supabase)
        monkeypatch.setattr("app.api.health.check_gemini", fake_gemini)

    def test_ready_when_dependencies_are_reachable(self, client, monkeypatch):
        self._stub_checks(monkeypatch, "reachable", "reachable")

        resp = client.get("/api/health/ready")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_unreachable_supabase_degrades_readiness(self, client, monkeypatch):
        self._stub_checks(monkeypatch, "unreachable", "reachable")

        resp = client.get("/api/health/ready")

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        # The body says which dependency, because a bare 503 explains
        # nothing to whoever is debugging.
        assert body["dependencies"]["supabase"] == "unreachable"

    def test_gemini_unconfigured_is_still_ready(self, client, monkeypatch):
        """Retrieval and fallback answers work without generation."""
        self._stub_checks(monkeypatch, "reachable", "unconfigured")

        resp = client.get("/api/health/ready")

        assert resp.status_code == 200
        assert resp.json()["dependencies"]["gemini"] == "unconfigured"

    def test_configured_but_broken_gemini_degrades(self, client, monkeypatch):
        """Configured implies the deployment expects generation to work."""
        self._stub_checks(monkeypatch, "reachable", "unhealthy (403)")

        resp = client.get("/api/health/ready")

        assert resp.status_code == 503
        assert resp.json()["dependencies"]["gemini"] == "unhealthy (403)"

    def test_liveness_still_touches_no_network(self, client):
        resp = client.get("/api/health")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestProbe:
    """The probe itself, with the HTTP client faked."""

    @staticmethod
    def _fake_httpx(monkeypatch, status_code: int | None, error: Exception | None = None):
        import app.api.health as health_module

        class _Response:
            def __init__(self, code):
                self.status_code = code

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, headers=None):
                if error is not None:
                    raise error
                return _Response(status_code)

        monkeypatch.setattr(health_module.httpx, "AsyncClient", _Client)
        return health_module

    def test_success_is_reachable(self, monkeypatch):
        health = self._fake_httpx(monkeypatch, status_code=200)
        import asyncio

        assert asyncio.run(health._probe("https://example.test")) == "reachable"

    def test_bad_credentials_are_not_confused_with_unreachable(self, monkeypatch):
        health = self._fake_httpx(monkeypatch, status_code=401)
        import asyncio

        state = asyncio.run(health._probe("https://example.test"))
        assert state == "unhealthy (401)"

    def test_server_error_reads_as_unreachable(self, monkeypatch):
        health = self._fake_httpx(monkeypatch, status_code=503)
        import asyncio

        assert asyncio.run(health._probe("https://example.test")) == "unreachable"

    def test_transport_failure_reads_as_unreachable(self, monkeypatch):
        health = self._fake_httpx(
            monkeypatch,
            status_code=None,
            error=httpx.ConnectError(
                "refused", request=httpx.Request("GET", "https://example.test")
            ),
        )
        import asyncio

        assert asyncio.run(health._probe("https://example.test")) == "unreachable"

    def test_supabase_probe_reads_data_not_the_schema_endpoint(self, monkeypatch):
        """The root /rest/v1/ endpoint 401s for keys that query fine.

        Probing it would report a healthy deployment as broken, so this
        pins the probe to a real data read.
        """
        import asyncio
        from types import SimpleNamespace as NS

        import app.api.health as health_module

        seen: dict = {}

        class _Response:
            status_code = 200

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, headers=None):
                seen["url"] = url
                seen["headers"] = headers or {}
                return _Response()

        monkeypatch.setattr(health_module.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(
            health_module,
            "get_settings",
            lambda: NS(
                SUPABASE_URL="https://project.supabase.co/",
                SUPABASE_ANON_KEY="anon-key",
            ),
        )

        assert asyncio.run(health_module.check_supabase()) == "reachable"
        assert "supabase.co/rest/v1/papers" in seen["url"]
        assert seen["url"].endswith("limit=1"), seen["url"]
        assert seen["headers"]["apikey"] == "anon-key"


# ---------------------------------------------------------------------------
# Request id plumbing
# ---------------------------------------------------------------------------


class TestRequestId:
    def test_safe_ids_are_accepted_verbatim(self):
        from app.core.request_context import resolve_request_id

        assert resolve_request_id("trace-1.2:abc") == "trace-1.2:abc"

    @pytest.mark.parametrize("candidate", [None, "", "has space", "x" * 65, "üñî"])
    def test_unsafe_ids_are_replaced(self, candidate):
        from app.core.request_context import resolve_request_id

        resolved = resolve_request_id(candidate)
        assert resolved != candidate
        assert re.fullmatch(r"[0-9a-f]{16}", resolved)

    def test_outside_a_request_the_id_is_a_dash(self):
        from app.core.request_context import get_request_id

        assert get_request_id() == "-"


# ---------------------------------------------------------------------------
# Integration: a failing request leaves a traceable trail
# ---------------------------------------------------------------------------


class TestFailureTrail:
    def test_one_id_links_response_log_line_and_traceback(self, caplog):
        """The user-facing ref, the summary line, and the stack trace agree."""

        def boom():
            raise RuntimeError("database went away")

        app_client = _client_with_route(boom)
        caplog.set_level(logging.INFO, logger="researchly")

        resp = app_client.get("/api/__boom__", headers={"X-Request-ID": "feedface01"})

        assert resp.headers["X-Request-ID"] == "feedface01"

        summary = next(
            rec for rec in caplog.records
            if "request | GET /api/__boom__" in rec.getMessage()
        )
        assert summary.levelno == logging.ERROR

        unhandled = next(
            rec for rec in caplog.records
            if "Unhandled error processing" in rec.getMessage()
        )
        assert "feedface01" in unhandled.getMessage()
        assert unhandled.exc_info is not None
