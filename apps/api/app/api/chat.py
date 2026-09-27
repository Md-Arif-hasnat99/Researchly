"""Chat API router.

Endpoints:
    POST   /api/chat                     — ask a question (RAG)
    POST   /api/chat/stream              — same, streamed as SSE tokens
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

POST /api/chat/stream performs the same steps, but retrieval happens
before the response starts (so failures there are still real HTTP status
codes) and only generation is streamed, one SSE event at a time.
"""

import json
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.core.logging import logger
from app.core.security import CurrentUser
from app.core.supabase import get_supabase_client
from app.rag.generation.gemini import stream_answer
from app.rag.pipeline import RetrievedContext, retrieve_context, run_rag
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
    rerank: bool | None = Field(
        default=None,
        description=(
            "Rerank retrieved chunks before generation (FR-15). None = "
            "server default, which is off for chat."
        ),
    )

    @field_validator("query")
    @classmethod
    def _reject_blank_query(cls, value: str) -> str:
        """Reject a whitespace-only question.

        ``min_length=1`` admits " ", which spends a retrieval round trip
        and a generation call to produce an answer to nothing. Search
        rejects the same input for the same reason.
        """
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class ChatCitation(BaseModel):
    chunk_id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    page_number: int
    section: str | None = None
    # Optional because the citations column is nullable and the retrieval
    # layer now also produces keyword-only hits with no vector score. The
    # chat pipeline is vector-only today, so this is None only in theory.
    similarity_score: float | None = None
    content: str | None = None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    citations: list[ChatCitation]
    reranked: bool = False
    """True only when a reranker reordered the context sent to Gemini (FR-15)."""


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


def _to_citations(chunks) -> list[ChatCitation]:
    """Map retrieved chunks onto the API's citation shape."""
    return [
        ChatCitation(
            chunk_id=chunk.chunk_id,
            paper_id=chunk.paper_id,
            paper_title=chunk.paper_title,
            page_number=chunk.page_number,
            section=chunk.section,
            similarity_score=chunk.similarity_score,
            content=chunk.content,
        )
        for chunk in chunks
    ]


