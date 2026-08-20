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
from app.modules.chat_bot.config import (
    CHATBOT_ANSWER_ROWS_SAMPLE,
    CHATBOT_LIST_BREAKDOWN_MAX_COLUMNS,
    CHATBOT_LIST_BREAKDOWN_MAX_VALUES,
    CHATBOT_LIST_SUMMARY_MIN_ROWS,
    CHATBOT_MAX_TOOL_RESULT_CHARS,
    CHATBOT_MAX_TOOL_ROUNDS,
    CHATBOT_MCP_ROW_CAP,
    CHATBOT_TOOL_ECHO_ROW_SAMPLE,
)
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

# Belt-and-braces cleanup for the final answer text: query-result.tsx's FormattedAnswerText
# renders exactly "**bold**", "- " bullets, and blank-line paragraph breaks — nothing else — so
# **bold** is intentionally left alone here (the UI now interprets it), but markdown headers
# (#, ##, ...) aren't part of that supported subset and LLMs reliably reach for them anyway
# despite the prompt's instruction not to — live-verified across providers that the instruction
# alone isn't consistently followed. Strips just the header markers, leaving the header text.
_MD_HEADER_RE = re.compile(r"(?m)^#{1,6}[ \t]+")


def _strip_markdown_formatting(text: str) -> str:
    if not text:
        return text
    text = _MD_HEADER_RE.sub("", text)
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


