"""Plain-words explanation of a query spec, built by code (never by the model).

The chat panel "How it was calculated" shows this next to the result so a person can check it:
data source, each filter in plain words, the calculation, and how many rows matched. The same
spec always gives the same text. The function never raises: a spec it cannot read gives `None`,
and the browser then shows the technical details only.
"""

from __future__ import annotations

import logging

from app.modules.chat_bot.answer_utils import humanize_column

logger = logging.getLogger(__name__)

VIEW_LABELS = {
    "customer_360_vw": "Customers",
    "subscription_360_vw": "Memberships",
    "session_360_vw": "Visits",
    "location_360_vw": "Stores",
    "daily_business_metrics_vw": "Daily business metrics",
}

COLUMN_LABELS = {
    "has_active_subscription": "has an active membership",
    "is_active_subscription": "membership is active",
    "is_cancelled_subscription": "membership is cancelled",
    "has_visited": "has visited",
    "is_payment_delinquent": "payment is overdue",
    "tier_name": "plan",
    "client_id": "customer",
    "days_since_last_visit": "days since last visit",
    "days_until_renewal": "days until renewal",
    "current_period_end": "renewal date",
    "cancelled_or_ended_at": "cancellation date",
    "session_date": "visit date",
    "customer_created_date": "sign-up date",
    "subscription_tenure_days": "membership length (days)",
    "tenure_at_cancel_days": "membership length at cancellation (days)",
    "current_mrr": "monthly revenue",
    "current_arr": "yearly revenue",
}

OP_TEXT = {
    "eq": "is",
    "ne": "is not",
    "gt": "is more than",
    "gte": "is at least",
    "lt": "is less than",
    "lte": "is at most",
    "contains": "contains",
    "not_contains": "does not contain",
    "starts_with": "starts with",
    "ends_with": "ends with",
    "array_contains": "includes",
    "before": "is before",
    "after": "is after",
    "on": "is on",
}

PRESET_TEXT = {
    "today": "today",
    "yesterday": "yesterday",
    "this_week": "this week",
    "last_week": "last week",
    "this_month": "this month",
    "last_month": "last month",
    "next_month": "next month",
    "this_quarter": "this quarter",
    "last_quarter": "last quarter",
    "this_year": "this year",
    "last_year": "last year",
    "past": "in the past",
    "future": "in the future",
}

AGG_TEXT = {
    "count": "Number of rows",
    "count_distinct": "Number of different",
    "sum": "Total of",
    "avg": "Average of",
    "min": "Lowest",
    "max": "Highest",
    "median": "Middle value (median) of",
    "stddev": "Spread (standard deviation) of",
    "array_agg_distinct": "List of different",
}

GRAIN_TEXT = {
    "day": "day",
    "week": "week",
    "month": "month",
    "quarter": "quarter",
    "year": "year",
    "day_of_week": "day of the week",
    "month_of_year": "month of the year",
    "hour": "hour",
}

ACTIVE_MEMBERSHIPS_NOTE = (
    "Active memberships are counted as different memberships marked active. No renewal-date check is made."
)
ACTIVE_MEMBERS_NOTE = (
    "Active members are customers who have at least one active membership. One customer is counted once."
)


def _col(name) -> str:
    text = str(name or "")
    if text in COLUMN_LABELS:
        return COLUMN_LABELS[text]
    prefix, dot, rest = text.partition(".")
    if dot and prefix in ("customer", "location"):
        return f"{_col(rest)} of the {prefix}"
    return humanize_column(text).lower()