def _raise_retrieval_failure(exc: Exception) -> None:
    """Translate a retrieval failure into the right HTTP error.

    The RuntimeError text names internal configuration (which env var is
    missing), so it is logged for the operator and the user gets a message
    that does not describe the server's wiring.
    """
    if isinstance(exc, RuntimeError):
        logger.error("RAG pipeline config error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Answer generation is temporarily unavailable. Please try again shortly.",
        ) from exc

    logger.error("RAG pipeline error: %s", exc, exc_info=True)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Answer generation failed. Please try again.",
    ) from exc


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    current_user: CurrentUser,
) -> ChatResponse:
    """Ask a grounded question using the RAG pipeline.

    - Optionally continues an existing conversation.
    - Persists user message, assistant message, and citation rows.
    - Returns the answer with inline citations.

    Sync ``def`` on purpose: retrieval and generation are blocking
    network calls, and awaiting them inline would block the event loop
    for every other request. FastAPI threadpools sync handlers.
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
            rerank=request.rerank,
        )
    except Exception as exc:
        _raise_retrieval_failure(exc)

    # 4. Persist assistant message
    assistant_msg_id = _persist_message(conv_id, "assistant", rag_result.answer)

    # 5. Persist citations
    _persist_citations(assistant_msg_id, rag_result.cited_chunks)

    # 6. Build response
    return ChatResponse(
        conversation_id=uuid.UUID(conv_id),
        message_id=uuid.UUID(assistant_msg_id),
        answer=rag_result.answer,
        citations=_to_citations(rag_result.cited_chunks),
        reranked=rag_result.reranked,
    )


# ---------------------------------------------------------------------------
# POST /api/chat/stream
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> bytes:
    """Serialise one Server-Sent Event frame.

    ``data`` is compact JSON on a single line: a newline inside a data
    field would terminate the frame early, and ``json.dumps`` never emits
    a raw newline for a string.
    """
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


@router.post("/chat/stream")
def chat_stream(
    request: ChatRequest,
    current_user: CurrentUser,
) -> StreamingResponse:
    """Ask a question and stream the answer as it is generated.

    Same pipeline and same persisted rows as ``POST /api/chat``; the
    difference is when the bytes leave. There, the client waits for a
    complete multi-second answer before showing anything. Here the answer
    arrives token by token, so the perceived wait is the time to the first
    token rather than the time to the last one.

    Event sequence:

    * ``citations`` — sent first, from retrieval, so the client can show
      which sources the answer is being grounded in before any text
      exists.
    * ``token``     — one or more, each carrying an increment of text.
    * ``done``      — the persisted ``message_id`` and ``reranked`` flag.
    * ``error``     — a failure during generation. The status line is
      already sent by then, so the failure is reported in-band.

    Everything that can fail *before* the first byte — conversation
    resolution and retrieval — still runs in the handler, so those
    failures keep their real HTTP status codes instead of degrading into
    a 200 with an error event.
    """
    user_id = str(current_user.id)

    # 1. Resolve / create conversation, and persist the user message, both
    #    before the response starts so failures are still HTTP errors.
    conv_id = _get_or_create_conversation(
        request.conversation_id, user_id, request.query
    )
    _persist_message(conv_id, "user", request.query)

    # 2. Retrieve. Same retrieve/rerank path as the buffered endpoint.
    try:
        context: RetrievedContext = retrieve_context(
            query=request.query,
            user_id=user_id,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            paper_ids=request.paper_ids,
            rerank=request.rerank,
        )
    except Exception as exc:
        _raise_retrieval_failure(exc)

    citations = _to_citations(context.chunks)

    # 3. Stream generation. A sync generator: Starlette iterates it in a
    #    threadpool, so the blocking Gemini reads never touch the event
    #    loop and other requests keep flowing while a stream is open.
    def event_stream() -> Iterator[bytes]:
        yield _sse(
            "citations",
            # mode="json": paper_id is a UUID, which json.dumps cannot
            # serialise unless the dump coerces it to a string.
            {"citations": [c.model_dump(mode="json") for c in citations]},
        )

        collected: list[str] = []
        try:
            for text in stream_answer(query=request.query, chunks=context.chunks):
                collected.append(text)
                yield _sse("token", {"text": text})
        except Exception as exc:  # noqa: BLE001
            # The status line is long gone, so the error has to travel in
            # the body. Deliberately generic for the same reason as the
            # buffered path: the cause is logged, not returned.
            logger.error("Streaming answer failed: %s", exc, exc_info=True)
            yield _sse(
                "error",
                {
                    "code": "GENERATION_FAILED",
                    "message": "Answer generation failed. Please try again.",
                },
            )
            return

        answer = "".join(collected)
        try:
            assistant_msg_id = _persist_message(conv_id, "assistant", answer)
            _persist_citations(assistant_msg_id, context.chunks)
        except Exception as exc:  # noqa: BLE001
            # The text already reached the client, so the answer is not
            # lost from their side, but it will not be in the history.
            # Surfaced in-band so the UI can say so rather than showing a
            # response that silently fails to persist.
            logger.error("Failed to persist streamed answer: %s", exc, exc_info=True)
            yield _sse(
                "error",
                {
                    "code": "PERSIST_FAILED",
                    "message": "The answer was generated but could not be saved to history.",
                },
            )
            return

        yield _sse(
            "done",
            {"message_id": assistant_msg_id, "reranked": context.reranked},
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Nginx and similar proxies buffer responses by default, which
            # would hold the whole answer back and defeat the point.
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/conversations
# ---------------------------------------------------------------------------


@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(current_user: CurrentUser) -> ConversationListResponse:
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
def get_conversation(
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
        .select("*, citations(*, papers(title), paper_chunks(content))")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )

    # ponytail: manual title mapping to match ChatCitation schema without a new model
    messages = []
    for row in (msg_result.data or []):
        if row.get("citations"):
            for c in row["citations"]:
                c["paper_title"] = c.get("papers", {}).get("title", "Unknown Paper")
                c["content"] = c.get("paper_chunks", {}).get("content", "")
        messages.append(MessageResponse(**row))

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
def delete_conversation(
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
