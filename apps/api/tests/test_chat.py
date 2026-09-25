"""Tests for the Chat API router.

Covers:
    POST   /api/chat
    GET    /api/conversations
    GET    /api/conversations/{id}
    DELETE /api/conversations/{id}

All Supabase calls and the RAG pipeline are mocked.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_application

# ---------------------------------------------------------------------------
# Fixtures & shared constants
# ---------------------------------------------------------------------------

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}
USER_ID = "00000000-0000-0000-0000-000000000000"  # dev-token user

CONV_ID = str(uuid4())
MSG_ID = str(uuid4())
PAPER_ID = str(uuid4())
CHUNK_ID = str(uuid4())


@pytest.fixture()
def client():
    return TestClient(create_application())


def _conv_row(conv_id: str = CONV_ID, title: str = "My Conv") -> dict:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": conv_id,
        "user_id": USER_ID,
        "title": title,
        "created_at": now,
        "updated_at": now,
    }


def _msg_row(
    msg_id: str = MSG_ID,
    conv_id: str = CONV_ID,
    role: str = "assistant",
    content: str = "Answer",
) -> dict:
    from datetime import datetime, timezone

    return {
        "id": msg_id,
        "conversation_id": conv_id,
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------


class TestChatEndpoint:
    @patch("app.api.chat.run_rag")
    @patch("app.api.chat.get_supabase_client")
    def test_new_conversation_success(self, mock_client_fn, mock_rag, client):
        """Creates a new conversation, runs RAG, persists messages + cites."""
        from app.rag.pipeline import RAGResult
        from app.schemas.search import SearchResultChunk

        chunk = SearchResultChunk(
            chunk_id=CHUNK_ID,
            paper_id=PAPER_ID,
            paper_title="Alpha Paper",
            page_number=7,
            section="Experiments",
            content="...",
            similarity_score=0.9,
        )
        mock_rag.return_value = RAGResult(
            answer="The answer is [1].",
            cited_chunks=[chunk],
            retrieved_count=1,
        )

        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db

        # Stub: create conversation
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[_conv_row()]
        )
        # Stub: insert user message
        user_msg_id = str(uuid4())
        assistant_msg_id = str(uuid4())
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            MagicMock(data=[_conv_row()]),           # conversations insert
            MagicMock(data=[_msg_row(msg_id=user_msg_id, role="user")]),  # user msg
            MagicMock(data=[_msg_row(msg_id=assistant_msg_id)]),           # asst msg
            MagicMock(data=[{}]),                    # citations insert
        ]

        resp = client.post(
            "/api/chat",
            json={"query": "What was the accuracy?"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "The answer is [1]."
        assert len(body["citations"]) == 1
        c = body["citations"][0]
        assert c["paper_title"] == "Alpha Paper"
        assert c["page_number"] == 7
        assert c["section"] == "Experiments"
        assert c["similarity_score"] == 0.9

    def test_unauthenticated_returns_401(self, client):
        resp = client.post("/api/chat", json={"query": "hello"})
        assert resp.status_code == 401

    def test_empty_query_returns_422(self, client):
        resp = client.post(
            "/api/chat", json={"query": ""}, headers=AUTH_HEADERS
        )
        assert resp.status_code == 422

    def test_top_k_out_of_range_returns_422(self, client):
        resp = client.post(
            "/api/chat",
            json={"query": "hello", "top_k": 50},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    @patch("app.api.chat.run_rag")
    @patch("app.api.chat.get_supabase_client")
    def test_503_when_api_key_missing(self, mock_client_fn, mock_rag, client):
        mock_rag.side_effect = RuntimeError("GEMINI_API_KEY is not configured.")
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[_conv_row()]
        )
        # user message insert
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            MagicMock(data=[_conv_row()]),
            MagicMock(data=[_msg_row(role="user")]),
        ]

        resp = client.post(
            "/api/chat", json={"query": "hello"}, headers=AUTH_HEADERS
        )
        assert resp.status_code == 503

    @patch("app.api.chat.run_rag")
    @patch("app.api.chat.get_supabase_client")
    def test_500_on_unexpected_error(self, mock_client_fn, mock_rag, client):
        mock_rag.side_effect = Exception("Unexpected failure")
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            MagicMock(data=[_conv_row()]),
            MagicMock(data=[_msg_row(role="user")]),
        ]

        resp = client.post(
            "/api/chat", json={"query": "hello"}, headers=AUTH_HEADERS
        )
        assert resp.status_code == 500

    @patch("app.api.chat.run_rag")
    @patch("app.api.chat.get_supabase_client")
    def test_existing_conversation_is_reused(self, mock_client_fn, mock_rag, client):
        """When conversation_id is provided, it is verified and reused."""
        from app.rag.pipeline import RAGResult

        mock_rag.return_value = RAGResult(
            answer="Continuing…", cited_chunks=[], retrieved_count=0
        )

        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db

        existing_id = str(uuid4())
        stub = mock_db.table.return_value
        stub = stub.select.return_value.eq.return_value.eq.return_value
        stub.single.return_value.execute.return_value = MagicMock(
            data={"id": existing_id}
        )
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            MagicMock(data=[_msg_row(conv_id=existing_id, role="user")]),
            MagicMock(data=[_msg_row(conv_id=existing_id, role="assistant")]),
        ]

        resp = client.post(
            "/api/chat",
            json={"query": "follow-up question", "conversation_id": existing_id},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["conversation_id"] == existing_id


# ---------------------------------------------------------------------------
# GET /api/conversations
# ---------------------------------------------------------------------------


class TestListConversations:
    @patch("app.api.chat.get_supabase_client")
    def test_returns_conversation_list(self, mock_client_fn, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        stub = mock_db.table.return_value
        stub = stub.select.return_value.eq.return_value.order.return_value
        stub.execute.return_value = MagicMock(
            data=[
                _conv_row(title="Conv A"),
                _conv_row(conv_id=str(uuid4()), title="Conv B"),
            ]
        )

        resp = client.get("/api/conversations", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["conversations"][0]["title"] == "Conv A"

    @patch("app.api.chat.get_supabase_client")
    def test_empty_list(self, mock_client_fn, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        stub = mock_db.table.return_value
        stub = stub.select.return_value.eq.return_value.order.return_value
        stub.execute.return_value = MagicMock(data=[])

        resp = client.get("/api/conversations", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/api/conversations")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/conversations/{id}
# ---------------------------------------------------------------------------


class TestGetConversation:
    @patch("app.api.chat.get_supabase_client")
    def test_returns_conversation_with_messages(self, mock_client_fn, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db

        # First call: conversation lookup
        # Second call: messages lookup
        stub = mock_db.table.return_value
        eq_stub = stub.select.return_value.eq.return_value.eq.return_value
        eq_stub.single.return_value.execute.return_value = MagicMock(
            data=_conv_row()
        )
        order_stub = stub.select.return_value.eq.return_value.order.return_value
        assistant_msg = _msg_row(role="assistant", content="A.")
        assistant_msg["citations"] = [{
            "chunk_id": CHUNK_ID, 
            "paper_id": PAPER_ID, 
            "papers": {"title": "Test Paper"},
            "page_number": 1,
            "similarity_score": 0.99
        }]
        order_stub.execute.return_value = MagicMock(
            data=[
                _msg_row(role="user", content="Q?"),
                assistant_msg,
            ]
        )

        resp = client.get(f"/api/conversations/{CONV_ID}", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == CONV_ID
        assert len(body["messages"]) == 2

    @patch("app.api.chat.get_supabase_client")
    def test_not_found(self, mock_client_fn, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        stub = mock_db.table.return_value
        stub = stub.select.return_value.eq.return_value.eq.return_value
        stub.single.return_value.execute.side_effect = Exception("not found")

        resp = client.get(f"/api/conversations/{uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/conversations/{id}
# ---------------------------------------------------------------------------


class TestDeleteConversation:
    @patch("app.api.chat.get_supabase_client")
    def test_deletes_successfully(self, mock_client_fn, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        stub = mock_db.table.return_value
        stub = stub.select.return_value.eq.return_value.eq.return_value
        stub.single.return_value.execute.return_value = MagicMock(
            data={"id": CONV_ID}
        )

        resp = client.delete(f"/api/conversations/{CONV_ID}", headers=AUTH_HEADERS)

        assert resp.status_code == 204

    @patch("app.api.chat.get_supabase_client")
    def test_not_found(self, mock_client_fn, client):
        mock_db = MagicMock()
        mock_client_fn.return_value = mock_db
        stub = mock_db.table.return_value
        stub = stub.select.return_value.eq.return_value.eq.return_value
        stub.single.return_value.execute.side_effect = Exception("not found")

        resp = client.delete(f"/api/conversations/{uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_unauthenticated_returns_401(self, client):
        resp = client.delete(f"/api/conversations/{CONV_ID}")
        assert resp.status_code == 401
