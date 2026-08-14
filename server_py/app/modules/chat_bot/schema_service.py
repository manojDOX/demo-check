"""BigQuery schema listing (process-local cached), LLM-based + keyword-fallback table
selection, table classification/platform grouping, and schema-context string builders.

Adapted from CHATBOT_ARCHITECTURE.md §5 step 1/2 + §7 (TABLE_SELECTION_PROMPT /
TABLE_CLASSIFICATION_PROMPT). Adaptation #2: XIOMARA connections may have
`dataset_id=None` (discover across ALL datasets in the project) — BigQueryService's
`discover_schema`/`discover_schema_via_sql` already handle that; this module just needs
to build per-table schema context across however many datasets came back, instead of
assuming one fixed dataset name.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.modules.chat_bot import prompts
from app.modules.chat_bot.config import CHATBOT_CLASSIFY_CACHE_TTL_SECONDS, CHATBOT_SCHEMA_CACHE_TTL_SECONDS
from app.modules.chat_bot.llm_client import call_llm, parse_llm_json
from app.modules.connections.bigquery_service import BigQueryService, SchemaColumn


@dataclass
class TableInfo:
    key: str  # "dataset.table" — unique within a connection, used for selection matching
    project_id: str
    dataset_id: str
    table_name: str
    full_name: str  # "project.dataset.table"
    columns: list[SchemaColumn] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Process-local TTL caches (per CHATBOT_ARCHITECTURE.md §11 — in-memory, not Redis)
# ---------------------------------------------------------------------------

_schema_cache: dict[int, tuple[float, list[TableInfo]]] = {}
_classify_cache: dict[str, tuple[float, dict]] = {}


async def get_connection_tables(bq: BigQueryService, connection_id: int, force_refresh: bool = False) -> list[TableInfo]:
    """`get_agency_tables`-equivalent, renamed for XIOMARA's connection-scoped tenancy.

    Cache key is just the connection id (one process-local cache entry per BigQuery
    connection, TTL CHATBOT_SCHEMA_CACHE_TTL_SECONDS).
    """
    now = time.time()
    if not force_refresh:
        cached = _schema_cache.get(connection_id)
        if cached and cached[0] > now:
            return cached[1]

    try:
        columns = await bq.discover_schema(None)
    except Exception:
        columns = []
    if not columns:
        columns = await bq.discover_schema_via_sql(None)

    table_map: dict[str, TableInfo] = {}
    for col in columns:
        key = f"{col.dataset_name}.{col.table_name}"
        info = table_map.get(key)
        if info is None:
            info = TableInfo(
                key=key,
                project_id=bq.project_id,
                dataset_id=col.dataset_name,
                table_name=col.table_name,
                full_name=f"{bq.project_id}.{col.dataset_name}.{col.table_name}",
            )
            table_map[key] = info
        info.columns.append(col)

    tables = list(table_map.values())
    _schema_cache[connection_id] = (now + CHATBOT_SCHEMA_CACHE_TTL_SECONDS, tables)
    return tables


# ---------------------------------------------------------------------------
# Schema-context string builders
# ---------------------------------------------------------------------------


def build_schema_context(tables: list[TableInfo]) -> str:
    parts: list[str] = []
    for table in tables:
        parts.append(f"Table: {table.full_name}")
        parts.append(f"  Full reference: `{table.full_name}`")
        parts.append("  Columns:")
        for col in table.columns:
            nullable = "nullable" if col.is_nullable else "required"
            desc = f" - {col.description}" if col.description else ""
            parts.append(f"    - {col.column_name} ({col.data_type}, {nullable}){desc}")
        parts.append("")
    return "\n".join(parts)


def build_schema_context_with_dates(tables: list[TableInfo]) -> str:
    """Same as build_schema_context but grounded with today's date, so the LLM can
    correctly resolve relative date phrases ("last 30 days", "this quarter") against
    actual wall-clock time rather than guessing from its training cutoff."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"Current date (UTC): {today}\n\n{build_schema_context(tables)}"


# ---------------------------------------------------------------------------
# Conversation-history formatting (shared by table selection + SQL generation prompts)
# ---------------------------------------------------------------------------


