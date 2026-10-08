"""Orchestration layer: session mgmt, history load, SSE event forwarding, DB persistence,
billing. Owns everything the engines deliberately do NOT — input-safety gating, the `session` SSE
event, ChatSession/ChatMessage writes, and the usage-increment decision.

Two engines answer a question. The AutoCare MCP agent (autocare_agent.py) is the main one: the model calls
structured tools and never writes SQL. The old SQL agent (sql_agent.py) is only a fallback, used when the
AutoCare service is not available (see _answer_events).

Port of CHATBOT_ARCHITECTURE.md §5b, adapted for XIOMARA's user_id/client_id/connection_id
tenancy (adaptation #1) and BYO-token owner-resolution for collaborators (adaptation #5).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chatbot import ChatSession
from app.modules.chat_bot import autocare_agent, autocare_drill, guardrails, repo, sql_agent
from app.modules.chat_bot.answer_utils import BACKUP_ENGINE_NOTE
from app.modules.chat_bot.autocare_client import McpUnavailable
from app.modules.connections import repo as connections_repo
from app.modules.kpi import repo as kpi_repo
from app.modules.team import repo as team_repo

logger = logging.getLogger(__name__)

_HISTORY_LOAD_LIMIT = 5
_MCP_DOWN_MESSAGE = "The analytics service is not available right now. Please try again in a moment."
_BACKUP_ENGINE_NAME = "sql_fallback"


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


async def _load_history_from_db(db: AsyncSession, session_id: str, history_cleared_at) -> list[dict]:
    """Threads only the question and the LLM's own narrative answer into the next request's
    conversation history — never the SQL or query-result rows (those stay persisted on the
    ChatMessage row itself for re-rendering a session's past turns in the UI, just not fed
    back to the LLM as context).

    `history_cleared_at` is the session's "Clear history" marker (see
    repo.clear_session_history) — messages created at or before it are excluded from what's
    sent to the LLM, even though they're still stored and still shown in the UI transcript.
    After a clear, this turn's history starts empty and the usual 5-turn window builds back
    up from there as the conversation continues, exactly as if this were a brand-new
    session, until the user clears again."""
    messages = await repo.get_messages(db, session_id)
    if history_cleared_at is not None:
        messages = [m for m in messages if m.created_at > history_cleared_at]
    recent = messages[-_HISTORY_LOAD_LIMIT:]
    return [{"role": message.role, "content": message.content} for message in recent]


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
# Engine selection
# ---------------------------------------------------------------------------


async def _answer_events(
    *,
    db: AsyncSession,
    user_id: str,
    session: ChatSession,
    connection,
    token,
    message: str,
    history: list[dict],
) -> AsyncGenerator[dict, None]:
    """Answers with the AutoCare MCP agent. If the AutoCare service fails BEFORE any result was produced
    (cannot connect, timeout, HTTP 5xx, wrong or missing key), answers with the old SQL agent instead and
    appends a fixed note, provided the client has a BigQuery connection. A wrong answer, a model error,
    or a failure after a first result never starts the backup engine."""
    saw_result = False
    reason = ""
    try:
        async for event in autocare_agent.stream_autocare_query(
            provider=token.provider,
            model=token.model,
            api_key=token.llm_api_token,
            message=message,
            conversation_history=history,
        ):
            if event.get("type") in ("sql", "rows"):
                saw_result = True
            yield event
        return
    except McpUnavailable as error:
        reason = str(error)
    except Exception as error:  # a bug in the new engine must not end the chat stream
        logger.exception("AutoCare engine failed unexpectedly")
        reason = f"unexpected error: {error}"

    if saw_result:
        yield {"type": "error", "content": "The analytics service stopped responding. Please try again in a moment."}
        yield {"type": "done", "billable": False, "confidence": 0.2, "tables_used": []}
        return

    logger.warning("AutoCare MCP unavailable (%s); using the backup SQL engine", reason)
    if connection is None:
        yield {"type": "error", "content": _MCP_DOWN_MESSAGE}
        yield {"type": "done", "billable": False, "confidence": 0.0, "tables_used": []}
        return

    yield {"type": "status", "label": "Main analytics service not available. Using the backup engine…"}
    async for event in sql_agent.stream_single_query(
        db=db,
        user_id=user_id,
        connection=connection,
        client_id=session.client_id,
        provider=token.provider,
        model=token.model,
        api_key=token.llm_api_token,
        message=message,
        conversation_history=history,
    ):
        if event.get("type") == "text":
            event = {**event, "content": f"{event.get('content') or ''}\n\n{BACKUP_ENGINE_NOTE}"}
        elif event.get("type") == "rows":
            event = {**event, "engine": _BACKUP_ENGINE_NAME}
        yield event


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

    # The BigQuery connection is only needed by the backup SQL engine; the AutoCare MCP engine reads one
    # fixed dataset whatever client is selected.
    connection = None
    if session.connection_id:
        connection = await connections_repo.get_connection(db, session.connection_id)

    token = await get_active_token_for(db, user_id, session.client_id)
    if token is None:
        yield {
            "type": "error",
            "content": "Add an LLM API key in chatbot settings before asking a question.",
        }
        yield {"type": "done", "confidence": 0.0, "tables_used": [], "session_id": session.id}
        return

    is_resuming = bool(session_id) and session_id == session.id
    conversation_history = (
        await _load_history_from_db(db, session.id, session.history_cleared_at) if is_resuming else []
    )

    final_sql: str | None = None
    final_confidence = 0.0
    final_tables_used: list[str] = []
    final_rows_payload: dict | None = None
    answer_parts: list[str] = []
    billable: bool | None = None

    async for event in _answer_events(
        db=db,
        user_id=user_id,
        session=session,
        connection=connection,
        token=token,
        message=message,
        history=conversation_history,
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
        elif event_type == "row_count":
            if final_rows_payload is not None:
                final_rows_payload.update({k: v for k, v in event.items() if k != "type"})
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


def _error_events(content: str, session_id: str | None) -> list[dict]:
    return [
        {"type": "error", "content": content},
        {"type": "done", "confidence": 0.0, "tables_used": [], "session_id": session_id},
    ]


async def stream_drill_step(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    message: str,
    base_view: str,
    base_spec: dict,
    chain: list[dict],
) -> AsyncGenerator[dict, None]:
    """One segment drill-down step: answers `message` only within the previous step's segment. The new
    query must keep every filter of `base_spec` (see autocare_drill.py). Unlike stream_chat, nothing is
    persisted, no chat history is used, and there is no backup engine: a drill step needs the spec."""
    is_safe, block_reason = guardrails.check_input_safety(message)
    if not is_safe:
        for event in _error_events(block_reason or "This message can't be processed.", session_id):
            yield event
        return

    session = await repo.get_session(db, session_id)
    if session is None:
        for event in _error_events("This chat session is no longer available.", session_id):
            yield event
        return

    token = await get_active_token_for(db, user_id, session.client_id)
    if token is None:
        for event in _error_events("Add an LLM API key in chatbot settings before asking a question.", session.id):
            yield event
        return

    try:
        view, spec = autocare_drill.sanitize_base_spec(base_view, base_spec)
    except ValueError as error:
        for event in _error_events(
            f"This segment can't be narrowed: {error} Run the original question again, then drill down.",
            session.id,
        ):
            yield event
        return

    drill = autocare_drill.DrillContext(
        base_view=view,
        base_spec=spec,
        chain=[step for step in autocare_drill.sanitize_chain(chain) if guardrails.check_input_safety(step.question)[0]],
    )

    final_confidence = 0.0
    final_tables_used: list[str] = []
    billable: bool | None = None

    try:
        async for event in autocare_agent.stream_autocare_query(
            provider=token.provider,
            model=token.model,
            api_key=token.llm_api_token,
            message=message,
            conversation_history=[],
            drill=drill,
        ):
            if event.get("type") == "done":
                final_confidence = event.get("confidence", final_confidence)
                if event.get("tables_used"):
                    final_tables_used = event["tables_used"]
                billable = event.get("billable")
                continue
            yield event
    except McpUnavailable as error:
        logger.warning("AutoCare MCP unavailable during a drill-down step: %s", error)
        for event in _error_events(_MCP_DOWN_MESSAGE, session.id):
            yield event
        return
    except Exception:
        logger.exception("Drill-down step failed unexpectedly")
        for event in _error_events("Something went wrong while narrowing this segment. Please try again.", session.id):
            yield event
        return

    if _should_bill(billable, final_confidence):
        await repo.increment_usage(db, user_id)

    yield {
        "type": "done",
        "confidence": final_confidence,
        "tables_used": final_tables_used,
        "session_id": session.id,
    }
