"""Helpers shared by both chat engines (the AutoCare MCP agent and the old SQL agent): cleanup of the
answer text, chart suggestions for a result table, display formatting of cell values, and the fixed
notes the application appends to an answer. Kept free of any engine-specific import so either engine
can be changed or removed without touching the other."""

from __future__ import annotations

import re
from datetime import datetime, timezone

# query-result.tsx's FormattedAnswerText renders exactly "**bold**", "- " bullets, and blank-line
# paragraph breaks — nothing else. **bold** is left alone, but markdown headers (#, ##, ...) are not
# part of that subset and LLMs reach for them anyway, so only the header markers are stripped.
_MD_HEADER_RE = re.compile(r"(?m)^#{1,6}[ \t]+")


def strip_markdown_formatting(text: str) -> str:
    if not text:
        return text
    text = _MD_HEADER_RE.sub("", text)
    # Inline code spans aren't rendered either; in answers they only ever wrap raw column names.
    return text.replace("`", "")


# ---------------------------------------------------------------------------
# Fixed notes. Added by the application, not the model, so the wording is identical on every run.
# ---------------------------------------------------------------------------

CUSTOMER_LEVEL_ACTIVE_NOTE = (
    "Note: this figure is at the customer level. It counts each customer with at least one active "
    "subscription once, even when a customer holds several active memberships, so it can be lower than "
    "the total number of active memberships."
)

BACKUP_ENGINE_NOTE = (
    "Note: this answer came from the backup engine because the main analytics service was not "
    "available. Figures may differ slightly from the main service."
)


def build_partial_list_note(shown: int, total: int, total_exact: bool, unique_customers: int | None) -> str:
    customers = f" ({unique_customers:,} unique customers)" if unique_customers is not None else ""
    of_total = f"{total:,}" if total_exact else f"more than {total:,}"
    return (
        f"Note: the table shows the first {shown:,} of {of_total} matching rows{customers}. The table, CSV "
        f"download, Crear Segmento and Send to GHL include only those {shown:,} rows — narrow the question "
        "(for example by location or date range) to get the complete list."
    )


# ---------------------------------------------------------------------------
# Result tables
# ---------------------------------------------------------------------------

_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$")


def display_value(value):
    """ISO timestamps become 'YYYY-MM-DD HH:MM:SS UTC', the format the table already showed before."""
    if isinstance(value, str) and _ISO_TIMESTAMP_RE.match(value):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        if moment.tzinfo is not None:
            moment = moment.astimezone(timezone.utc)
        return moment.strftime("%Y-%m-%d %H:%M:%S UTC")
    return value


def infer_fields(columns: list[str], rows: list[dict]) -> list[dict]:
    """Column types guessed from the values: [{"name", "type"}] with the type names infer_charts reads.
    Strings are never parsed as numbers (a phone number is text)."""
    fields = []
    for column in columns:
        values = [row.get(column) for row in rows if row.get(column) is not None]
        if not values:
            kind = "STRING"
        elif all(isinstance(v, bool) for v in values):
            kind = "BOOL"
        elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            kind = "FLOAT64"
        elif all(isinstance(v, str) and _UTC_TIMESTAMP_RE.match(v) for v in values):
            kind = "TIMESTAMP"
        elif all(isinstance(v, str) and _DATE_RE.match(v) for v in values):
            kind = "DATE"
        else:
            kind = "STRING"
        fields.append({"name": column, "type": kind})
    return fields


_DATE_FIELD_TYPES = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}
_NUMERIC_FIELD_TYPES = {"INT64", "INTEGER", "FLOAT64", "FLOAT", "NUMERIC", "BIGNUMERIC"}


def humanize_column(name: str) -> str:
    return name.replace("_", " ").strip().title()


def infer_charts(fields: list[dict], data: list[dict]) -> list[dict]:
    """Heuristic chart suggestion from the result's column types — no extra LLM round trip. A date
    column becomes a line-chart x-axis (trend over time); any other non-numeric column becomes a
    bar-chart x-axis (category breakdown). Returns [] (table only) when there is nothing meaningful to
    plot: a single scalar row, or no numeric column to use as a y-axis."""
    if len(data) < 2:
        return []
    field_types = {f.get("name"): (f.get("type") or "").upper() for f in fields}
    numeric_cols = [c for c, t in field_types.items() if t in _NUMERIC_FIELD_TYPES]
    if not numeric_cols:
        return []
    date_cols = [c for c, t in field_types.items() if t in _DATE_FIELD_TYPES]
    x_field = date_cols[0] if date_cols else next((c for c in field_types if c not in numeric_cols), None)
    if x_field is None:
        return []
    y_field = next((c for c in numeric_cols if c != x_field), None)
    if y_field is None:
        return []
    chart_type = "line" if date_cols else "bar"
    return [
        {
            "type": chart_type,
            "title": f"{humanize_column(y_field)} by {humanize_column(x_field)}",
            "x_field": x_field,
            "y_field": y_field,
            "x_label": humanize_column(x_field),
            "y_label": humanize_column(y_field),
        }
    ]
