"""Tests for the Gemini embedding service."""

from unittest.mock import MagicMock, patch

import pytest

from app.rag.embeddings.gemini import embed_query, embed_texts


class TestGeminiEmbeddings:
    @patch("app.rag.embeddings.gemini.get_settings")
    @patch("app.rag.embeddings.gemini.genai.Client")
    def test_embed_texts_success(self, mock_client_cls, mock_get_settings):
        mock_settings = MagicMock()
        mock_settings.GEMINI_API_KEY = "test_key"
        mock_settings.GEMINI_EMBEDDING_MODEL = "test_model"
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_emb1 = MagicMock()
        mock_emb1.values = [0.1] * 768
        mock_emb2 = MagicMock()
        mock_emb2.values = [0.2] * 768
        mock_response.embeddings = [mock_emb1, mock_emb2]

        mock_client.models.embed_content.return_value = mock_response

        texts = ["hello", "world"]
        vectors = embed_texts(texts)

        assert len(vectors) == 2
        assert len(vectors[0]) == 768
        assert vectors[0] == [0.1] * 768
        assert vectors[1] == [0.2] * 768
        mock_client.models.embed_content.assert_called_once()

    @patch("app.rag.embeddings.gemini.get_settings")
    def test_embed_texts_no_api_key(self, mock_get_settings):
        mock_settings = MagicMock()
        mock_settings.GEMINI_API_KEY = ""
        mock_get_settings.return_value = mock_settings

        with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not configured"):
            embed_texts(["hello"])

    @patch("app.rag.embeddings.gemini.get_settings")
    @patch("app.rag.embeddings.gemini.genai.Client")
    def test_embed_texts_invalid_dimension(self, mock_client_cls, mock_get_settings):
        mock_settings = MagicMock()
        mock_settings.GEMINI_API_KEY = "test_key"
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_emb = MagicMock()
        mock_emb.values = [0.1] * 100  # Invalid dimension
        mock_response.embeddings = [mock_emb]

        mock_client.models.embed_content.return_value = mock_response

        with pytest.raises(ValueError, match="Expected 768-dim vector"):
            embed_texts(["hello"])

    @patch("app.rag.embeddings.gemini.get_settings")
    @patch("app.rag.embeddings.gemini.genai.Client")
    def test_embed_query_success(self, mock_client_cls, mock_get_settings):
        mock_settings = MagicMock()
        mock_settings.GEMINI_API_KEY = "test_key"
        mock_settings.GEMINI_EMBEDDING_MODEL = "test_model"
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_emb = MagicMock()
        mock_emb.values = [0.5] * 768
        mock_response.embeddings = [mock_emb]

        mock_client.models.embed_content.return_value = mock_response

        vector = embed_query("test query")

        assert len(vector) == 768
        assert vector == [0.5] * 768
        mock_client.models.embed_content.assert_called_once()
