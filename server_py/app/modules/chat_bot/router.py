"""FastAPI routes for the session-based, SSE-streaming "Ask Your Data" chatbot.

Pure HTTP layer — delegates everything to service.py (chat) / repo.py (session + token
CRUD) / llm_client.py (model discovery for token add). Mounted by hand into
app/main.py (not done here — see the port task's rules).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import to_camel, to_camel_list
from app.db import SessionLocal, get_db
from app.dependencies import can_access_client, get_user_id, require_authenticated_or_token
from app.models.chatbot import ChatbotToken, ChatSession
from app.modules.chat_bot import repo, service
from app.modules.chat_bot.llm_client import discover_models

router = APIRouter(tags=["chat-bot"], dependencies=[Depends(require_authenticated_or_token)])


# ---------------------------------------------------------------------------
# Chat streaming
# ---------------------------------------------------------------------------


class ChatStreamBody(BaseModel):
    sessionId: str | None = None
    message: str
    clientId: int | None = None
    connectionId: int | None = None


async def _sse_body(user_id: str, session_id: str | None, client_id: int | None, connection_id: int | None, message: str):
    # A fresh DB session is opened here (rather than reusing the Depends(get_db) session)
    # because FastAPI's dependency-injected AsyncSession is closed as soon as the route
    # handler function returns — before a StreamingResponse's body generator actually
    # runs — so it would be invalid by the time service.stream_chat tries to use it.
    async with SessionLocal() as db:
        async for event in service.stream_chat(db, user_id, session_id, client_id, connection_id, message):
            yield f"data: {json.dumps(event)}\n\n"


@router.post("/api/chat/stream")
async def chat_stream(body: ChatStreamBody, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_user_id(request)
    if body.clientId is not None:
        if not await can_access_client(request, db, body.clientId):
            raise HTTPException(status_code=403, detail="Access denied")

    return StreamingResponse(
        _sse_body(user_id, body.sessionId, body.clientId, body.connectionId, body.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


async def _can_access_session(request: Request, db: AsyncSession, session: ChatSession, user_id: str) -> bool:
    if session.user_id == user_id:
        return True
    if session.client_id is not None:
        return await can_access_client(request, db, session.client_id)
    return False


@router.get("/api/chat/sessions")
async def list_sessions(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_user_id(request)
    sessions = await repo.get_sessions(db, user_id)
    return to_camel_list(sessions)


@router.get("/api/chat/sessions/{session_id}/messages")
async def list_session_messages(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_user_id(request)
    session = await repo.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not await _can_access_session(request, db, session, user_id):
        raise HTTPException(status_code=403, detail="Access denied")
    messages = await repo.get_messages(db, session_id)
    return to_camel_list(messages)


class RenameSessionBody(BaseModel):
    name: str


@router.patch("/api/chat/sessions/{session_id}")
async def rename_session(session_id: str, body: RenameSessionBody, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_user_id(request)
    session = await repo.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not await _can_access_session(request, db, session, user_id):
        raise HTTPException(status_code=403, detail="Access denied")
    updated = await repo.update_session(db, session_id, name=body.name)
    return to_camel(updated)


@router.delete("/api/chat/sessions/{session_id}")
async def delete_session(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_user_id(request)
    session = await repo.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not await _can_access_session(request, db, session, user_id):
        raise HTTPException(status_code=403, detail="Access denied")
    await repo.delete_session(db, session_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# Token CRUD (BYO multi-provider LLM keys)
# ---------------------------------------------------------------------------


def _mask_token(token: ChatbotToken) -> dict:
    camel = to_camel(token)
    camel["llmApiToken"] = "[ENCRYPTED]"
    if token.available_models:
        try:
            camel["availableModels"] = json.loads(token.available_models)
        except Exception:
            camel["availableModels"] = []
    else:
        camel["availableModels"] = []
    return camel


@router.get("/api/chat/tokens")
async def list_tokens(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_user_id(request)
    tokens = await repo.get_tokens(db, user_id)
    return [_mask_token(t) for t in tokens]


class CreateTokenBody(BaseModel):
    provider: str
    apiKey: str
    displayName: str | None = None


@router.post("/api/chat/tokens")
async def create_token(body: CreateTokenBody, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_user_id(request)
    try:
        discovery = await discover_models(body.provider, body.apiKey)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error) or "Couldn't validate that API key.")

    default_model = discovery.get("default_model")
    available_models = discovery.get("available_models") or []
    if not default_model:
        raise HTTPException(status_code=400, detail="No usable models were found for that API key.")

    token = await repo.create_token(
        db,
        owner_user_id=user_id,
        llm_api_token=body.apiKey,
        provider=body.provider,
        model=default_model,
        available_models=json.dumps(available_models),
        display_name=body.displayName,
    )
    return _mask_token(token)


class UpdateTokenBody(BaseModel):
    model: str | None = None
    displayName: str | None = None
    isActive: bool | None = None


@router.patch("/api/chat/tokens/{token_id}")
async def update_token(token_id: str, body: UpdateTokenBody, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_user_id(request)
    token = await repo.get_token(db, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    fields: dict = {}
    if body.model is not None:
        fields["model"] = body.model
    if body.displayName is not None:
        fields["display_name"] = body.displayName
    if body.isActive is not None:
        fields["is_active"] = body.isActive

    updated = await repo.update_token(db, token_id, **fields)
    return _mask_token(updated)


@router.delete("/api/chat/tokens/{token_id}")
async def delete_token(token_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_user_id(request)
    token = await repo.get_token(db, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    await repo.delete_token(db, token_id)
    return {"success": True}
