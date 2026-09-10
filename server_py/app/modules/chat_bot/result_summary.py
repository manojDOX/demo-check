"""Exact totals and breakdowns for list results that hit the MCP tool's row cap.

The hosted MCP tool returns at most CHATBOT_MCP_ROW_CAP rows and its totalRows isn't reliable past
that. The rows it does return are just the first N in the query's sort order — not a
representative sample — so counting them in Python can be badly skewed (e.g. every row from the
last two days of a seven-day window). Instead, one extra query wraps the original SQL as a
subquery and aggregates the FULL result inside BigQuery. That aggregate result is tiny, so it is
never capped itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

MAX_CATEGORY_COLUMNS = 4
MAX_CATEGORY_VALUES = 10
MAX_DATE_BUCKETS = 60
_MAX_SAMPLE_DISTINCT = 20
_DAILY_MAX_SPAN_DAYS = 62

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Id/contact columns are useless as a breakdown even when a sample happens to repeat values.
_SKIP_CATEGORY_RE = re.compile(
    r"(^id$|_id$|email|phone|^full_name$|^first_name$|^last_name$|^customer_name$)", re.IGNORECASE
)
_CATEGORY_TYPES = {"STRING", "BOOL", "BOOLEAN"}
_DATE_TYPES = {"DATE", "DATETIME", "TIMESTAMP"}
_TOTAL_DIM = "__total__"
_NULL_STRING = "CAST(NULL AS STRING)"


@dataclass
class SummaryPlan:
    sql: str
    category_columns: list[str]
    date_column: str | None
    date_granularity: str | None
    has_customer_count: bool


@dataclass
class CategoryBreakdown:
    column: str
    values: list[tuple[str | None, int, int | None]]
    has_more: bool


@dataclass
class CappedSummary:
    total_rows: int
    unique_customers: int | None
    date_column: str | None = None
    min_date: str | None = None
    max_date: str | None = None
    date_granularity: str | None = None
    date_buckets: list[tuple[str, int]] = field(default_factory=list)
    breakdowns: list[CategoryBreakdown] = field(default_factory=list)


def _sample_span_days(values: list) -> int | None:
    parsed: list[date] = []
    for value in values:
        try:
            parsed.append(date.fromisoformat(str(value)[:10]))
        except ValueError:
            continue
    if not parsed:
        return None
    return (max(parsed) - min(parsed)).days


def plan_summary(base_sql: str, fields: list[dict], sample: list[dict]) -> SummaryPlan:
    """Builds one UNION ALL query over the full result: a total row (row count, distinct
    client_id, date range), top values for up to MAX_CATEGORY_COLUMNS category-like columns, and
    row counts per day/month for the first date column. Columns are chosen from the capped sample,
    but every count is computed over the full result."""
    base = base_sql.strip().rstrip(";").strip()
    source = f"FROM (\n{base}\n) AS base"
    typed = [
        (f["name"], (f.get("type") or "").upper())
        for f in fields
        if isinstance(f.get("name"), str) and _IDENTIFIER_RE.match(f["name"])
    ]

    client_column = next((name for name, _ in typed if name.lower() == "client_id"), None)
    customers = f"COUNT(DISTINCT `{client_column}`)" if client_column else "CAST(NULL AS INT64)"

    date_column, date_type = next(((n, t) for n, t in typed if t in _DATE_TYPES), (None, None))
    min_expr = max_expr = _NULL_STRING
    granularity: str | None = None
    date_branch: str | None = None
    if date_column:
        col = f"`{date_column}`"
        if date_type == "TIMESTAMP":
            min_expr = f"FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', MIN({col}))"
            max_expr = f"FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', MAX({col}))"
            day_expr = f"DATE({col})"
        elif date_type == "DATETIME":
            min_expr = f"FORMAT_DATETIME('%Y-%m-%d %H:%M:%S', MIN({col}))"
            max_expr = f"FORMAT_DATETIME('%Y-%m-%d %H:%M:%S', MAX({col}))"
            day_expr = f"DATE({col})"
        else:
            min_expr = f"CAST(MIN({col}) AS STRING)"
            max_expr = f"CAST(MAX({col}) AS STRING)"
            day_expr = col
        span = _sample_span_days([row.get(date_column) for row in sample if row.get(date_column)])
        granularity = "month" if span is not None and span > _DAILY_MAX_SPAN_DAYS else "day"
        bucket = (
            f"FORMAT_DATE('%Y-%m', DATE_TRUNC({day_expr}, MONTH))"
            if granularity == "month"
            else f"CAST({day_expr} AS STRING)"
        )
        date_branch = (
            f"(SELECT '{date_column}' AS dim, {bucket} AS val, COUNT(*) AS row_count, "
            f"{customers} AS customer_count, {_NULL_STRING} AS min_value, {_NULL_STRING} AS max_value "
            f"{source} WHERE {col} IS NOT NULL GROUP BY 2 ORDER BY 2 DESC LIMIT {MAX_DATE_BUCKETS})"
        )

    candidates = []
    for index, (name, ftype) in enumerate(typed):
        if ftype not in _CATEGORY_TYPES or name == client_column or _SKIP_CATEGORY_RE.search(name):
            continue
        distinct = len({str(row.get(name)) for row in sample})
        if 1 <= distinct <= _MAX_SAMPLE_DISTINCT:
            # Columns that vary within the sample first; a constant-looking one may still vary
            # across the full result, so it's kept as a lower-priority candidate.
            candidates.append((distinct < 2, index, name))
    category_columns = [name for _, _, name in sorted(candidates)[:MAX_CATEGORY_COLUMNS]]

    branches = [
        f"SELECT '{_TOTAL_DIM}' AS dim, {_NULL_STRING} AS val, COUNT(*) AS row_count, "
        f"{customers} AS customer_count, {min_expr} AS min_value, {max_expr} AS max_value {source}"
    ]
    for name in category_columns:
        branches.append(
            f"(SELECT '{name}' AS dim, CAST(`{name}` AS STRING) AS val, COUNT(*) AS row_count, "
            f"{customers} AS customer_count, {_NULL_STRING} AS min_value, {_NULL_STRING} AS max_value "
            f"{source} GROUP BY 2 ORDER BY 3 DESC LIMIT {MAX_CATEGORY_VALUES + 1})"
        )
    if date_branch:
        branches.append(date_branch)

    return SummaryPlan(
        sql="\nUNION ALL\n".join(branches),
        category_columns=category_columns,
        date_column=date_column,
        date_granularity=granularity,
        has_customer_count=client_column is not None,
    )


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_summary(plan: SummaryPlan, rows: list[dict]) -> CappedSummary | None:
    total = next((row for row in rows if row.get("dim") == _TOTAL_DIM), None)
    total_rows = _to_int(total.get("row_count")) if total else None
    if total is None or total_rows is None:
        return None

    summary = CappedSummary(
        total_rows=total_rows,
        unique_customers=_to_int(total.get("customer_count")) if plan.has_customer_count else None,
        date_column=plan.date_column,
        min_date=total.get("min_value"),
        max_date=total.get("max_value"),
        date_granularity=plan.date_granularity,
    )
    for name in plan.category_columns:
        values = [
            (row.get("val"), _to_int(row.get("row_count")) or 0, _to_int(row.get("customer_count")))
            for row in rows
            if row.get("dim") == name
        ]
        values.sort(key=lambda item: item[1], reverse=True)
        if values:
            summary.breakdowns.append(
                CategoryBreakdown(name, values[:MAX_CATEGORY_VALUES], len(values) > MAX_CATEGORY_VALUES)
            )
    if plan.date_column:
        summary.date_buckets = sorted(
            (str(row.get("val")), _to_int(row.get("row_count")) or 0)
            for row in rows
            if row.get("dim") == plan.date_column and row.get("val") is not None
        )
    return summary


def _share(part: int, total: int) -> str:
    return f"{part / total:.0%}" if total else "n/a"


def format_summary_block(sql: str, summary: CappedSummary) -> str:
    lines = [
        f"SQL executed:\n{sql}",
        "",
        "The full result was too large to retrieve row by row, so the figures below were computed by "
        "BigQuery over ALL matching rows. They are exact, not estimates — state them as totals.",
        f"Total matching rows: {summary.total_rows:,}",
    ]
    if summary.unique_customers is not None:
        lines.append(
            f"Unique customers (distinct client_id) across those rows: {summary.unique_customers:,}. If "
            "this is lower than the row total, rows are not one per customer (e.g. one row per visit) — "
            "report rows and customers with the right units."
        )
    if summary.min_date and summary.max_date:
        lines.append(f"Range of {summary.date_column}: {summary.min_date} to {summary.max_date}")
    for breakdown in summary.breakdowns:
        parts = []
        for value, count, customers in breakdown.values:
            label = value if value not in (None, "") else "(blank)"
            customer_part = f", {customers:,} customers" if customers is not None else ""
            parts.append(f"{label}: {count:,} rows{customer_part} ({_share(count, summary.total_rows)})")
        more = "; plus other values" if breakdown.has_more else ""
        lines.append(f"Breakdown by {breakdown.column}: " + "; ".join(parts) + more)
    if summary.date_buckets:
        unit = summary.date_granularity or "day"
        lines.append(
            f"Rows per {unit} of {summary.date_column} (most recent {len(summary.date_buckets)}): "
            + "; ".join(f"{bucket}: {count:,}" for bucket, count in summary.date_buckets)
        )
    return "\n".join(lines)


def build_partial_list_note(shown: int, total: int, total_exact: bool, unique_customers: int | None) -> str:
    customers = f" ({unique_customers:,} unique customers)" if unique_customers is not None else ""
    of_total = f"{total:,}" if total_exact else f"more than {total:,}"
    return (
        f"Note: the table shows the first {shown:,} of {of_total} matching rows{customers}. The table, CSV "
        f"download, Crear Segmento and Send to GHL include only those {shown:,} rows — narrow the question "
        "(for example by location or date range) to get the complete list."
    )
