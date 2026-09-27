from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Embedding and generation defaults
    GEMINI_EMBEDDING_MODEL: str = "models/text-embedding-004"
    GEMINI_GENERATION_MODEL: str = "models/gemini-1.5-pro"
    DEFAULT_TOP_K: int = 8
    DEFAULT_SIMILARITY_THRESHOLD: float = 0.65

    # Reranking (FR-15). Search reranks by default because the user is
    # already waiting on the response; chat leaves it off because it would
    # add a full LLM round-trip to every turn of a conversation. Both are
    # overridable per request.
    RERANK_SEARCH_DEFAULT: bool = True
    RERANK_CHAT_DEFAULT: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
