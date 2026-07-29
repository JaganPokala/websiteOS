"""HTTP layer for conversations & messages. All endpoints require auth."""
# --- Imports: standard library ---
from uuid import UUID

# --- Imports: third-party ---
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

# --- Imports: local application ---
from app import db
from app.auth import get_current_user_id
from app.conversations import service

# --- Router setup ---
router = APIRouter(prefix="/conversations", tags=["conversations"])


# --- Request/response models ---
class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


# --- Routes ---
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(user_id: str = Depends(get_current_user_id)):
    return await service.create_conversation(db.get_pool(), user_id)


@router.get("")
async def list_conversations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    return await service.list_conversations(db.get_pool(), user_id, limit, offset)


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    rows = await service.get_messages(db.get_pool(), user_id, conversation_id, limit, offset)
    if rows is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return rows


@router.patch("/{conversation_id}")
async def rename_conversation(
    conversation_id: UUID,
    body: RenameRequest,
    user_id: str = Depends(get_current_user_id),
):
    row = await service.rename_conversation(db.get_pool(), user_id, conversation_id, body.title)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return row


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    user_id: str = Depends(get_current_user_id),
):
    ok = await service.delete_conversation(db.get_pool(), user_id, conversation_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    # 204 → no body