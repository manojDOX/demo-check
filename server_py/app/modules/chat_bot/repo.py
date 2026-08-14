"""Data-access helpers for the chatbot's own tables: ChatbotToken, ChatSession,
ChatMessage, ChatbotUsage. Kept in this module (not connections/repo.py or kpi/repo.py)
since these tables are chat_bot-owned per app/models/chatbot.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chatbot import ChatbotToken, ChatbotUsage, ChatMessage, ChatSession

# ---------------------------------------------------------------------------
# ChatbotToken
# ---------------------------------------------------------------------------


async def get_tokens(db: AsyncSession, owner_user_id: str) -> list[ChatbotToken]:
    result = await db.execute(
        select(ChatbotToken).where(ChatbotToken.owner_user_id == owner_user_id).order_by(desc(ChatbotToken.created_at))
    )
    return list(result.scalars().all())


async def get_token(db: AsyncSession, token_id: str) -> ChatbotToken | None:
    result = await db.execute(select(ChatbotToken).where(ChatbotToken.id == token_id))
    return result.scalar_one_or_none()


async def get_active_token(db: AsyncSession, owner_user_id: str) -> ChatbotToken | None:
    result = await db.execute(
        select(ChatbotToken)
        .where(ChatbotToken.owner_user_id == owner_user_id, ChatbotToken.is_active.is_(True))
        .order_by(desc(ChatbotToken.created_at))
    )
    return result.scalars().first()


async def create_token(
    db: AsyncSession,
    *,
    owner_user_id: str,
    llm_api_token: str,
    provider: str,
    model: str,
    available_models: str | None,
    display_name: str | None,
) -> ChatbotToken:
    token = ChatbotToken(
        owner_user_id=owner_user_id,
        llm_api_token=llm_api_token,
        provider=provider,
        model=model,
        available_models=available_models,
        display_name=display_name,
        is_active=True,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return token


async def update_token(db: AsyncSession, token_id: str, **fields) -> ChatbotToken | None:
    token = await get_token(db, token_id)
    if token is None:
        return None
    for key, value in fields.items():
        setattr(token, key, value)
    await db.commit()
    await db.refresh(token)
    return token


async def delete_token(db: AsyncSession, token_id: str) -> None:
    await db.execute(delete(ChatbotToken).where(ChatbotToken.id == token_id))
    await db.commit()


# ---------------------------------------------------------------------------
# ChatSession
# ---------------------------------------------------------------------------


async def get_sessions(db: AsyncSession, user_id: str) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession).where(ChatSession.user_id == user_id).order_by(desc(ChatSession.updated_at))
    )
    return list(result.scalars().all())


async def get_session(db: AsyncSession, session_id: str) -> ChatSession | None:
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    return result.scalar_one_or_none()


async def create_session(
    db: AsyncSession,
    *,
    user_id: str,
    client_id: int | None,
    connection_id: int | None,
    token_id: str | None,
    name: str | None,
) -> ChatSession:
    session = ChatSession(
        user_id=user_id,
        client_id=client_id,
        connection_id=connection_id,
        token_id=token_id,
        name=name,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def update_session(db: AsyncSession, session_id: str, **fields) -> ChatSession | None:
    session = await get_session(db, session_id)
    if session is None:
        return None
    for key, value in fields.items():
        setattr(session, key, value)
    session.updated_at = datetime.utcnow()  # TIMESTAMP WITHOUT TIME ZONE column
    await db.commit()
    await db.refresh(session)
    return session


async def touch_session(db: AsyncSession, session_id: str, *, first_message: str | None = None) -> None:
    session = await get_session(db, session_id)
    if session is None:
        return
    if not session.name and first_message:
        session.name = first_message.strip()[:80]
    session.updated_at = datetime.utcnow()  # TIMESTAMP WITHOUT TIME ZONE column
    await db.commit()


async def delete_session(db: AsyncSession, session_id: str) -> None:
    # ChatMessage rows cascade-delete via the FK's ondelete="CASCADE".
    await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db.commit()


# ---------------------------------------------------------------------------
# ChatMessage
# ---------------------------------------------------------------------------


async def get_messages(db: AsyncSession, session_id: str) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    )
    return list(result.scalars().all())


async def create_message(
    db: AsyncSession,
    *,
    session_id: str,
    role: str,
    content: str,
    sql: str | None = None,
    confidence: float | None = None,
    tables_used: list | None = None,
    rows: dict | None = None,
) -> ChatMessage:
    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        sql=sql,
        confidence=confidence,
        tables_used=tables_used,
        rows=rows,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


# ---------------------------------------------------------------------------
# ChatbotUsage
# ---------------------------------------------------------------------------


async def increment_usage(db: AsyncSession, user_id: str) -> ChatbotUsage:
    result = await db.execute(select(ChatbotUsage).where(ChatbotUsage.user_id == user_id))
    usage = result.scalar_one_or_none()
    if usage is None:
        usage = ChatbotUsage(user_id=user_id, successful_calls=1)
        db.add(usage)
    else:
        usage.successful_calls = (usage.successful_calls or 0) + 1
    await db.commit()
    return usage
