"""Segment drill-down on query specs.

A drill step narrows the previous result: the new `query` spec must keep EVERY filter and rollup of the
previous spec (same view) and add the new condition. The model writes the whole spec, and
check_drill_call rejects a spec that lost a previous filter, so a step can never widen the segment.

Steps are not saved: the browser carries the previous step's spec back with each request. The spec is
JSON that the MCP server validates itself (every column is checked against its catalog and every
value is sent to BigQuery as a parameter), so no signature is needed; only the size is limited here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

MAX_SPEC_CHARS = 20_000
MAX_CHAIN_DEPTH = 10
_MAX_QUESTION_CHARS = 300

ALLOWED_VIEWS = {
    "customer_360_vw",
    "subscription_360_vw",
    "session_360_vw",
    "location_360_vw",
    "daily_business_metrics_vw",
}
# Short names the MCP server accepts (see API_GUIDE.md, "{view} accepts the full name or a short one").
_VIEW_ALIASES = {
    "customer": "customer_360_vw",
    "customers": "customer_360_vw",
    "subscription": "subscription_360_vw",
    "subscriptions": "subscription_360_vw",
    "membership": "subscription_360_vw",
    "memberships": "subscription_360_vw",
    "session": "session_360_vw",
    "sessions": "session_360_vw",
    "visits": "session_360_vw",
    "location": "location_360_vw",
    "locations": "location_360_vw",
    "stores": "location_360_vw",
    "daily": "daily_business_metrics_vw",
    "daily_metrics": "daily_business_metrics_vw",
}


@dataclass(frozen=True)
class DrillStep:
    question: str
    row_count: int | None


@dataclass
class DrillContext:
    base_view: str
    base_spec: dict
    chain: list[DrillStep] = field(default_factory=list)


def normalize_view(value) -> str | None:
    key = str(value or "").strip().lower()
    if key in ALLOWED_VIEWS:
        return key
    return _VIEW_ALIASES.get(key)


def sanitize_base_spec(base_view, base_spec) -> tuple[str, dict]:
    """Returns (view, spec) as plain JSON data, or raises ValueError with a user-readable reason."""
    if not isinstance(base_spec, dict):
        raise ValueError("The previous query is missing.")
    view = normalize_view(base_view) or normalize_view(base_spec.get("view"))
    if view is None:
        raise ValueError("The previous query uses an unknown data view.")
    try:
        text = json.dumps(base_spec, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("The previous query is not valid.") from error
    if len(text) > MAX_SPEC_CHARS:
        raise ValueError("The previous query is too large.")
    return view, json.loads(text)


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


def _canonical(item) -> str:
    return json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def check_drill_call(drill: DrillContext, name: str, arguments: dict) -> str | None:
    """None when the call keeps the segment, otherwise a message for the model to fix its spec."""
    if name != "query":
        return "In a drill-down, call only the `query` tool."
    spec = arguments.get("spec")
    if not isinstance(spec, dict):
        return "The `spec` argument must be an object."
    if normalize_view(spec.get("view")) != drill.base_view:
        return f"Use the same view as the previous step: {drill.base_view}."
    for key in ("filters", "rollups"):
        wanted = drill.base_spec.get(key) or []
        have = {_canonical(item) for item in (spec.get(key) or [])}
        for item in wanted:
            if _canonical(item) not in have:
                return (
                    f"Your spec dropped this previous {key[:-1]}: {_canonical(item)}. Copy every previous "
                    "filter and rollup exactly as it is, then add the new condition."
                )
    return None


def build_drill_block(drill: DrillContext) -> str:
    lines = [
        "<DRILL_DOWN>",
        "The user narrows a segment of customers one step at a time. The question is the next narrowing "
        "step. Steps so far, oldest first:",
    ]
    for index, step in enumerate(drill.chain, start=1):
        size = f" -> {step.row_count:,} rows" if step.row_count is not None else ""
        lines.append(f"{index}. {json.dumps(step.question, ensure_ascii=False)}{size}")
    lines += [
        "The previous step ran this `query` spec:",
        json.dumps(drill.base_spec, ensure_ascii=False),
        "Rules for this question:",
        "- Call `query` ONCE, with the SAME view.",
        "- Copy EVERY filter and EVERY rollup of the previous spec exactly as they are, then add the new "
        "condition(s) from the question. Never drop or change a previous filter.",
        "- Return a list of customers (no metrics), unless the user asks \"how many\". Put client_id, "
        "full_name, email and phone_number first in `columns`, then any column the question needs.",
        "- Describe the answer relative to the previous segment (for example: \"N of those customers ...\"), "
        "not as a result over all customers.",
        "- Read \"these\", \"those\" and \"them\" as the customers of the previous step.",
        "</DRILL_DOWN>",
    ]
    return "\n".join(lines)
