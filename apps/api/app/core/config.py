from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Environments the app is allowed to run as. A typo in ENVIRONMENT must
#: fail loudly: silently falling back to "development" would enable the
#: dev-token auth bypass and the relaxed CORS defaults in production.
ENVIRONMENTS = ("development", "test", "staging", "production")

#: Substrings that mark a credential as a copy-paste placeholder. The
#: example env file ships exactly these, so a deployment that copies it
#: and forgets to fill it in would otherwise look configured.
_PLACEHOLDER_MARKERS = ("your_", "changeme", "placeholder", "todo", "replace_me")


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    PROJECT_NAME: str = "Researchly API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api"
    ENVIRONMENT: str = "development"

    # CORS configuration
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # External services (Supabase & Gemini)
    GEMINI_API_KEY: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Embedding and generation defaults.
    #
    # Both defaults were previously `text-embedding-004` and
    # `gemini-1.5-pro`, which Google has since retired: the API answers
    # 404 NOT_FOUND for them, so every generation *and* every ingestion
    # failed at the last step. Verified against the live API with the
    # project's own key, which is what settled the values below.
    #
    # Note that availability is per-project, not global: this key is also
    # refused the 2.5 and 2.0 families ("no longer available to new
    # users"), so a model that works elsewhere may not work here. The
    # readiness probe checks both configured models by name for exactly
    # this reason — a retired or unavailable model now fails /api/health
    # /ready instead of surfacing as a 404 on the first user request.
    #
    # The embedding model is pinned to 768 dimensions by an explicit
    # output_dimensionality, not by luck: the paper_chunks.embedding
    # column is vector(768), and a model that silently returned a
    # different width would fail at insert instead of at startup.
    #
    # Both are overridable per environment. No pro-tier generation model
    # is currently available to this project; if access is granted,
    # setting GEMINI_GENERATION_MODEL to a pro variant is a one-line
    # change with no code edit.
    GEMINI_EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    GEMINI_GENERATION_MODEL: str = "models/gemini-3.8-flash"
    DEFAULT_TOP_K: int = 5
    DEFAULT_SIMILARITY_THRESHOLD: float = 0.65

    # Reranking (FR-15). Search reranks by default because the user is
    # already waiting on the response; chat now also reranks to improve
    # precision with the lower top_k.
    RERANK_SEARCH_DEFAULT: bool = True
    RERANK_CHAT_DEFAULT: bool = True

    # ------------------------------------------------------------------
    # Security (Part 18)
    # ------------------------------------------------------------------

    # Upload ceiling. The bucket also enforces this, so the limit cannot
    # be raised by changing only one of the two.
    MAX_UPLOAD_MB: int = 50

    # Inbound rate limiting. Every request is metered, but the endpoints
    # that spend money (an embedding, a generation, a rerank, a 50 MB
    # upload) get their own, much tighter budget: they are the ones worth
    # attacking, and the ones a user cannot legitimately hammer.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 120
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_AI_REQUESTS: int = 30
    RATE_LIMIT_AI_WINDOW_SECONDS: int = 60

    # Behind a reverse proxy or load balancer every socket arrives from
    # the proxy's address, so the client IP is only trustworthy when the
    # proxy is known to overwrite X-Forwarded-For. Off by default: an
    # unverified header would let a caller pick their own rate-limit key.
    TRUST_PROXY_HEADERS: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.ENVIRONMENT == "production"

    @model_validator(mode="after")
    def _reject_unsafe_production_settings(self) -> "Settings":
        """Refuse to boot a production deployment that is not secured.

        Each of these is a mistake that is invisible at runtime and
        expensive later: a wildcard CORS origin combined with
        ``allow_credentials`` lets any site make authenticated calls with
        the user's cookie, an unset service-role key disables the row
        level security the whole data model relies on, and a placeholder
        key fails only when the first real request is made.
        """
        if self.ENVIRONMENT not in ENVIRONMENTS:
            raise ValueError(
                f"ENVIRONMENT must be one of {list(ENVIRONMENTS)}, got {self.ENVIRONMENT!r}"
            )

        if not self.IS_PRODUCTION:
            return self

        problems: list[str] = []

        if "*" in self.CORS_ORIGINS:
            problems.append(
                'CORS_ORIGINS must not contain "*" in production: it is combined '
                "with allow_credentials, which makes any origin trusted"
            )
        insecure_origins = [
            origin
            for origin in self.CORS_ORIGINS
            if not origin.startswith("https://")
            or "localhost" in origin
            or "127.0.0.1" in origin
        ]
        if insecure_origins:
            problems.append(
                f"CORS_ORIGINS must be https and non-local in production: {insecure_origins}"
            )
        if not self.CORS_ORIGINS:
            problems.append("CORS_ORIGINS must list the deployed frontend origin")

        for name in (
            "GEMINI_API_KEY",
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        ):
            if _looks_like_placeholder(getattr(self, name)):
                problems.append(f"{name} is unset or still a placeholder")

        if not self.TRUST_PROXY_HEADERS:
            problems.append(
                "TRUST_PROXY_HEADERS must be enabled when deployed behind a proxy, "
                "or every client shares one rate-limit bucket"
            )

        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
