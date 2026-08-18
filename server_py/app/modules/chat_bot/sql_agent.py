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

Two-stage pipeline (see prompts.py): stage 1's tool-calling loop below only ever writes and
executes SQL (prompts.build_sql_generation_system_prompt, no schema-lookup tools offered).
The moment a SQL tool call returns real rows, the loop breaks and hands off to stage 2 — a
SEPARATE, tools-free LLM call (prompts.build_answer_generation_system_prompt) that turns
those rows into the final analyst-voice text. Stage 1 never produces the user-facing answer
itself except in the "no data needed / out of scope" case, where it answers directly without
ever calling a tool.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

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

# Belt-and-braces cleanup for the final answer text: the chat UI renders it as plain text
# (no markdown parser — see query-result.tsx's `<p>{summary}</p>`), but LLMs reliably reach
# for **bold**/markdown syntax regardless of the prompt's "PLAIN TEXT ONLY" instruction —
# live-verified across providers that the instruction alone isn't consistently followed.
# Strips just the bold markers (the specific defect actually observed: literal "**Name**"
# reaching the screen) — deliberately NOT touching single "_"/"*" since those appear inside
# real content here (e.g. email addresses like "c_navedo@icloud.com").
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_HEADER_RE = re.compile(r"(?m)^#{1,6}[ \t]+")


def _strip_markdown_formatting(text: str) -> str:
    if not text:
        return text
    text = _MD_HEADER_RE.sub("", text)
    text = _MD_BOLD_RE.sub(lambda m: m.group(1) or m.group(2) or "", text)
    return text


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


_TIMESTAMP_FIELD_TYPES = {"TIMESTAMP", "DATETIME"}


def _convert_bq_cell(value, field_type: str):
    """BigQuery's legacy tabledata REST shape returns TIMESTAMP/DATETIME columns as a
    string of raw Unix epoch seconds (e.g. "1785966448.226") — live-verified against the
    real hosted MCP server. That's meaningless to show a user, and the LLM cannot reliably
    convert it to a calendar date itself (verified: it was guessing plausible-looking but
    wrong dates instead). Converted here, once, into a plain "YYYY-MM-DD HH:MM:SS UTC"
    string so both the LLM's tool-result view and the frontend's rows/table/chart display
    see a real date instead of a raw epoch number."""
    if field_type in _TIMESTAMP_FIELD_TYPES and isinstance(value, str) and value:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        except (TypeError, ValueError, OverflowError, OSError):
            return value
    return value


def _parse_bq_rows(structured: dict) -> tuple[list[str], list[dict], int]:
    """Parses the BigQuery legacy-REST tabledata shape returned in an
    execute_sql(_readonly) tool result's `structuredContent`:
        {"schema": {"fields": [{"name","type","mode"}, ...]},
         "rows": [{"f": [{"v": ...}, ...]}, ...], ...}
    into (columns, [{col: value, ...}, ...], total_row_count). TIMESTAMP/DATETIME values
    are converted from raw epoch seconds to a readable date string along the way."""
    schema = structured.get("schema") or {}
    fields = schema.get("fields") or []
    columns = [f.get("name") for f in fields]
    field_types = [(f.get("type") or "").upper() for f in fields]
    raw_rows = structured.get("rows") or []
    data: list[dict] = []
    for row in raw_rows:
        cells = row.get("f") or []
        record = {}
        for name, ftype, cell in zip(columns, field_types, cells):
            value = cell.get("v") if isinstance(cell, dict) else cell
            record[name] = _convert_bq_cell(value, ftype)
        data.append(record)
    total_rows = structured.get("totalRows")
    try:
        total_rows = int(total_rows) if total_rows is not None else len(data)
    except (TypeError, ValueError):
        total_rows = len(data)
    return columns, data, total_rows


def _looks_like_bq_rows(structured) -> bool:
    return isinstance(structured, dict) and ("schema" in structured or "rows" in structured)


_DATE_FIELD_TYPES = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}
_NUMERIC_FIELD_TYPES = {"INT64", "INTEGER", "FLOAT64", "FLOAT", "NUMERIC", "BIGNUMERIC"}


def _humanize_column(name: str) -> str:
    return name.replace("_", " ").strip().title()


