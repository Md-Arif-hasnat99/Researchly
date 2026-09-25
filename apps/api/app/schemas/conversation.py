"""Pydantic schemas for Conversation and Message domain objects."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"


class MessageBase(BaseModel):
    role: MessageRole
    content: str


class MessageCreate(MessageBase):
    conversation_id: UUID


class MessageResponse(MessageBase):
    id: UUID
    conversation_id: UUID
    created_at: datetime
    citations: list[dict] | None = None

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    title: str = "New Conversation"
    paper_ids: list[UUID] | None = None


class ConversationResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse] = []