def _val(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    if isinstance(value, int):
        return f"{value:,}"
    return f"'{value}'"


def _period(value) -> str:
    if isinstance(value, dict) and value.get("n") is not None:
        n = value["n"]
        unit = str(value.get("unit") or "day")
        return f"{n} {unit}{'' if n == 1 else 's'}"
    return _val(value)


def _filter_text(item: dict) -> str:
    if "any_of" in item or "all_of" in item:
        key = "any_of" if "any_of" in item else "all_of"
        joiner = " OR " if key == "any_of" else " AND "
        parts = [_filter_text(sub) for sub in item[key] if isinstance(sub, dict)]
        return "(" + joiner.join(parts) + ")"

    column = _col(item.get("column"))
    op = item.get("op")
    value = item.get("value")
    ref = item.get("ref")

    if op == "is_true":
        text = column
    elif op == "is_false":
        text = f"NOT: {column}"
    elif op == "is_null":
        text = f"{column} is empty"
    elif op == "not_null":
        text = f"{column} is filled in"
    elif op in ("in", "not_in"):
        values = ", ".join(_val(v) for v in (value if isinstance(value, list) else [value]))
        text = f"{column} {'is one of' if op == 'in' else 'is none of'} {values}"
    elif op == "between":
        low, high = (list(value) + [None, None])[:2] if isinstance(value, list) else (None, None)
        text = f"{column} is between {_val(low)} and {_val(high)}"
    elif op == "in_last":
        text = f"{column} is in the last {_period(value)}"
    elif op == "in_next":
        text = f"{column} is in the next {_period(value)}"
    elif op == "older_than":
        text = f"{column} is more than {_period(value)} ago"
    elif op == "preset":
        text = f"{column} is {PRESET_TEXT.get(str(value), str(value))}"
    elif op in OP_TEXT:
        target = f"the {_col(ref)} of the same row" if ref else _val(value)
        text = f"{column} {OP_TEXT[op]} {target}"
    else:
        text = f"{column} {op} {_val(value)}"

    if item.get("include_nulls"):
        text += " (also when the value is empty)"
    return text


def _metric_text(metric: dict) -> str:
    agg = str(metric.get("agg") or "")
    column = metric.get("column")
    if metric.get("ratio_of"):
        num, den = (list(metric["ratio_of"]) + ["", ""])[:2]
        suffix = " (as a percent)" if metric.get("percent") else ""
        text = f"{_col(num)} divided by {_col(den)}{suffix}"
    elif agg == "count":
        text = AGG_TEXT["count"]
    elif agg == "percentile":
        text = f"Percentile {metric.get('percentile')} of {_col(column)}"
    elif agg == "quantiles":
        text = f"Cut points ({metric.get('buckets')} equal groups) of {_col(column)}"
    elif agg in AGG_TEXT:
        text = f"{AGG_TEXT[agg]} {_col(column)}"
    else:
        text = f"{agg} {_col(column)}".strip()
    if metric.get("filters"):
        text += ", only where " + " AND ".join(_filter_text(f) for f in metric["filters"] if isinstance(f, dict))
    if metric.get("pct_of_total"):
        text += ", shown as a share of the total"
    return text


def _group_text(item) -> str:
    if isinstance(item, str):
        return _col(item)
    if isinstance(item, dict):
        text = _col(item.get("column"))
        if item.get("grain"):
            text += f" by {GRAIN_TEXT.get(str(item['grain']), item['grain'])}"
        if item.get("bins") or item.get("breaks"):
            text += " in ranges"
        return text
    return str(item)


def _rollup_text(rollup: dict) -> str:
    relation = {"sessions": "visits", "subscriptions": "memberships"}.get(str(rollup.get("relation")), rollup.get("relation"))
    agg = str(rollup.get("agg") or "count")
    if agg == "count":
        what = f"number of {relation}"
    else:
        what = f"{AGG_TEXT.get(agg, agg).lower()} {_col(rollup.get('column'))} of {relation}"
    if rollup.get("grain"):
        what += f" (per {GRAIN_TEXT.get(str(rollup['grain']), rollup['grain'])})"
    text = f"{_col(rollup.get('alias'))} = {what}"
    if rollup.get("filters"):
        text += ", counting only: " + " AND ".join(_filter_text(f) for f in rollup["filters"] if isinstance(f, dict))
    return text


def _result_text(total_rows: int, shown_rows: int, aggregate: bool) -> str:
    if aggregate:
        return f"{total_rows:,} result row{'' if total_rows == 1 else 's'}"
    if total_rows > shown_rows:
        return f"{total_rows:,} rows matched. The first {shown_rows:,} are shown in the table."
    return f"{total_rows:,} row{'' if total_rows == 1 else 's'} matched (all shown)."


def explain_query(view, spec, total_rows: int, shown_rows: int) -> dict | None:
    """Plain-words lines for a `query` spec: {"lines": [{"label", "value"}, ...]}."""
    try:
        return _explain(view, spec, total_rows, shown_rows)
    except Exception:  # an odd spec must never break the answer
        logger.warning("Could not explain a query spec", exc_info=True)
        return None


def _explain(view, spec, total_rows: int, shown_rows: int) -> dict | None:
    if not isinstance(spec, dict):
        return None
    lines: list[dict] = []

    def add(label: str, value: str) -> None:
        lines.append({"label": label, "value": value})

    add("Data source", VIEW_LABELS.get(str(view), str(view or "Unknown")))

    filters = [f for f in (spec.get("filters") or []) if isinstance(f, dict)]
    if filters:
        for item in filters:
            add("Filter", _filter_text(item))
    else:
        add("Filter", "None. All rows are used.")

    for rollup in spec.get("rollups") or []:
        if isinstance(rollup, dict):
            add("Counted per row", _rollup_text(rollup))

    metrics = [m for m in (spec.get("metrics") or []) if isinstance(m, dict)]
    if metrics:
        for metric in metrics:
            add("Calculation", _metric_text(metric))
        groups = spec.get("group_by") or []
        if groups:
            add("Grouped by", ", ".join(_group_text(g) for g in groups))
    else:
        columns = spec.get("columns")
        add("Calculation", "A list of matching rows" + (f" with {len(columns)} columns" if isinstance(columns, list) and columns else ""))

    for item in spec.get("having") or []:
        if isinstance(item, dict):
            add("Then keep only", _filter_text(item))

    top = spec.get("top_percent")
    if isinstance(top, dict) and top.get("percent") is not None:
        add("Top share", f"Only the top {top['percent']}% by {_col(top.get('column'))}")

    order = [o for o in (spec.get("order_by") or []) if isinstance(o, dict)]
    if order:
        add(
            "Sorted by",
            ", ".join(
                f"{_col(o.get('column'))} ({'lowest first' if str(o.get('direction')).lower() == 'asc' else 'highest first'})"
                for o in order
            ),
        )

    add("Result", _result_text(total_rows, shown_rows, bool(metrics)))

    if view == "subscription_360_vw" and any(
        f.get("column") == "is_active_subscription" and f.get("op") == "is_true" for f in filters
    ):
        add("Definition", ACTIVE_MEMBERSHIPS_NOTE)
    elif view == "customer_360_vw" and any(
        f.get("column") == "has_active_subscription" and f.get("op") == "is_true" for f in filters
    ):
        add("Definition", ACTIVE_MEMBERS_NOTE)

    add("Time zone", "Dates use Puerto Rico time.")
    return {"lines": lines}


def explain_profile(shown_rows: int) -> dict:
    """Explanation for the one-customer lookup (customer_profile tool)."""
    return {
        "lines": [
            {"label": "Data source", "value": "Customer profile lookup"},
            {"label": "Calculation", "value": "The customer is found by the email, phone or name in the question."},
            {"label": "Result", "value": f"{shown_rows:,} customer{'' if shown_rows == 1 else 's'} found."},
        ]
    }