def _infer_charts(fields: list[dict], data: list[dict]) -> list[dict]:
    """Heuristic chart suggestion straight from the BigQuery result schema — no extra LLM
    round trip needed. A date/time-typed column becomes a line-chart x-axis (trend over
    time); any other non-numeric column becomes a bar-chart x-axis (category breakdown).
    Deliberately returns [] (table-only) when there's nothing meaningful to plot: a single
    scalar-result row (e.g. "how many customers do we have"), or no numeric column to use
    as a y-axis at all (e.g. a plain SELECT DISTINCT listing)."""
    if len(data) < 2:
        return []
    field_types = {f.get("name"): (f.get("type") or "").upper() for f in fields}
    numeric_cols = [c for c, t in field_types.items() if t in _NUMERIC_FIELD_TYPES]
    if not numeric_cols:
        return []
    date_cols = [c for c, t in field_types.items() if t in _DATE_FIELD_TYPES]
    x_field = date_cols[0] if date_cols else next(
        (c for c in field_types if c not in numeric_cols), None
    )
    if x_field is None:
        return []
    y_field = next((c for c in numeric_cols if c != x_field), None)
    if y_field is None:
        return []
    chart_type = "line" if date_cols else "bar"
    return [
        {
            "type": chart_type,
            "title": f"{_humanize_column(y_field)} by {_humanize_column(x_field)}",
            "x_field": x_field,
            "y_field": y_field,
            "x_label": _humanize_column(x_field),
            "y_label": _humanize_column(y_field),
        }
    ]


def _done_event(billable: bool, confidence: float, tables_used: list[str]) -> dict:
    return {"type": "done", "billable": billable, "confidence": confidence, "tables_used": tables_used}


def _sql_only_tools(mcp_tools: list[dict]) -> list[dict]:
    """Strips schema/discovery tools (list_dataset_ids, get_table_info, ...) out of what's
    offered to the model. Safe only because this deployment's schema is static and baked
    into the system prompt built by prompts.build_sql_generation_system_prompt() — the model
    never needs to look anything up.
    Falls back to the full tool list if, for some reason, no SQL-execution tool is found
    (e.g. the hosted MCP server renames its tools), so the agent degrades gracefully
    instead of being left with zero usable tools."""
    filtered = [t for t in mcp_tools if _is_sql_tool(t.get("name", ""))]
    return filtered or mcp_tools


def _build_initial_messages(conversation_history: list[dict] | None, message: str) -> list[dict]:
    messages: list[dict] = [
        {"role": "system", "content": prompts.build_sql_generation_system_prompt(message)}
    ]
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
        # Set the moment a SQL tool call comes back with real rows — once this is populated
        # the round loop below breaks out and hands off to a SEPARATE answer-generation call
        # (prompts.build_answer_generation_system_prompt) instead of letting the SAME
        # tool-calling conversation produce the final text itself. Stays None through
        # tool-call errors/retries, so those still loop normally within step 1.
        successful_result: dict | None = None

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
                content = _strip_markdown_formatting((response.get("content") or "").strip())
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
                            truncated = total_rows > len(data_rows)
                            fields = ((structured.get("schema") or {}).get("fields") or [])
                            yield {
                                "type": "rows",
                                "columns": columns,
                                "data": data_rows,
                                "total_rows": total_rows,
                                "truncated": truncated,
                                "viz": {
                                    "show_table": True,
                                    "charts": _infer_charts(fields, data_rows),
                                },
                            }
                            successful_result = {
                                "sql": sql,
                                "columns": columns,
                                "data": data_rows,
                                "total_rows": total_rows,
                                "truncated": truncated,
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

            if successful_result is not None:
                break
        else:
            # --- Round limit exhausted without ever getting a successful query result ---
            yield {
                "type": "text",
                "content": "I wasn't able to finish answering that within the allowed number of steps. "
                "Try asking a narrower question.",
            }
            yield _done_event(False, 0.2, tables_used)
            return

        # --- Step 2: hand the successful query result to a SEPARATE answer-generation call,
        # rather than letting the step-1 tool-calling conversation produce the final text
        # itself. No tools offered here — this call only turns already-fetched rows into an
        # analyst-voice answer, it never queries anything itself. -----------------------
        yield {"type": "status", "label": "Writing your answer…"}
        query_result_block = prompts.format_query_result_block(
            successful_result["sql"],
            successful_result["columns"],
            successful_result["data"],
            successful_result["total_rows"],
            successful_result["truncated"],
        )
        answer_messages = [
            {"role": "system", "content": prompts.build_answer_generation_system_prompt(message, query_result_block)},
            {"role": "user", "content": message},
        ]
        try:
            answer_response = await call_llm_with_tools(
                provider, model, api_key, answer_messages, [], max_tokens=1500, temperature=0.3
            )
        except Exception as error:
            yield {"type": "error", "content": f"Couldn't get a response from the model: {error}"}
            yield _done_event(False, 0.0, tables_used)
            return

        content = _strip_markdown_formatting((answer_response.get("content") or "").strip())
        if content:
            yield {"type": "text", "content": content}
        else:
            yield {"type": "text", "content": "I found the data but couldn't put together an answer for it."}
        yield _done_event(True, 0.9 if content else 0.2, tables_used)
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
