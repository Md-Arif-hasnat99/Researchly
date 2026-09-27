"""Tests for the security controls (Part 18).

Covers five groups, each of which corresponds to a real gap or defect
found in the audit:

- rate limiting (there was none, and four endpoints spend money)
- the dev-token auth bypass (was reachable in production)
- production configuration guards (a wildcard CORS origin with
  credentials, or an unset service-role key, used to boot silently)
- upload validation (content was trusted on the client's word alone)
- error-message sanitization (internal config text reached the client)

Plus the two database defects the migrations fix, asserted against the
SQL so they cannot silently regress.
"""

import io
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.errors import safe_error_message
from app.core.rate_limit import (
    _PRUNE_EVERY,
    EXPENSIVE_PREFIXES,
    RateLimitMiddleware,
    SlidingWindowLimiter,
)
from app.main import create_application

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}

MIGRATIONS = Path(__file__).parents[3] / "supabase" / "migrations"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_application())


def _app_with_tiny_limit(limit: int = 3, window: int = 60) -> TestClient:
    """Build an app whose limiter allows *limit* requests, then one more.

    The probe path is a throwaway non-exempt route: the real /api/health
    is deliberately never rate limited, so it cannot be used to observe
    the limiter.
    """
    app = create_application()
    clock = SimpleNamespace(now=[1000.0])
    limiter = SlidingWindowLimiter(limit, window, time_func=lambda: clock.now[0])
    app.add_middleware(
        RateLimitMiddleware,
        general=limiter,
        expensive=SlidingWindowLimiter(limit, window, time_func=lambda: clock.now[0]),
    )
    app.add_api_route("/api/__ping__", lambda: {"ok": True}, methods=["GET"])
    return TestClient(app)


PING = "/api/__ping__"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestSlidingWindowLimiter:
    def test_allows_up_to_the_limit_then_refuses(self):
        now = [0.0]
        limiter = SlidingWindowLimiter(3, 60, time_func=lambda: now[0])

        for _ in range(3):
            assert limiter.check("ip").allowed is True

        decision = limiter.check("ip")
        assert decision.allowed is False
        assert decision.remaining == 0
        assert decision.retry_after > 0

    def test_window_slides_so_old_requests_stop_counting(self):
        now = [0.0]
        limiter = SlidingWindowLimiter(2, 60, time_func=lambda: now[0])
        assert limiter.check("ip").allowed
        assert limiter.check("ip").allowed
        assert limiter.check("ip").allowed is False

        # 61s later the first two have aged out; the caller is fresh.
        now[0] = 61.0
        assert limiter.check("ip").allowed is True

    def test_keys_are_independent(self):
        now = [0.0]
        limiter = SlidingWindowLimiter(1, 60, time_func=lambda: now[0])
        assert limiter.check("a").allowed
        assert limiter.check("b").allowed  # a different client has its own budget
        assert limiter.check("a").allowed is False

    def test_idle_keys_are_pruned_so_memory_does_not_grow(self):
        now = [0.0]
        limiter = SlidingWindowLimiter(5, 60, time_func=lambda: now[0])
        for i in range(200):
            limiter.check(f"ip-{i}")
        # Advance past the window and keep checking, so the periodic
        # sweep runs and finds every key idle.
        now[0] = 61.0
        for i in range(_PRUNE_EVERY + 1):
            limiter.check(f"live-{i}")
        assert len(limiter._hits) <= _PRUNE_EVERY + 1


