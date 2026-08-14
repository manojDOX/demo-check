"""MCP tool-calling pipeline: the LLM drives its own BigQuery investigation (dataset/table
discovery, SQL execution) via Google's hosted remote BigQuery MCP server
(https://bigquery.googleapis.com/mcp), instead of the old manual
schema-fetch -> table-select -> SQL-gen -> dry-run/fix/retry pipeline.

Adapted from the reference implementation's `chat.py` agent loop
(F:\\prowiz\\bq-mcp\\MCP-Chat_bot\\app\\chat.py). See mcp_client.py for the transport and
llm_client.py's `call_llm_with_tools`/`messages_with_tool_result` for the per-provider
tool-calling normalization this loop relies on.

Never touches session/persistence/input-safety-gating — that's service.py's job. Yields
event dicts (`status`, `sql`, `rows`, `text`, `error`, `done` — snake_case keys); `session`/
`done`-with-session_id are NOT emitted here — service.py owns those (it does consume this
module's own `done` event for its `billable`/`confidence`/`tables_used` fields, then emits
its own final `done`).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator

from app.modules.chat_bot import guardrails, prompts
from app.modules.chat_bot.config import CHATBOT_MAX_TOOL_RESULT_CHARS, CHATBOT_MAX_TOOL_ROUNDS
from app.modules.chat_bot.llm_client import (
    call_llm_with_tools,
    mcp_tools_to_openai_format,
    messages_with_tool_result,
)
from app.modules.chat_bot.mcp_client import BigQueryMCPClient

# Tool names that execute SQL against BigQuery — SQL-safety interception (guardrails.
# check_sql_safety) applies to these before the tool is actually called. The real hosted
# MCP server (live-verified 2026-08-14) exposes exactly `execute_sql_readonly` and
# `execute_sql`, both taking the SQL string as arguments["query"]. The substring fallback
# below is a defensive net in case Google renames/adds an execute-style tool later.
_KNOWN_SQL_TOOL_NAMES = {"execute_sql_readonly", "execute_sql"}


def _is_sql_tool(name: str) -> bool:
    if name in _KNOWN_SQL_TOOL_NAMES:
        return True
    low = name.lower()
    return "execute" in low and ("sql" in low or "query" in low)


def _extract_sql_from_arguments(arguments: dict) -> str:
    return arguments.get("query") or arguments.get("sql") or ""


_TABLE_REF_RE = re.compile(r"`?([a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)`?")


def _extract_tables_used(sql: str) -> list[str]:
    """Best-effort regex extraction of `project.dataset.table` references from a SQL
    string, matching how the old pipeline populated the `tables_used` field."""
    if not sql:
        return []
    seen: list[str] = []
    for match in _TABLE_REF_RE.finditer(sql):
        ref = match.group(1)
        if ref not in seen:
            seen.append(ref)
    return seen


def _parse_bq_rows(structured: dict) -> tuple[list[str], list[dict], int]:
    """Parses the BigQuery legacy-REST tabledata shape returned in an
    execute_sql(_readonly) tool result's `structuredContent`:
        {"schema": {"fields": [{"name","type","mode"}, ...]},
         "rows": [{"f": [{"v": ...}, ...]}, ...], ...}
    into (columns, [{col: value, ...}, ...], total_row_count)."""
    schema = structured.get("schema") or {}
    fields = schema.get("fields") or []
    columns = [f.get("name") for f in fields]
    raw_rows = structured.get("rows") or []
    data: list[dict] = []
    for row in raw_rows:
        cells = row.get("f") or []
        record = {}
        for name, cell in zip(columns, cells):
            record[name] = cell.get("v") if isinstance(cell, dict) else cell
        data.append(record)
    total_rows = structured.get("totalRows")
    try:
        total_rows = int(total_rows) if total_rows is not None else len(data)
    except (TypeError, ValueError):
        total_rows = len(data)
    return columns, data, total_rows


def _looks_like_bq_rows(structured) -> bool:
    return isinstance(structured, dict) and ("schema" in structured or "rows" in structured)


def _done_event(billable: bool, confidence: float, tables_used: list[str]) -> dict:
    return {"type": "done", "billable": billable, "confidence": confidence, "tables_used": tables_used}


def _sql_only_tools(mcp_tools: list[dict]) -> list[dict]:
    """Strips schema/discovery tools (list_dataset_ids, get_table_info, ...) out of what's
    offered to the model. Safe only because this deployment's schema is static and baked
    into MCP_STATIC_SCHEMA_SYSTEM_PROMPT — the model never needs to look anything up.
    Falls back to the full tool list if, for some reason, no SQL-execution tool is found
    (e.g. the hosted MCP server renames its tools), so the agent degrades gracefully
    instead of being left with zero usable tools."""
    filtered = [t for t in mcp_tools if _is_sql_tool(t.get("name", ""))]
    return filtered or mcp_tools


def _build_initial_messages(conversation_history: list[dict] | None, message: str) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": prompts.MCP_STATIC_SCHEMA_SYSTEM_PROMPT}]
    for turn in conversation_history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def stream_single_query(
    db,
    user_id: str,
    connection,
    client_id: int | None,
    provider: str,
    model: str,
    api_key: str,
    message: str,
    conversation_history: list[dict] | None,
) -> AsyncGenerator[dict, None]:
    # --- MCP client construction --------------------------------------------------------
    try:
        mcp = BigQueryMCPClient(connection.credentials, connection.project_id)
    except Exception as error:
        yield {"type": "error", "content": f"Couldn't set up the BigQuery connection: {error}"}
        yield _done_event(False, 0.0, [])
        return

    try:
        # --- Tool discovery ---------------------------------------------------------
        yield {"type": "status", "label": "Connecting to BigQuery…"}
        try:
            mcp_tools = await mcp.list_tools()
        except Exception as error:
            yield {"type": "error", "content": f"Couldn't reach BigQuery: {error}"}
            yield _done_event(False, 0.0, [])
            return

        if not mcp_tools:
            yield {"type": "error", "content": "No BigQuery tools are available for this connection."}
            yield _done_event(False, 0.0, [])
            return

        openai_format_tools = mcp_tools_to_openai_format(_sql_only_tools(mcp_tools))
        messages = _build_initial_messages(conversation_history, message)
        tables_used: list[str] = []

        status_labels = ["Thinking…", "Looking up your data…", "Analyzing your question…"]

        for round_idx in range(CHATBOT_MAX_TOOL_ROUNDS):
            yield {"type": "status", "label": status_labels[min(round_idx, len(status_labels) - 1)]}
            try:
                response = await call_llm_with_tools(
                    provider, model, api_key, messages, openai_format_tools, max_tokens=3000, temperature=0.2
                )
            except Exception as error:
                yield {"type": "error", "content": f"Couldn't get a response from the model: {error}"}
                yield _done_event(False, 0.0, tables_used)
                return

            messages.append(response["raw_message"])
            tool_calls = response.get("tool_calls")

            if not tool_calls:
                content = (response.get("content") or "").strip()
                if content:
                    yield {"type": "text", "content": content}
                else:
                    yield {
                        "type": "text",
                        "content": "I couldn't find relevant data to answer that question.",
                    }
                yield _done_event(True, 0.8 if content else 0.2, tables_used)
                return

            # --- Tool-call round ----------------------------------------------------
            for call in tool_calls:
                name = call["name"]
                arguments = dict(call.get("arguments") or {})
                # Force-override rather than setdefault: live testing against the real
                # hosted MCP server showed the model can hallucinate a placeholder value
                # for `projectId` (observed: literally the string "projectId", i.e. the
                # JSON-schema field's own name) when the prompt doesn't spell out the
                # actual id. Each XIOMARA connection maps to exactly one BigQuery
                # project, so there's no legitimate reason for the model to pick a
                # different one — always use the connection's project_id.
                arguments["projectId"] = connection.project_id

                if _is_sql_tool(name):
                    sql = _extract_sql_from_arguments(arguments)
                    is_safe, unsafe_reason = guardrails.check_sql_safety(sql)
                    if not is_safe:
                        yield {
                            "type": "error",
                            "content": unsafe_reason or "The generated query failed a safety check.",
                        }
                        yield _done_event(False, 0.0, tables_used)
                        return
                    for table in _extract_tables_used(sql):
                        if table not in tables_used:
                            tables_used.append(table)
                    yield {"type": "sql", "content": sql, "tables_used": tables_used}
                    yield {"type": "status", "label": "Running query…"}

                try:
                    result = await mcp.call_tool(name, arguments)
                except Exception as exc:
                    result_content = (
                        "TOOL CALL FAILED — this did not run successfully and produced NO data. "
                        f"Error: {exc}. You MUST NOT answer the user's question using this as if it "
                        "succeeded. Either fix the problem and retry, or tell the user you couldn't "
                        "retrieve the data."
                    )
                else:
                    # MCP tool-execution failures (e.g. a BigQuery SQL error) come back as a
                    # *successful* JSON-RPC response with isError=true and no structuredContent —
                    # NOT an exception, and NOT distinguishable from real data just by looking at
                    # the raw JSON shape. Live-verified against the real hosted MCP server: a bad
                    # column name returns {"content":[{"type":"text","text":"Unrecognized name..."}],
                    # "isError":true}. Burying that in a raw json.dumps() of the whole payload let
                    # the model notice-but-ignore it and hallucinate a summary instead of retrying —
                    # so error results get an explicit, impossible-to-miss imperative message instead
                    # of a JSON blob.
                    is_tool_error = isinstance(result, dict) and result.get("isError")
                    structured = result.get("structuredContent") if isinstance(result, dict) else None

                    if is_tool_error:
                        error_text = ""
                        if isinstance(result, dict):
                            for block in result.get("content") or []:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    error_text = block.get("text", "")
                                    break
                        result_content = (
                            "QUERY FAILED — this did NOT run successfully and returned NO data. "
                            f"Error from BigQuery: {error_text or 'unknown error'}. "
                            "Do not answer the user's question as if this succeeded or returned "
                            "empty results — that would be fabricating an answer. Re-check the exact "
                            "column names and types listed in your system instructions — the schema "
                            "there is complete and authoritative — fix the query accordingly and "
                            "retry. If you're out of ideas, tell the user what went wrong instead of "
                            "making up numbers."
                        )
                    else:
                        if _is_sql_tool(name) and _looks_like_bq_rows(structured):
                            columns, data, total_rows = _parse_bq_rows(structured)
                            data_rows = data[:500]
                            yield {
                                "type": "rows",
                                "columns": columns,
                                "data": data_rows,
                                "total_rows": total_rows,
                                "truncated": total_rows > len(data_rows),
                                "viz": {"show_table": True, "charts": []},
                            }
                        payload = structured if structured is not None else result
                        result_content = json.dumps(payload, default=str)
                        if len(result_content) > CHATBOT_MAX_TOOL_RESULT_CHARS:
                            result_content = (
                                result_content[:CHATBOT_MAX_TOOL_RESULT_CHARS]
                                + f"... [truncated, {len(result_content)} chars total. "
                                "Narrow the query with a LIMIT or filter and try again.]"
                            )

                messages.extend(messages_with_tool_result(provider, call["id"], name, result_content))

        # --- Round limit exhausted without a final answer -------------------------------
        yield {
            "type": "text",
            "content": "I wasn't able to finish answering that within the allowed number of steps. "
            "Try asking a narrower question.",
        }
        yield _done_event(False, 0.2, tables_used)
    finally:
        await mcp.aclose()


async def run_single_query(
    db,
    user_id: str,
    connection,
    client_id: int | None,
    provider: str,
    model: str,
    api_key: str,
    message: str,
    conversation_history: list[dict] | None,
) -> dict:
    """Non-streaming variant: fully drains stream_single_query. Not currently used by
    router.py (the chatbot is SSE-only per the task's UI requirements) — kept for parity
    with the reference doc / in case a future non-streaming caller needs it."""
    answer_parts: list[str] = []
    sql = None
    confidence = 0.0
    tables_used: list[str] = []
    rows_payload = None

    async for event in stream_single_query(
        db, user_id, connection, client_id, provider, model, api_key, message, conversation_history
    ):
        etype = event.get("type")
        if etype == "sql":
            sql = event.get("content")
        elif etype == "rows":
            rows_payload = {k: v for k, v in event.items() if k != "type"}
        elif etype == "text":
            answer_parts.append(event.get("content") or "")
        elif etype == "done":
            confidence = event.get("confidence", confidence)
            tables_used = event.get("tables_used", tables_used)

    return {
        "answer": "".join(answer_parts),
        "sql": sql,
        "confidence": confidence,
        "tables_used": tables_used,
        "rows": rows_payload,
    }
