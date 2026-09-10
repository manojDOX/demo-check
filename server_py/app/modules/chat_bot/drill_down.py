"""Segment drill-down: answering the next question only within a previous step's result.

The model never retypes the previous step's SQL. It writes a query against a placeholder table
named `previous_segment`, and compose_drill_sql splices the real SQL in as a subquery before
guardrails/execution. Drill steps aren't persisted, so the browser carries each step's SQL between
requests; sign_sql/verify_sql ensure what comes back is SQL this server actually ran, for this user
and this connection.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field

from app.config import get_settings

_TOKEN_CONTEXT = "drill-sql-v1"
MAX_CHAIN_DEPTH = 10
_MAX_COLUMNS = 200
_MAX_QUESTION_CHARS = 300
_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CONTACT_COLUMNS = ("full_name", "first_name", "last_name", "customer_name", "email", "phone_number")

_ALIAS_STOP_WORDS = (
    "WHERE|JOIN|INNER|LEFT|RIGHT|FULL|OUTER|CROSS|NATURAL|ON|USING|GROUP|ORDER|LIMIT|QUALIFY|"
    "HAVING|WINDOW|UNION|EXCEPT|INTERSECT|SELECT|TABLESAMPLE|FOR"
)
# `FROM|JOIN previous_segment [[AS] alias]`, optionally backtick-quoted. Qualified column refs
# (`previous_segment.client_id`) aren't table references and are deliberately not matched.
_SEGMENT_REF_RE = re.compile(
    r"\b(FROM|JOIN)\s+`?previous_segment`?(?![\w.])"
    rf"(?:\s+(?:AS\s+)?(?!(?:{_ALIAS_STOP_WORDS})\b)([A-Za-z_]\w*))?",
    re.IGNORECASE,
)

MISSING_SEGMENT_REASON = (
    "This is a drill-down step, but the query doesn't select FROM previous_segment. It must narrow "
    "the user's current segment: select FROM previous_segment (JOINing other views on "
    "previous_segment.client_id if needed) instead of querying the base tables from scratch. "
    "Rewrite it and retry."
)


@dataclass(frozen=True)
class DrillStep:
    question: str
    row_count: int | None


@dataclass
class DrillContext:
    base_sql: str
    base_columns: list[str] = field(default_factory=list)
    chain: list[DrillStep] = field(default_factory=list)


def _digest(user_id: str, connection_id: int, sql: str) -> str:
    key = get_settings().SESSION_SECRET.encode()
    message = "\x00".join((_TOKEN_CONTEXT, str(user_id), str(connection_id), sql)).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def sign_sql(user_id: str, connection_id: int, sql: str) -> str:
    return _digest(user_id, connection_id, sql)


def verify_sql(user_id: str, connection_id: int | None, sql: str | None, token: str | None) -> bool:
    if connection_id is None or not sql or not token:
        return False
    return hmac.compare_digest(_digest(user_id, connection_id, sql), token)


def references_previous_segment(sql: str | None) -> bool:
    return bool(sql) and _SEGMENT_REF_RE.search(sql) is not None


def compose_drill_sql(model_sql: str, base_sql: str) -> str:
    base = base_sql.strip().rstrip(";").strip()

    def _substitute(match: re.Match) -> str:
        alias = match.group(2) or "previous_segment"
        return f"{match.group(1)} (\n{base}\n) AS {alias}"

    # Function replacement (not a template string) so backslashes in the base SQL stay literal.
    return _SEGMENT_REF_RE.sub(_substitute, model_sql)


def sanitize_columns(columns: list | None) -> list[str]:
    cleaned: list[str] = []
    for column in columns or []:
        if isinstance(column, str) and _COLUMN_RE.match(column) and column not in cleaned:
            cleaned.append(column)
            if len(cleaned) >= _MAX_COLUMNS:
                break
    return cleaned


def sanitize_chain(chain: list | None) -> list[DrillStep]:
    steps: list[DrillStep] = []
    for item in (chain or [])[-MAX_CHAIN_DEPTH:]:
        if not isinstance(item, dict):
            continue
        question = " ".join(str(item.get("question") or "").split())[:_MAX_QUESTION_CHARS]
        row_count = item.get("row_count")
        if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
            row_count = None
        if question:
            steps.append(DrillStep(question=question, row_count=row_count))
    return steps


def build_prompt_block(context: DrillContext) -> str:
    lines = [
        "",
        "<DRILL_DOWN>",
        "The user is narrowing an existing customer segment one step at a time; <USER_PROMPT> is the "
        "next narrowing step. Steps so far, oldest first:",
    ]
    for index, step in enumerate(context.chain, start=1):
        size = f" -> {step.row_count} rows" if step.row_count is not None else ""
        lines.append(f"{index}. {json.dumps(step.question)}{size}")

    if context.base_columns:
        columns = ", ".join(context.base_columns)
        contact = [column for column in CONTACT_COLUMNS if column in context.base_columns]
    else:
        columns = "client_id (other columns unknown)"
        contact = []
    keep = ", ".join(["client_id", *contact])

    lines += [
        f"The current segment is available as a table named previous_segment with these columns: {columns}.",
        "",
        "For THIS question you MUST:",
        "- Select FROM previous_segment (an alias is fine, e.g. FROM previous_segment ps). Reference it "
        "only by that bare name: never backtick-quote it, never prefix it with a dataset, and never "
        "re-derive the logic that produced it. The application substitutes the real segment in automatically.",
        "- Only return customers that are in previous_segment. If the question needs an attribute "
        "previous_segment doesn't have (e.g. tier_name, last_session_date, a location), JOIN the relevant "
        "view(s) from <SQL_SCHEMA> on previous_segment.client_id (per JOINING ACROSS TABLES), or filter with "
        "previous_segment.client_id IN (SELECT client_id FROM ...). One-to-many views (sessions, "
        "subscriptions) would duplicate customers in a plain JOIN, so prefer IN/EXISTS or SELECT DISTINCT "
        "so each customer appears once.",
        f"- Return one row per customer and always include these previous_segment columns: {keep}, so "
        "the result can be narrowed again or exported.",
        "- Return a count or breakdown instead of the customer list only if the user explicitly asks for "
        "one (e.g. \"how many of these...\").",
        "- Read \"these\", \"those\", and \"them\" as the customers in previous_segment.",
        "</DRILL_DOWN>",
    ]
    return "\n".join(lines) + "\n"


def build_answer_note(context: DrillContext) -> str:
    if not context.chain:
        return ""
    previous = context.chain[-1]
    size = f" ({previous.row_count} rows)" if previous.row_count is not None else ""
    return (
        "\n\nDrill-down context: this result was computed only within the user's previous segment, "
        f"{json.dumps(previous.question)}{size}. Describe it relative to that segment (e.g. \"N of those "
        "customers ...\"), not as a result over the whole customer base."
    )
