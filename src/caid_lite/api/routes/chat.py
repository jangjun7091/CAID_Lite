"""POST /api/chat — submit a natural language prompt."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..deps import get_manager
from ...session.manager import SessionManager

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Natural language description")


class ChatResponse(BaseModel):
    part_id: str
    message: str


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    body: ChatRequest,
    manager: SessionManager = Depends(get_manager),
) -> ChatResponse:
    """Accept a user message and start an async generation run.

    Returns immediately with the ``part_id`` that will be tracked via
    ``GET /api/events`` and ``GET /api/parts/{part_id}``.
    """
    part_id = await manager.generate(body.message)
    return ChatResponse(
        part_id=part_id,
        message="Generation started. Subscribe to /api/events for status updates.",
    )