class TestRateLimitMiddleware:
    def test_429_after_the_budget_is_spent(self):
        client = _app_with_tiny_limit(limit=2)

        assert client.get(PING, headers=AUTH_HEADERS).status_code == 200
        assert client.get(PING, headers=AUTH_HEADERS).status_code == 200
        blocked = client.get(PING, headers=AUTH_HEADERS)

        assert blocked.status_code == 429
        body = blocked.json()
        assert body["error"]["code"] == "TOO_MANY_REQUESTS"
        assert "wait" in body["error"]["message"].lower()

    def test_429_carries_backoff_headers(self):
        client = _app_with_tiny_limit(limit=1)
        client.get(PING, headers=AUTH_HEADERS)
        blocked = client.get(PING, headers=AUTH_HEADERS)

        assert int(blocked.headers["Retry-After"]) > 0
        assert blocked.headers["X-RateLimit-Limit"] == "1"
        assert blocked.headers["X-RateLimit-Remaining"] == "0"

    def test_allowed_request_advertises_remaining_budget(self):
        client = _app_with_tiny_limit(limit=5)
        resp = client.get(PING, headers=AUTH_HEADERS)
        assert resp.headers["X-RateLimit-Remaining"] == "4"

    def test_health_probes_are_never_rate_limited(self):
        client = _app_with_tiny_limit(limit=1)
        for _ in range(5):
            # A liveness probe that gets 429 would take the instance out
            # of rotation, turning a rate limit into an outage.
            assert client.get("/api/health").status_code == 200

    def test_preflight_is_never_rate_limited(self):
        client = _app_with_tiny_limit(limit=1)
        for _ in range(5):
            resp = client.options(
                PING,
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.status_code < 500

    def test_expensive_endpoints_have_their_own_budget(self):
        assert "/api/chat" in EXPENSIVE_PREFIXES
        assert "/api/research" in EXPENSIVE_PREFIXES
        assert "/api/papers" in EXPENSIVE_PREFIXES
        assert "/api/search" in EXPENSIVE_PREFIXES

    def test_can_be_disabled(self, monkeypatch):
        fake = SimpleNamespace(
            RATE_LIMIT_ENABLED=False,
            RATE_LIMIT_REQUESTS=1,
            RATE_LIMIT_WINDOW_SECONDS=60,
            RATE_LIMIT_AI_REQUESTS=1,
            RATE_LIMIT_AI_WINDOW_SECONDS=60,
            TRUST_PROXY_HEADERS=False,
        )
        monkeypatch.setattr("app.core.rate_limit.get_settings", lambda: fake)
        app = create_application()
        app.add_api_route(PING, lambda: {"ok": True}, methods=["GET"])
        client = TestClient(app)
        for _ in range(5):
            assert client.get(PING, headers=AUTH_HEADERS).status_code == 200


# ---------------------------------------------------------------------------
# Dev-token auth bypass
# ---------------------------------------------------------------------------


class TestDevTokenBypass:
    @pytest.mark.asyncio
    async def test_refused_in_production(self):
        """A production deployment must never accept the dev identity."""
        from fastapi import HTTPException

        from app.core.security import get_current_user

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(
                SUPABASE_ANON_KEY="", IS_PRODUCTION=True
            )
            with pytest.raises(HTTPException):
                await get_current_user(authorization="Bearer dev-token")

    @pytest.mark.asyncio
    async def test_allowed_outside_production(self):
        from app.core.security import get_current_user

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(
                SUPABASE_ANON_KEY="", IS_PRODUCTION=False
            )
            user = await get_current_user(authorization="Bearer dev-token")
        assert user.email == "dev@researchly.local"


# ---------------------------------------------------------------------------
# Production configuration guards
# ---------------------------------------------------------------------------


class TestProductionGuards:
    def _settings(self, **overrides):
        from app.core.config import Settings

        base = {
            "ENVIRONMENT": "production",
            "GEMINI_API_KEY": "real-key",
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_ANON_KEY": "real-anon",
            "SUPABASE_SERVICE_ROLE_KEY": "real-service",
            "CORS_ORIGINS": ["https://app.researchly.dev"],
            "TRUST_PROXY_HEADERS": True,
        }
        base.update(overrides)
        return Settings(**base)

    def test_a_correct_production_config_boots(self):
        assert self._settings().IS_PRODUCTION is True

    def test_wildcard_cors_origin_is_refused(self):
        with pytest.raises(ValueError, match="CORS_ORIGINS"):
            self._settings(CORS_ORIGINS=["*"])

    def test_plaintext_http_origin_is_refused(self):
        with pytest.raises(ValueError, match="https"):
            self._settings(CORS_ORIGINS=["http://app.researchly.dev"])

    def test_localhost_origin_is_refused_in_production(self):
        with pytest.raises(ValueError, match="https"):
            self._settings(CORS_ORIGINS=["http://localhost:5173"])

    @pytest.mark.parametrize(
        "field",
        [
            "GEMINI_API_KEY",
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        ],
    )
    def test_unset_credential_is_refused(self, field):
        with pytest.raises(ValueError, match=field):
            self._settings(**{field: ""})

    def test_placeholder_credential_is_refused(self):
        with pytest.raises(ValueError, match="SUPABASE_SERVICE_ROLE_KEY"):
            self._settings(SUPABASE_SERVICE_ROLE_KEY="your_supabase_service_role_key_here")

    def test_unknown_environment_is_refused(self):
        from app.core.config import Settings

        with pytest.raises(ValueError, match="ENVIRONMENT"):
            Settings(ENVIRONMENT="prod")

    def test_development_is_unaffected(self):
        from app.core.config import Settings

        # Development keeps its permissive defaults so local work and the
        # test suite are not blocked by a production guard.
        settings = Settings(ENVIRONMENT="development")
        assert settings.IS_PRODUCTION is False


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


class TestUploadValidation:
    def test_title_sanitizer_strips_directories_and_controls(self):
        from app.api.papers import sanitize_title_from_filename

        # A path is reduced to its last segment, never kept whole.
        assert sanitize_title_from_filename("../../etc/passwd.pdf") == "passwd"
        assert sanitize_title_from_filename("C:\\Users\\me\\thesis.pdf") == "thesis"
        assert sanitize_title_from_filename("my paper\x00.pdf") == "my paper"
        assert sanitize_title_from_filename("....pdf") == "Untitled Paper"
        assert sanitize_title_from_filename("") == "Untitled Paper"
        assert sanitize_title_from_filename(None) == "Untitled Paper"
        assert len(sanitize_title_from_filename("x" * 400 + ".pdf")) <= 255

    def test_content_must_really_be_a_pdf(self, client):

        resp = client.post(
            "/api/papers",
            files={"file": ("evil.pdf", io.BytesIO(b"PK\x03\x04not a pdf"), "application/pdf")},
            headers=AUTH_HEADERS,
        )
        # A spoofed Content-Type no longer buys a free pass into storage.
        # 422 specifically (not 413): the size check is not what fired.
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_a_real_pdf_passes_the_content_check(self):
        """The magic-byte check must not reject genuine uploads."""
        from fastapi import HTTPException

        from app.api.papers import _assert_is_pdf_bytes

        _assert_is_pdf_bytes(b"%PDF-1.4 real bytes")  # must not raise
        with pytest.raises(HTTPException):
            _assert_is_pdf_bytes(b"PK\x03\x04")
        with pytest.raises(HTTPException):
            _assert_is_pdf_bytes(b"")


# ---------------------------------------------------------------------------
# Error-message sanitization
# ---------------------------------------------------------------------------


class TestErrorSanitization:
    def test_storage_paths_are_redacted(self):
        msg = safe_error_message(
            "Failed to open /home/user/app/storage/papers/abc123.pdf"
        )
        assert "/home/user" not in msg
        assert "<path>" in msg

    def test_tokens_are_redacted(self):
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefghijklmnop"
        assert token not in safe_error_message(f"auth failed with {token}")

    def test_only_the_first_line_survives(self):
        msg = safe_error_message("Problem here\nTraceback (most recent call last): ...")
        assert "Traceback" not in msg

    def test_empty_exception_uses_the_fallback(self):
        assert safe_error_message("", fallback="Could not read the file.") == (
            "Could not read the file."
        )

    def test_upstream_config_error_is_not_shown_to_the_user(self, client):
        with patch("app.api.search.similarity_search") as mock_search:
            mock_search.side_effect = RuntimeError("GEMINI_API_KEY is not configured.")
            resp = client.post(
                "/api/search", json={"query": "test"}, headers=AUTH_HEADERS
            )
        assert resp.status_code == 503
        assert "GEMINI_API_KEY" not in resp.text
        assert "not configured" not in resp.text


# ---------------------------------------------------------------------------
# Storage bucket alignment (the dead-policy defect)
# ---------------------------------------------------------------------------


class TestStorageBucketAlignment:
    def test_migration_guards_the_bucket_the_code_writes_to(self):
        from app.core.storage import BUCKET

        sql = (MIGRATIONS / "20260927000003_security_fixes.sql").read_text()
        # The policies must name the same bucket the application uses, or
        # they guard nothing while looking correct. Only the executable
        # statements count; the migration's own header explains the old
        # name in prose.
        policies = re.findall(
            r"create policy .*?;", sql, flags=re.DOTALL
        )
        assert policies, "expected storage policies in the migration"
        for policy in policies:
            assert f"bucket_id = '{BUCKET}'" in policy
            assert "research-papers" not in policy

    def test_storage_policies_are_idempotent(self):
        sql = (MIGRATIONS / "20260927000003_security_fixes.sql").read_text()
        assert "drop policy if exists" in sql

    def test_stray_keyword_function_overload_is_dropped(self):
        sql = (MIGRATIONS / "20260927000003_security_fixes.sql").read_text()
        # The broken overload (text, uuid, uuid[], integer) must be
        # removed, or PostgREST keeps resolving calls to it.
        assert re.search(
            r"drop function if exists public\.search_paper_chunks_by_keyword"
            r"\(text, uuid, uuid\[\], integer\)",
            sql,
        )

    def test_keyword_function_keeps_the_signature_the_api_calls(self):
        sql = (MIGRATIONS / "20260927000003_security_fixes.sql").read_text()
        # filter_user_id/filter_paper_ids are the names the API sends.
        assert "filter_user_id" in sql
        assert "tsquery_english tsquery" in sql
        assert "p.status = 'ready'" in sql


# ---------------------------------------------------------------------------
# Middleware ordering
# ---------------------------------------------------------------------------


class TestMiddlewareOrdering:
    def test_request_id_present_on_rate_limited_response(self, client):
        resp = client.get("/api/health", headers={**AUTH_HEADERS, "X-Request-ID": "abc123"})
        assert resp.headers["X-Request-ID"] == "abc123"
