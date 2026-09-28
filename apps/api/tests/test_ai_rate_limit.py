"""Tests for the AI rate-limit error mapping helper (pure unit tests)."""

import pytest

from app.core.errors import ai_rate_limit_retry_after


class TestAiRateLimit:
    """Tests for the AI service rate-limit error mapping."""

    def test_extracts_retry_after_from_429_message(self):
        class Fake429(Exception):
            code = 429
            def __str__(self):
                return "429 You exceeded your current quota. Please retry in 34.3s."

        exc = Fake429()
        assert ai_rate_limit_retry_after(exc) == 36  # ceil(34.3) + 1

    def test_fallback_60s_when_no_retry_in_message(self):
        class Fake429(Exception):
            code = 429
            def __str__(self):
                return "429 RESOURCE_EXHAUSTED quota exceeded."

        exc = Fake429()
        assert ai_rate_limit_retry_after(exc) == 60

    def test_server_error_503_gets_60s(self):
        class Fake503(Exception):
            code = 503
            def __str__(self):
                return "503 SERVICE_UNAVAILABLE model overloaded."

        exc = Fake503()
        assert ai_rate_limit_retry_after(exc) == 60

    def test_other_codes_return_none(self):
        class Fake400(Exception):
            code = 400
        assert ai_rate_limit_retry_after(Fake400()) is None
        assert ai_rate_limit_retry_after(Exception("random")) is None