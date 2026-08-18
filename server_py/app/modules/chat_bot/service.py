"""Orchestration layer: session mgmt, history load, SSE event forwarding, DB persistence,
billing. Owns everything sql_agent.py deliberately does NOT — input-safety gating, the
`session` SSE event, ChatSession/ChatMessage writes, and the usage-increment decision.

Port of CHATBOT_ARCHITECTURE.md §5b, adapted for XIOMARA's user_id/client_id/connection_id
tenancy (adaptation #1) and BYO-token owner-resolution for collaborators (adaptation #5).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chatbot import ChatSession
from app.modules.chat_bot import guardrails, repo, sql_agent
from app.modules.connections import repo as connections_repo
from app.modules.kpi import repo as kpi_repo
from app.modules.team import repo as team_repo

_HISTORY_LOAD_LIMIT = 5
_HISTORY_ROWS_SAMPLE = 5


# ---------------------------------------------------------------------------
# Token resolution (adaptation #5 — no shared_user_id rows; for a collaborator acting on
# a shared client's chatbot, resolve the token by the CLIENT'S OWNING user, not the
# requester's own. `user_id` here is already the resolved actor id from
# app.dependencies.get_user_id, which for token-session collaborators is already the
# admin's id — the client-owner lookup below additionally covers OIDC team-member
# collaborators, whose own user_id differs from the client-owning admin's.)
# ---------------------------------------------------------------------------


async def _resolve_token_owner(db: AsyncSession, user_id: str, client_id: int | None) -> str:
    if client_id is None:
        return user_id
    client = await team_repo.get_client(db, client_id)
    if client is None:
        return user_id
    return client.user_id


async def get_active_token_for(db: AsyncSession, user_id: str, client_id: int | None):
    owner_user_id = await _resolve_token_owner(db, user_id, client_id)
    return await repo.get_active_token(db, owner_user_id)


# ---------------------------------------------------------------------------
# Session resolution
# ---------------------------------------------------------------------------


async def _resolve_connection_id(db: AsyncSession, client_id: int | None, connection_id: int | None) -> int | None:
    if connection_id is not None:
        return connection_id
    if client_id is not None:
        connection = await kpi_repo.get_connection_by_client_id(db, client_id)
        return connection.id if connection is not None else None
    return None


async def _resolve_or_create_session(
    db: AsyncSession,
    user_id: str,
    session_id: str | None,
    client_id: int | None,
    connection_id: int | None,
) -> ChatSession | None:
    if session_id:
        existing = await repo.get_session(db, session_id)
        if existing is not None and existing.user_id == user_id:
            return existing
        # Unknown/foreign session id — fall through and create a fresh session rather
        # than 404ing, matching the reference doc's fail-open session-resume behavior.

    resolved_connection_id = await _resolve_connection_id(db, client_id, connection_id)
    token = await get_active_token_for(db, user_id, client_id)
    session = await repo.create_session(
        db,
        user_id=user_id,
        client_id=client_id,
        connection_id=resolved_connection_id,
        token_id=token.id if token else None,
        name=None,
    )
    return session


def _rows_summary_for_history(rows_payload: dict) -> str | None:
    data = rows_payload.get("data") or []
    columns = rows_payload.get("columns") or []
    if not data:
        return None
    lines = ["(internal context, not shown to the user — rows returned by the previous query):"]
    for row in data[:_HISTORY_ROWS_SAMPLE]:
        lines.append(", ".join(f"{col}={row.get(col)}" for col in columns))
    total_rows = rows_payload.get("total_rows")
    if total_rows is not None:
        lines.append(f"(total_rows={total_rows})")
    return "\n".join(lines)


async def _load_history_from_db(db: AsyncSession, session_id: str) -> list[dict]:
    messages = await repo.get_messages(db, session_id)
    recent = messages[-_HISTORY_LOAD_LIMIT:]
    history: list[dict] = []
    for message in recent:
        content = message.content
        if message.role == "assistant" and message.rows:
            summary = _rows_summary_for_history(message.rows)
            if summary:
                content = f"{content}\n\n{summary}"
        history.append({"role": message.role, "content": content})
    return history


# ---------------------------------------------------------------------------
# Persistence + billing
# ---------------------------------------------------------------------------


async def _persist_exchange(
    db: AsyncSession,
    session_id: str,
    user_message: str,
    answer_text: str,
    sql: str | None,
    confidence: float,
    tables_used: list[str] | None,
    rows_payload: dict | None,
) -> None:
    await repo.create_message(db, session_id=session_id, role="user", content=user_message)
    await repo.create_message(
        db,
        session_id=session_id,
        role="assistant",
        content=answer_text,
        sql=sql,
        confidence=confidence,
        tables_used=tables_used or None,
        rows=rows_payload,
    )
    await repo.touch_session(db, session_id, first_message=user_message)


def _should_bill(billable: bool | None, confidence: float) -> bool:
    if billable is not None:
        return bool(billable)
    # Fallback heuristic if sql_agent ever omits the flag: every early-exit path in
    # sql_agent reports confidence <= 0.2 by construction.
    return confidence > 0.2


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def stream_chat(
    db: AsyncSession,
    user_id: str,
    session_id: str | None,
    client_id: int | None,
    connection_id: int | None,
    message: str,
) -> AsyncGenerator[dict, None]:
    is_safe, block_reason = guardrails.check_input_safety(message)
    if not is_safe:
        yield {"type": "error", "content": block_reason or "This message can't be processed."}
        yield {"type": "done", "confidence": 0.0, "tables_used": [], "session_id": session_id}
        return

    session = await _resolve_or_create_session(db, user_id, session_id, client_id, connection_id)
    if session is None:
        yield {"type": "error", "content": "Couldn't start a chat session."}
        yield {"type": "done", "confidence": 0.0, "tables_used": [], "session_id": session_id}
        return

    yield {"type": "session", "session_id": session.id, "name": session.name}

    connection = None
    if session.connection_id:
        connection = await connections_repo.get_connection(db, session.connection_id)
    if connection is None:
        yield {
            "type": "error",
            "content": "No BigQuery connection is configured for this client yet.",
        }
        yield {"type": "done", "confidence": 0.0, "tables_used": [], "session_id": session.id}
        return

    token = await get_active_token_for(db, user_id, session.client_id)
    if token is None:
        yield {
            "type": "error",
            "content": "Add an LLM API key in chatbot settings before asking a question.",
        }
        yield {"type": "done", "confidence": 0.0, "tables_used": [], "session_id": session.id}
        return

    is_resuming = bool(session_id) and session_id == session.id
    conversation_history = await _load_history_from_db(db, session.id) if is_resuming else []

    final_sql: str | None = None
    final_confidence = 0.0
    final_tables_used: list[str] = []
    final_rows_payload: dict | None = None
    answer_parts: list[str] = []
    billable: bool | None = None

    async for event in sql_agent.stream_single_query(
        db=db,
        user_id=user_id,
        connection=connection,
        client_id=session.client_id,
        provider=token.provider,
        model=token.model,
        api_key=token.llm_api_token,
        message=message,
        conversation_history=conversation_history,
    ):
        event_type = event.get("type")
        if event_type == "sql":
            final_sql = event.get("content")
            if event.get("tables_used"):
                final_tables_used = event["tables_used"]
            yield event
        elif event_type == "rows":
            final_rows_payload = {k: v for k, v in event.items() if k != "type"}
            yield event
        elif event_type == "text":
            answer_parts.append(event.get("content") or "")
            yield event
        elif event_type == "done":
            final_confidence = event.get("confidence", final_confidence)
            if event.get("tables_used"):
                final_tables_used = event["tables_used"]
            billable = event.get("billable")
            # Swallowed — service.py emits its own `done` (with session_id) below.
        else:
            # status / error — forwarded verbatim.
            yield event

    answer_text = "".join(answer_parts)
    await _persist_exchange(
        db, session.id, message, answer_text, final_sql, final_confidence, final_tables_used, final_rows_payload
    )

    if _should_bill(billable, final_confidence):
        await repo.increment_usage(db, user_id)

    yield {
        "type": "done",
        "confidence": final_confidence,
        "tables_used": final_tables_used,
        "session_id": session.id,
    }
