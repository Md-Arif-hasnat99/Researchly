"""Chat API router.

Endpoints:
    POST   /api/chat                     — ask a question (RAG)
    GET    /api/conversations            — list user's conversations
    GET    /api/conversations/{id}       — conversation + messages + citations
    DELETE /api/conversations/{id}       — delete conversation

Flow for POST /api/chat:
    1. Resolve or create a conversation.
    2. Persist the user message.
    3. Run the RAG pipeline (retrieve + generate).
    4. Persist the assistant message.
    5. Persist citation rows for each cited chunk.
    6. Return the answer + citations.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.core.security import CurrentUser
from app.core.supabase import get_supabase_client
from app.rag.pipeline import run_rag
from app.schemas.conversation import (
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
)
from app.schemas.search import SearchResultChunk

router = APIRouter(tags=["Chat"])

# ---------------------------------------------------------------------------
# Request / response schemas (chat-specific, lives here to stay co-located)
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = Field(
        default=None,
        description="Continue an existing conversation, or omit to start a new one.",
    )
    paper_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Restrict RAG retrieval to these papers.  None = all user papers.",
    )
    top_k: int = Field(default=8, ge=1, le=20)
    similarity_threshold: float = Field(default=0.65, ge=0.0, le=1.0)


class ChatCitation(BaseModel):
    chunk_id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    page_number: int
    section: str | None = None
    similarity_score: float


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    citations: list[ChatCitation]


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_or_create_conversation(
    conversation_id: uuid.UUID | None,
    user_id: str,
    query: str,
) -> str:
    """Return an existing conversation's UUID string, or create a new one.

    The conversation title is derived from the first query (truncated).
    Ownership is verified when an ID is supplied.
    """
    client = get_supabase_client()

    if conversation_id is not None:
        try:
            result = (
                client.table("conversations")
                .select("id")
                .eq("id", str(conversation_id))
                .eq("user_id", user_id)
                .single()
                .execute()
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found.",
            )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found.",
            )
        return str(result.data["id"])

    # Create a new conversation — title from first 80 chars of query
    title = query[:80].strip() or "New Conversation"
    result = (
        client.table("conversations")
        .insert({"user_id": user_id, "title": title})
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation.",
        )
    return str(result.data[0]["id"])


def _persist_message(conversation_id: str, role: str, content: str) -> str:
    """Insert a message row and return its UUID string."""
    client = get_supabase_client()
    result = (
        client.table("messages")
        .insert(
            {
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist message.",
        )
    return str(result.data[0]["id"])


def _persist_citations(
    message_id: str,
    cited_chunks: list[SearchResultChunk],
) -> None:
    """Insert citation rows for each cited chunk."""
    if not cited_chunks:
        return
    client = get_supabase_client()
    rows = [
        {
            "message_id": message_id,
            "paper_id": str(chunk.paper_id),
            "chunk_id": str(chunk.chunk_id),
            "page_number": chunk.page_number,
            "similarity_score": chunk.similarity_score,
        }
        for chunk in cited_chunks
    ]
    client.table("citations").insert(rows).execute()


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: CurrentUser,
) -> ChatResponse:
    """Ask a grounded question using the RAG pipeline.

    - Optionally continues an existing conversation.
    - Persists user message, assistant message, and citation rows.
    - Returns the answer with inline citations.
    """
    user_id = str(current_user.id)

    # 1. Resolve / create conversation
    conv_id = _get_or_create_conversation(
        request.conversation_id, user_id, request.query
    )

    # 2. Persist user message
    _persist_message(conv_id, "user", request.query)

    # 3. Run RAG pipeline
    try:
        rag_result = run_rag(
            query=request.query,
            user_id=user_id,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            paper_ids=request.paper_ids,
        )
    except RuntimeError as exc:
        logger.error("RAG pipeline config error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("RAG pipeline error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Answer generation failed. Please try again.",
        ) from exc

    # 4. Persist assistant message
    assistant_msg_id = _persist_message(conv_id, "assistant", rag_result.answer)

    # 5. Persist citations
    _persist_citations(assistant_msg_id, rag_result.cited_chunks)

    # 6. Build response
    citations = [
        ChatCitation(
            chunk_id=chunk.chunk_id,
            paper_id=chunk.paper_id,
            paper_title=chunk.paper_title,
            page_number=chunk.page_number,
            section=chunk.section,
            similarity_score=chunk.similarity_score,
        )
        for chunk in rag_result.cited_chunks
    ]

    return ChatResponse(
        conversation_id=uuid.UUID(conv_id),
        message_id=uuid.UUID(assistant_msg_id),
        answer=rag_result.answer,
        citations=citations,
    )


# ---------------------------------------------------------------------------
# GET /api/conversations
# ---------------------------------------------------------------------------


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(current_user: CurrentUser) -> ConversationListResponse:
    """Return all conversations for the authenticated user, newest first."""
    client = get_supabase_client()
    result = (
        client.table("conversations")
        .select("*")
        .eq("user_id", str(current_user.id))
        .order("updated_at", desc=True)
        .execute()
    )
    convs = [ConversationResponse(**row) for row in (result.data or [])]
    return ConversationListResponse(conversations=convs, total=len(convs))


# ---------------------------------------------------------------------------
# GET /api/conversations/{conversation_id}
# ---------------------------------------------------------------------------


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
async def get_conversation(
    conversation_id: str,
    current_user: CurrentUser,
) -> ConversationDetailResponse:
    """Return a conversation with its full message history."""
    client = get_supabase_client()

    try:
        conv_result = (
            client.table("conversations")
            .select("*")
            .eq("id", conversation_id)
            .eq("user_id", str(current_user.id))
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    if not conv_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    # Fetch messages ordered chronologically
    msg_result = (
        client.table("messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )
    messages = [MessageResponse(**row) for row in (msg_result.data or [])]

    return ConversationDetailResponse(
        **conv_result.data,
        messages=messages,
    )


# ---------------------------------------------------------------------------
# DELETE /api/conversations/{conversation_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: str,
    current_user: CurrentUser,
) -> None:
    """Delete a conversation and all its messages/citations (ownership enforced)."""
    client = get_supabase_client()

    try:
        result = (
            client.table("conversations")
            .select("id")
            .eq("id", conversation_id)
            .eq("user_id", str(current_user.id))
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    client.table("conversations").delete().eq("id", conversation_id).execute()
    logger.info(
        "Conversation deleted: %s by user %s", conversation_id, current_user.id
    )
