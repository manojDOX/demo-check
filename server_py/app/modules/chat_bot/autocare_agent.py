"""Chat engine that answers through the AutoCare MCP server.

The model never writes SQL. It calls MCP tools (mostly `query`, with a JSON spec). The server checks the
spec against its catalog, runs a read-only SELECT, and returns rows with the true `total_rows`. This module
runs the loop: model turn -> tool calls -> results -> model turn ... until the model writes its answer.

Yields the same event dicts as the old SQL engine (sql_agent.py), so service.py and the frontend do not
care which engine answered: `status`, `sql`, `rows`, `text`, `error`, and a final `done` (with `billable`,
`confidence`, `tables_used`). service.py owns `session` and the final `done` with the session id.

McpUnavailable is raised, not turned into an event, when the service fails BEFORE any tool call has
succeeded. That is the signal for service.py to fall back to the old SQL engine. After a first success the
failure becomes an `error` event instead (starting over on another engine would only confuse the user).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator

from app.modules.chat_bot import autocare_client, autocare_prompt
from app.modules.chat_bot.answer_utils import (
    CUSTOMER_LEVEL_ACTIVE_NOTE,
    build_partial_list_note,
    display_value,
    infer_charts,
    infer_fields,
    strip_markdown_formatting,
)
from app.modules.chat_bot.autocare_client import AutoCareClient, McpToolError, McpUnavailable
from app.modules.chat_bot.autocare_drill import DrillContext, build_drill_block, check_drill_call
from app.modules.chat_bot.autocare_explain import explain_profile, explain_query
from app.modules.chat_bot.config import (
    AUTOCARE_MAX_RESULT_CHARS,
    AUTOCARE_MAX_ROWS_TO_MODEL,
    AUTOCARE_MAX_TOKENS,
    AUTOCARE_MAX_TOOL_ROUNDS,
    AUTOCARE_ROW_LIMIT,
)
from app.modules.chat_bot.llm_client import (
    call_llm_with_tools,
    mcp_tools_to_openai_format,
    messages_with_tool_result,
)

logger = logging.getLogger(__name__)

ENGINE_NAME = "autocare_mcp"

# Tools shown to the model. `query` does the work of the five per-view tools (the view goes inside the
# spec), so those are hidden: their schemas are about 11,000 characters each and would be sent on every
# model turn. compile_query / refresh_schema are admin tools; list_views / glossary repeat what the server
# instructions already say.
EXPOSED_TOOLS = (
    "query",
    "customer_profile",
    "churn_rate",
    "engagement_quintiles",
    "upsell_uplift",
    "data_overview",
    "distinct_values",
    "describe_view",
)
ADMIN_TOOLS = {"compile_query", "refresh_schema"}
# Providers that cannot read JSON Schema `$ref` / recursive definitions (the `query` schema uses both).
FLAT_SCHEMA_PROVIDERS = {"gemini"}

_LENGTH_FINISH_REASONS = {"length", "max_tokens", "MAX_TOKENS"}
_EMPTY_RESPONSE_NUDGE = (
    "Your previous reply was empty: no text and no tool call. Call a tool, or answer in plain text."
)
_STATUS_LABELS = ["Thinking…", "Looking up your data…", "Analyzing your question…"]

# customer_profile returns every customer column; the table shows only the useful ones.
_PROFILE_COLUMNS = (
    "full_name",
    "email",
    "phone_number",
    "customer_status",
    "tier_name",
    "current_subscription_status",
    "current_period_end",
    "customer_created_date",
    "last_session_date",
    "total_sessions",
    "has_active_subscription",
)
# A filter on one of these means "one specific customer", not a customer-level count.
_SINGLE_CUSTOMER_COLUMNS = {"email", "phone_number", "client_id", "stripe_customer_id"}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def select_tools(catalog_tools: list[dict]) -> list[dict]:
    chosen = [tool for tool in catalog_tools if tool.get("name") in EXPOSED_TOOLS]
    if any(tool.get("name") == "query" for tool in chosen):
        return chosen
    # The server changed and has no `query` tool: expose everything except the admin tools.
    return [tool for tool in catalog_tools if tool.get("name") not in ADMIN_TOOLS]


def flatten_schema(schema: dict) -> dict:
    """Plain top-level object schema: no `$ref`, no `$defs`, no `anyOf`. The server instructions already
    describe the spec, and the server validates it, so the model loses nothing it needs."""
    properties = {}
    for name, prop in (schema.get("properties") or {}).items():
        prop = prop if isinstance(prop, dict) else {}
        kind = prop.get("type")
        if kind not in ("string", "number", "integer", "boolean", "array", "object"):
            kind = "object"
        flat: dict = {"type": kind}
        description = prop.get("description") or ("The query spec. See the instructions." if name == "spec" else "")
        if description:
            flat["description"] = description
        if prop.get("enum"):
            flat["enum"] = prop["enum"]
        if kind == "array":
            flat["items"] = {"type": "string"}
        properties[name] = flat
    flat_schema: dict = {"type": "object", "properties": properties}
    if schema.get("required"):
        flat_schema["required"] = list(schema["required"])
    return flat_schema


def adapt_tools(tools: list[dict], provider: str) -> list[dict]:
    if (provider or "").strip().lower() not in FLAT_SCHEMA_PROVIDERS:
        return tools
    adapted = []
    for tool in tools:
        schema = tool.get("inputSchema") or {}
        if "$defs" in schema or "$ref" in json.dumps(schema):
            tool = {**tool, "inputSchema": flatten_schema(schema)}
        adapted.append(tool)
    return adapted


# ---------------------------------------------------------------------------
# Arguments and results
# ---------------------------------------------------------------------------


def apply_row_limit(name: str, arguments: dict) -> dict:
    """A list question (a `query` spec without `metrics`) returns at most AUTOCARE_ROW_LIMIT rows: the
    default when the model sets no `limit`, and the cap when it sets a larger one. `total_rows` in the
    result still gives the true size of the answer."""
    spec = arguments.get("spec")
    if name != "query" or not isinstance(spec, dict) or spec.get("metrics"):
        return arguments
    limit = spec.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and 0 < limit <= AUTOCARE_ROW_LIMIT:
        return arguments
    return {**arguments, "spec": {**spec, "limit": AUTOCARE_ROW_LIMIT}}


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_sql_literal(item) for item in value) + "]"
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return "'" + text + "'"


def inline_sql_params(sql: str, params: dict | None) -> str:
    """The server returns SQL with @p0, @p1 ... parameters. Putting the values into the text gives SQL
    that runs on its own: "View SQL" shows it, and Crear Segmento stores it and re-runs it later."""
    for name in sorted(params or {}, key=len, reverse=True):
        sql = re.sub(r"@" + re.escape(name) + r"\b", lambda _match, v=params[name]: _sql_literal(v), sql)
    return sql


def shrink_for_model(result: dict) -> str:
    """What the model sees of a result: no sql/params, a sample of the rows, a size limit."""
    payload = {key: value for key, value in result.items() if key not in ("sql", "params", "bytes_processed")}
    rows = payload.get("rows")
    if isinstance(rows, list) and len(rows) > AUTOCARE_MAX_ROWS_TO_MODEL:
        payload["rows"] = rows[:AUTOCARE_MAX_ROWS_TO_MODEL]
        payload["rows_note"] = f"first {AUTOCARE_MAX_ROWS_TO_MODEL} of {payload.get('total_rows', len(rows))} rows"
    text = json.dumps(payload, default=str, ensure_ascii=False)
    if len(text) > AUTOCARE_MAX_RESULT_CHARS:
        text = text[:AUTOCARE_MAX_RESULT_CHARS] + "... [truncated]"
    return text


class _Outcome:
    """The last result that produced a table. Its numbers drive the fixed notes."""

    def __init__(self, view: str | None, spec: dict | None, total_rows: int, shown_rows: int):
        self.view = view
        self.spec = spec
        self.total_rows = total_rows
        self.shown_rows = shown_rows


def build_table_events(name: str, arguments: dict, result: dict) -> tuple[list[dict], _Outcome | None]:
    """UI events for a result: `sql` (View SQL) and `rows` (table + chart). Only `query` and
    `customer_profile` produce a table; the other tools give nested figures the answer text covers."""
    if name == "query":
        rows = result.get("rows") if isinstance(result.get("rows"), list) else []
        columns = list(result.get("columns") or (rows[0].keys() if rows else []))
        shown = [{column: display_value(row.get(column)) for column in columns} for row in rows[:AUTOCARE_ROW_LIMIT]]
        view = result.get("view")
        spec = arguments.get("spec") if isinstance(arguments.get("spec"), dict) else None
        total_rows = result.get("total_rows")
        total_rows = total_rows if isinstance(total_rows, int) and total_rows >= len(shown) else len(shown)
        events: list[dict] = []
        if result.get("sql"):
            events.append(
                {
                    "type": "sql",
                    "content": inline_sql_params(result["sql"], result.get("params")),
                    "tables_used": [view] if view else [],
                }
            )
        events.append(
            {
                "type": "rows",
                "columns": columns,
                "data": shown,
                "total_rows": total_rows,
                "truncated": total_rows > len(shown),
                "viz": {"show_table": True, "charts": infer_charts(infer_fields(columns, shown), shown)},
                # What the browser sends back to drill into this result.
                "spec": {"tool": "query", "view": view, "spec": spec} if spec is not None else None,
                # Plain-words "How it was calculated" lines, built from the spec by code.
                "explain": explain_query(view, spec, total_rows, len(shown)),
                "engine": ENGINE_NAME,
            }
        )
        return events, _Outcome(view, spec, total_rows, len(shown))

    if name == "customer_profile":
        customers = [row for row in (result.get("customers") or []) if isinstance(row, dict)]
        if not customers:
            return [], None
        columns = [c for c in _PROFILE_COLUMNS if any(c in row for row in customers)] or list(customers[0])[:12]
        shown = [{column: display_value(row.get(column)) for column in columns} for row in customers]
        event = {
            "type": "rows",
            "columns": columns,
            "data": shown,
            "total_rows": len(shown),
            "truncated": False,
            "viz": {"show_table": True, "charts": []},
            "spec": None,
            "explain": explain_profile(len(shown)),
            "engine": ENGINE_NAME,
        }
        return [event],_Outcome("customer_360_vw", None, len(shown), len(shown))

    return [], None


def is_customer_level_active_spec(view: str | None, spec: dict | None) -> bool:
    """True for a customer_360_vw query that FILTERS on has_active_subscription being true: a count or list
    of customers with an active subscription. A lookup of one customer (email, phone, id) does not count."""
    if view != "customer_360_vw" or not isinstance(spec, dict):
        return False
    filters = [item for item in (spec.get("filters") or []) if isinstance(item, dict)]
    if any(item.get("column") in _SINGLE_CUSTOMER_COLUMNS for item in filters):
        return False
    for item in filters:
        if item.get("column") != "has_active_subscription":
            continue
        if item.get("op") == "is_true" or (item.get("op") == "eq" and item.get("value") in (True, "true", 1)):
            return True
    return False


def _compose_answer(answer: str, outcome: _Outcome | None) -> str:
    notes: list[str] = []
    if outcome is not None:
        if is_customer_level_active_spec(outcome.view, outcome.spec):
            notes.append(CUSTOMER_LEVEL_ACTIVE_NOTE)
        if outcome.total_rows > outcome.shown_rows:
            notes.append(build_partial_list_note(outcome.shown_rows, outcome.total_rows, True, None))
    return "\n\n".join([answer, *notes])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _done_event(billable: bool, confidence: float, tables_used: list[str]) -> dict:
    return {"type": "done", "billable": billable, "confidence": confidence, "tables_used": tables_used}


async def stream_autocare_query(
    *,
    provider: str,
    model: str,
    api_key: str,
    message: str,
    conversation_history: list[dict] | None = None,
    drill: DrillContext | None = None,
    client: AutoCareClient | None = None,
) -> AsyncGenerator[dict, None]:
    mcp = client if client is not None else AutoCareClient()  # may raise McpUnavailable (no key)
    try:
        yield {"type": "status", "label": "Connecting to the analytics service…"}
        instructions, catalog_tools = await autocare_client.load_catalog(mcp)  # may raise McpUnavailable
        tools = select_tools(catalog_tools)
        exposed_names = {tool["name"] for tool in tools}
        llm_tools = mcp_tools_to_openai_format(adapt_tools(tools, provider))

        system_prompt = autocare_prompt.build_system_prompt(
            instructions, build_drill_block(drill) if drill is not None else ""
        )
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for turn in conversation_history or []:
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})

        tables_used: list[str] = []
        outcome: _Outcome | None = None
        had_success = False
        retried_empty = False
        max_tokens = AUTOCARE_MAX_TOKENS

        for round_index in range(AUTOCARE_MAX_TOOL_ROUNDS):
            yield {"type": "status", "label": _STATUS_LABELS[min(round_index, len(_STATUS_LABELS) - 1)]}
            try:
                response = await call_llm_with_tools(
                    provider, model, api_key, messages, llm_tools, max_tokens=max_tokens, temperature=0
                )
            except Exception as error:
                yield {"type": "error", "content": f"Couldn't get a response from the model: {error}"}
                yield _done_event(False, 0.0, tables_used)
                return

            tool_calls = response.get("tool_calls")
            content = (response.get("content") or "").strip()

            if not tool_calls and not content:
                # No text and no tool call is a provider-side failure (a malformed call, or the output
                # budget used up by reasoning), not a considered answer. Retry once.
                logger.warning(
                    "Model returned an empty response (provider=%s, model=%s, finish_reason=%s, round=%d)",
                    provider,
                    model,
                    response.get("finish_reason"),
                    round_index,
                )
                if not retried_empty:
                    retried_empty = True
                    if response.get("finish_reason") in _LENGTH_FINISH_REASONS:
                        max_tokens *= 2
                    messages.append({"role": "user", "content": _EMPTY_RESPONSE_NUDGE})
                    continue
                yield {
                    "type": "text",
                    "content": "The AI model returned an empty response, so I couldn't answer that. "
                    "Please try rephrasing the question.",
                }
                yield _done_event(False, 0.2, tables_used)
                return

            messages.append(response["raw_message"])

            if not tool_calls:
                answer = strip_markdown_formatting(content) or "I found the data but couldn't put together an answer."
                yield {"type": "text", "content": _compose_answer(answer, outcome)}
                yield _done_event(True, 0.9 if had_success else 0.8, tables_used)
                return

            for call in tool_calls:
                name = call["name"]
                arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                yield {"type": "status", "label": "Looking up your data…"}

                problem = None
                if name not in exposed_names:
                    problem = f"Unknown tool: '{name}'. Use one of: {', '.join(sorted(exposed_names))}."
                elif drill is not None:
                    problem = check_drill_call(drill, name, arguments)

                if problem is not None:
                    tool_text = f"ERROR: {problem}"
                else:
                    arguments = apply_row_limit(name, arguments)
                    try:
                        result = await mcp.call_tool(name, arguments)
                    except McpToolError as error:
                        tool_text = f"ERROR: {error}"
                    except McpUnavailable as error:
                        if not had_success:
                            raise
                        logger.warning("AutoCare MCP failed after a first result: %s", error)
                        yield {
                            "type": "error",
                            "content": "The analytics service stopped responding. Please try again in a moment.",
                        }
                        yield _done_event(False, 0.2, tables_used)
                        return
                    else:
                        had_success = True
                        table_events, table_outcome = build_table_events(name, arguments, result)
                        for event in table_events:
                            yield event
                        if table_outcome is not None:
                            outcome = table_outcome
                            if table_outcome.view and table_outcome.view not in tables_used:
                                tables_used.append(table_outcome.view)
                        tool_text = shrink_for_model(result)

                messages.extend(messages_with_tool_result(provider, call["id"], name, tool_text))

        yield {
            "type": "text",
            "content": "I wasn't able to finish answering that within the allowed number of steps. "
            "Try asking a narrower question.",
        }
        yield _done_event(False, 0.2, tables_used)
    finally:
        if client is None:
            await mcp.aclose()