# Coarse, whole-string detection of whether a SQL result is a raw entity list vs an already-
# aggregated result — same regex-based-guardrail style as guardrails.check_join_conditions, not
# a real SQL parser. A query that only uses an aggregate inside a subquery/window function would
# be misclassified as aggregate-shaped, which just means it falls back to the existing row-sample
# narrative path below (a missed optimization, not a correctness bug).
_AGGREGATE_SHAPE_RE = re.compile(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(|\bGROUP\s+BY\b", re.IGNORECASE)


def _is_list_shaped_sql(sql: str) -> bool:
    return not _AGGREGATE_SHAPE_RE.search(sql or "")


def _build_list_aggregate_summary(sql: str, columns: list[str], data: list[dict], total_rows: int) -> str:
    """Builds a compact <QUERY_RESULT> text block for a large list-shaped result: a total-count
    line (plus an honesty caveat when `data` is itself only a slice of `total_rows`, whether from
    our own courtesy caps or a silent cap the MCP tool applies upstream) and a per-column
    value-count breakdown for any column that looks categorical, instead of dumping individual
    rows into the LLM prompt. See config.py's CHATBOT_LIST_SUMMARY_MIN_ROWS/
    CHATBOT_LIST_BREAKDOWN_MAX_COLUMNS/CHATBOT_LIST_BREAKDOWN_MAX_VALUES."""
    lines = [f"SQL executed:\n{sql}", "", f"Total matching rows: {len(data)}"]
    if total_rows > len(data):
        lines.append(
            f"Note: only {len(data)} of {total_rows} total matching rows were available to "
            "summarize — the breakdown below is representative of that sample, not exact for "
            "the full total."
        )

    breakdown_count = 0
    for col in columns:
        if breakdown_count >= CHATBOT_LIST_BREAKDOWN_MAX_COLUMNS:
            break
        counts: dict = {}
        for row in data:
            value = row.get(col)
            counts[value] = counts.get(value, 0) + 1
        distinct_count = len(counts)
        # "Categorical enough to break down": a handful of repeated values, not a near-unique
        # column like an id/email/name (which would have ~len(data) distinct values).
        if not (2 <= distinct_count <= 20) or distinct_count >= len(data):
            continue
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        shown = ranked[:CHATBOT_LIST_BREAKDOWN_MAX_VALUES]
        remainder = len(ranked) - len(shown)
        parts = [f"{value} ({count})" for value, count in shown]
        if remainder > 0:
            parts.append(f"+{remainder} others")
        lines.append(f"Breakdown by {col}: " + ", ".join(parts))
        breakdown_count += 1

    return "\n".join(lines)


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


def _find_date_range(fields: list[dict], data: list[dict]) -> tuple[str, str, str] | None:
    """Picks the first DATE/DATETIME/TIMESTAMP/TIME-typed column in the result (in column
    order) and returns (column_name, min_value, max_value) computed over the actual returned
    rows, or None if no such column exists or every value is missing. Values are already
    normalized to sortable strings by _convert_bq_cell (TIMESTAMP/DATETIME -> "YYYY-MM-DD
    HH:MM:SS UTC"; DATE passes through BigQuery's own "YYYY-MM-DD" string as-is), so plain
    string min/max gives the correct chronological bounds without parsing dates ourselves —
    deliberately not delegated to the LLM (same reasoning as _convert_bq_cell's epoch-seconds
    conversion: the model can't reliably state an exact date from what it's given)."""
    for field in fields:
        name = field.get("name")
        if (field.get("type") or "").upper() not in _DATE_FIELD_TYPES:
            continue
        values = [row.get(name) for row in data if row.get(name)]
        if not values:
            continue
        return name, min(values), max(values)
    return None


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
                # This step's output is just a SQL string passed as a tool-call argument (or,
                # in the out-of-scope branch, a short plain-text refusal) — not free-form
                # prose. Even a query with several CTEs/JOINs rarely runs past a few hundred
                # tokens, so this only needs headroom for an unusually long query, not the
                # 3000 carried over from the reference implementation's answer-writing budget.
                response = await call_llm_with_tools(
                    provider, model, api_key, messages, openai_format_tools, max_tokens=1000, temperature=0.2
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

                bad_join_reason: str | None = None
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
                    # Unlike check_sql_safety above, a bad join is retryable — feed it back to
                    # the model as a tool-error-style message (below) instead of aborting the
                    # whole turn, so it gets a chance to fix the join and try again.
                    bad_join_reason = guardrails.check_join_conditions(sql)
                    for table in _extract_tables_used(sql):
                        if table not in tables_used:
                            tables_used.append(table)
                    yield {"type": "sql", "content": sql, "tables_used": tables_used}
                    yield {"type": "status", "label": "Running query…"}

                if bad_join_reason:
                    # Skip execution entirely — this SQL wasn't run against BigQuery, so
                    # there's no real result to parse. Same imperative-message treatment as a
                    # genuine tool error below, so the model notices and retries rather than
                    # hallucinating a result.
                    result_content = (
                        "QUERY NOT RUN — rejected before execution, no data was returned. "
                        f"{bad_join_reason}"
                    )
                else:
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
                                # The MCP tool's own `totalRows` doesn't reliably report the true
                                # total once `data` itself hits CHATBOT_MCP_ROW_CAP (see config.py) —
                                # so a query matching MORE than the cap can still come back with
                                # total_rows == len(data) == cap, which would make the usual
                                # `total_rows > len(data)` check below miss the truncation entirely.
                                hit_row_cap = len(data) >= CHATBOT_MCP_ROW_CAP
                                truncated = total_rows > len(data_rows) or hit_row_cap
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
                                    # Full set the MCP tool actually returned, before the 500-row
                                    # UI-display slice above — used by _build_list_aggregate_summary
                                    # for an accurate row count/breakdown, not the UI's capped view.
                                    "full_data": data,
                                    "total_rows": total_rows,
                                    "truncated": truncated,
                                    "hit_row_cap": hit_row_cap,
                                    # Only trustworthy when the full matching set was actually
                                    # retrieved — a range computed from a partial/capped result
                                    # would understate true coverage, so this is populated here
                                    # but only used for the final answer when that's the case
                                    # (see the date-range append below).
                                    "date_range": _find_date_range(fields, data),
                                }
                                # Echo a compact, already-parsed sample back to the model instead of
                                # the raw verbose BigQuery REST shape (`{"f":[{"v":...}]}`) — the
                                # model only needs enough to confirm the query worked, not up to 500
                                # raw rows. See config.py's CHATBOT_TOOL_ECHO_ROW_SAMPLE.
                                echo_rows = data_rows[:CHATBOT_TOOL_ECHO_ROW_SAMPLE]
                                payload = {
                                    "columns": columns,
                                    "rows": echo_rows,
                                    "total_rows": total_rows,
                                    "truncated": total_rows > len(echo_rows),
                                }
                            else:
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
        # List-shaped results (raw entities, no COUNT/SUM/AVG/GROUP BY) above the row threshold
        # get a Python-computed aggregate breakdown instead of a row sample — dumping hundreds of
        # `col=val` lines into the prompt for the model to narrate is wasteful and prone to the
        # model just enumerating rows back in prose. Small list results (e.g. "list the
        # subscription tiers" -> 3 rows) and aggregate-shaped results keep the existing row-sample
        # path unchanged. See config.py's CHATBOT_LIST_SUMMARY_MIN_ROWS.
        if (
            _is_list_shaped_sql(successful_result["sql"])
            and successful_result["total_rows"] > CHATBOT_LIST_SUMMARY_MIN_ROWS
        ):
            query_result_block = _build_list_aggregate_summary(
                successful_result["sql"],
                successful_result["columns"],
                successful_result["full_data"],
                successful_result["total_rows"],
            )
        else:
            # Independent, much smaller sample than the up-to-500-row `successful_result["data"]`
            # (that cap is sized for the frontend table/chart, not for formatting into an LLM
            # prompt as text lines). See config.py's CHATBOT_ANSWER_ROWS_SAMPLE.
            answer_sample = successful_result["data"][:CHATBOT_ANSWER_ROWS_SAMPLE]
            query_result_block = prompts.format_query_result_block(
                successful_result["sql"],
                successful_result["columns"],
                answer_sample,
                successful_result["total_rows"],
                successful_result["total_rows"] > len(answer_sample),
            )
        if successful_result.get("hit_row_cap"):
            # Both branches above may have already stated `total_rows` as if it were exact — it
            # isn't, once the MCP tool's own row cap is hit (see the hit_row_cap comment where
            # it's computed). Append this regardless of which branch ran, so the model can't
            # present the capped count as a final total either way.
            query_result_block += (
                f"\n\nNote: this query hit the query tool's per-call cap of {CHATBOT_MCP_ROW_CAP} "
                f"rows — at least {len(successful_result['full_data'])} rows matched, but the true "
                "total could be higher and is not knowable from this result. Say so plainly if you "
                "report a count from this data (e.g. \"at least N\", not a bare total) — do not "
                "state the capped number as if it were the complete total."
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
        # Deterministic, not model-authored — appended after generation rather than asked of the
        # model, same reasoning as the row-cap note above: the model shouldn't be trusted to
        # restate an exact date range itself. Only when the full matching set was actually
        # retrieved (not truncated/capped) — a range from a partial result would understate the
        # data's true coverage, which is worse than omitting the line.
        date_range = successful_result.get("date_range")
        full_data_complete = (
            successful_result["total_rows"] <= len(successful_result["full_data"])
            and not successful_result.get("hit_row_cap")
        )
        if content and date_range and full_data_complete:
            _, min_value, max_value = date_range
            content += f"\n\nThis response is based on data from {min_value} to {max_value}."
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
