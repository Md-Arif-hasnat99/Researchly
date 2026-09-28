"""Tests for Part 1: Pydantic schema validation and Supabase client configuration."""

import pytest

from app.core.config import get_settings
from app.schemas.conversation import ConversationCreate, MessageRole
from app.schemas.paper import PaperCreate, PaperStatus, PaperUpdate


class TestSettings:
    def test_settings_loads_defaults(self):
        settings = get_settings()
        assert settings.PROJECT_NAME == "Researchly API"
        assert settings.VERSION == "0.1.0"
        assert settings.DEFAULT_TOP_K == 5
        assert settings.DEFAULT_SIMILARITY_THRESHOLD == 0.65

    def test_cors_origins_are_list(self):
        settings = get_settings()
        assert isinstance(settings.CORS_ORIGINS, list)
        assert len(settings.CORS_ORIGINS) > 0

    def test_embedding_model_configured(self):
        """Assert the model's *shape*, not a literal name.

        This test used to assert the exact string
        "models/text-embedding-004". That model has since been retired by
        Google, and the assertion kept passing while every embedding call
        404'd — a green test guarding a broken deployment. The name is
        configurable and changes over time; what must not change is that
        it is a well-formed model reference and not a known-dead one.
        """
        settings = get_settings()
        model = settings.GEMINI_EMBEDDING_MODEL
        assert model.startswith("models/") and len(model) > len("models/")
        # Retired upstream: the API answers 404 NOT_FOUND for these.
        assert "text-embedding-004" not in model

    def test_generation_model_configured(self):
        """Same reasoning as the embedding model above.

        The default was "models/gemini-1.5-pro", which is retired, so
        every chat / compare / review / gaps request failed at the last
        step with a 404 from the API. Availability is per-project, so
        this also rejects the families this key is refused.
        """
        settings = get_settings()
        model = settings.GEMINI_GENERATION_MODEL
        assert model.startswith("models/") and len(model) > len("models/")
        for retired in ("gemini-1.5-pro", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"):
            assert retired not in model, (
                f"{model} is not available to this project; the API answers "
                "404 for it, so every generation request would fail"
            )


class TestPaperSchemas:
    def test_paper_status_enum_values(self):
        assert PaperStatus.uploaded == "uploaded"
        assert PaperStatus.processing == "processing"
        assert PaperStatus.ready == "ready"
        assert PaperStatus.failed == "failed"

    def test_paper_create_valid(self):
        paper = PaperCreate(
            title="Attention Is All You Need",
            authors=["Vaswani", "Shazeer"],
            publication_year=2017,
            file_path="user-id/paper-id.pdf",
            file_size=2048576,
        )
        assert paper.title == "Attention Is All You Need"
        assert len(paper.authors) == 2
        assert paper.publication_year == 2017

    def test_paper_create_defaults(self):
        paper = PaperCreate(file_path="user-id/paper-id.pdf")
        assert paper.title == "Untitled Paper"
        assert paper.authors == []
        assert paper.abstract is None

    def test_paper_update_partial(self):
        update = PaperUpdate(status=PaperStatus.ready, total_pages=15)
        assert update.status == PaperStatus.ready
        assert update.total_pages == 15
        assert update.title is None

    def test_paper_update_invalid_year(self):
        with pytest.raises(Exception):
            PaperUpdate(publication_year=999)  # below 1000

    def test_paper_update_future_year_invalid(self):
        with pytest.raises(Exception):
            PaperUpdate(publication_year=2200)  # above 2100


class TestConversationSchemas:
    def test_message_role_enum(self):
        assert MessageRole.user == "user"
        assert MessageRole.assistant == "assistant"

    def test_conversation_create_defaults(self):
        conv = ConversationCreate()
        assert conv.title == "New Conversation"
        assert conv.paper_ids is None

    def test_conversation_create_with_papers(self):
        import uuid

        paper_ids = [uuid.uuid4(), uuid.uuid4()]
        conv = ConversationCreate(title="RAG chat", paper_ids=paper_ids)
        assert len(conv.paper_ids) == 2