def format_history(history: list[dict] | None, limit: int = 6) -> str:
    if not history:
        return "(no prior conversation)"
    recent = history[-limit:]
    lines = []
    for turn in recent:
        role = "User" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {turn.get('content', '')}")
    return "\n".join(lines) if lines else "(no prior conversation)"


# ---------------------------------------------------------------------------
# Table selection
# ---------------------------------------------------------------------------


def _table_lookup(tables: list[TableInfo]) -> dict[str, TableInfo]:
    lookup: dict[str, TableInfo] = {}
    for table in tables:
        lookup[table.key] = table
        lookup[table.full_name] = table
        lookup[table.table_name] = table
    return lookup


async def select_relevant_tables_with_llm(
    tables: list[TableInfo],
    question: str,
    history: list[dict] | None,
    provider: str,
    model: str,
    api_key: str,
) -> tuple[list[TableInfo], bool]:
    """Returns (selected_tables, platform_not_found)."""
    prompt = prompts.TABLE_SELECTION_PROMPT.format(
        recent_conversation=format_history(history),
        question=question,
        tables_summary=build_schema_context(tables),
    )
    text = await call_llm(
        provider, model, api_key, [{"role": "user", "content": prompt}], max_tokens=800, temperature=0.0
    )
    data = parse_llm_json(text)
    platform_not_found = bool(data.get("platform_not_found"))
    if platform_not_found:
        return [], True

    lookup = _table_lookup(tables)
    selected: list[TableInfo] = []
    seen: set[str] = set()
    for raw_id in data.get("selected_tables") or []:
        table = lookup.get(raw_id)
        if table is not None and table.key not in seen:
            selected.append(table)
            seen.add(table.key)
    return selected, False


def select_relevant_tables_keyword(tables: list[TableInfo], question: str) -> list[TableInfo]:
    """Pure keyword-scoring fallback, no LLM. Deliberately has no platform awareness —
    per CHATBOT_ARCHITECTURE.md §5 step 2, this must NEVER be used when the LLM already
    determined a named platform isn't connected (platform_not_found)."""
    q_lower = question.lower()
    words = {w for w in re.findall(r"[a-z0-9_]+", q_lower) if len(w) > 2}

    scored: list[tuple[int, TableInfo]] = []
    for table in tables:
        score = 0
        name_lower = table.table_name.lower()
        if name_lower in q_lower:
            score += 5
        for word in words:
            if word in name_lower:
                score += 2
        column_blob = " ".join(col.column_name.lower() for col in table.columns)
        for word in words:
            if len(word) > 3 and word in column_blob:
                score += 1
        if score > 0:
            scored.append((score, table))

    if not scored:
        return tables[:3]

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [table for _, table in scored[:5]]


# ---------------------------------------------------------------------------
# Table classification / platform grouping
# ---------------------------------------------------------------------------


async def classify_tables(
    tables: list[TableInfo], provider: str, model: str, api_key: str
) -> dict[str, dict]:
    """Classifies tables into platform/category/data_type. Not currently wired into the
    single-query pipeline (stream_single_query relies on TABLE_SELECTION_PROMPT's own
    platform reasoning instead, to avoid a third LLM call per request) — kept available
    as a standalone utility for future dashboard/browsing UX, per the reference doc's
    file map. Cached per exact table-set (7-day TTL)."""
    if not tables:
        return {}

    cache_key = "|".join(sorted(table.key for table in tables))
    now = time.time()
    cached = _classify_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    tables_info = "\n".join(
        f"{table.key}: columns={[col.column_name for col in table.columns]}" for table in tables
    )
    prompt = prompts.TABLE_CLASSIFICATION_PROMPT.format(tables_info=tables_info)
    text = await call_llm(
        provider, model, api_key, [{"role": "user", "content": prompt}], max_tokens=2000, temperature=0.0
    )
    data = parse_llm_json(text)
    _classify_cache[cache_key] = (now + CHATBOT_CLASSIFY_CACHE_TTL_SECONDS, data)
    return data
