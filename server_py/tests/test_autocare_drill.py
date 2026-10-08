import json

import pytest

from app.modules.chat_bot import autocare_drill as drill
from app.modules.chat_bot.autocare_drill import DrillContext, DrillStep

from .fakes import FakeLlm, FakeMcpServer, of_type, query_result, run_agent, text_turn, tool_turn

BASE_FILTERS = [
    {"column": "has_active_subscription", "op": "is_true"},
    {"column": "has_visited", "op": "is_false"},
]
BASE_SPEC = {"view": "customer_360_vw", "filters": BASE_FILTERS, "columns": ["client_id", "full_name"], "limit": 500}


def _context(**overrides) -> DrillContext:
    return DrillContext(
        base_view="customer_360_vw",
        base_spec={**BASE_SPEC, **overrides},
        chain=[DrillStep("active customers who never visited", 393)],
    )


def _call(spec: dict, name: str = "query") -> tuple[str, dict]:
    return name, {"spec": spec}


# ---------------------------------------------------------------- the guard


def test_narrowing_step_that_keeps_every_filter_is_accepted():
    spec = {"view": "customer_360_vw", "filters": [*BASE_FILTERS, {"column": "tier_name", "op": "eq", "value": "premium"}]}
    assert drill.check_drill_call(_context(), *_call(spec)) is None


def test_filter_order_and_key_order_do_not_matter():
    spec = {
        "view": "customer_360_vw",
        "filters": [{"op": "is_false", "column": "has_visited"}, {"op": "is_true", "column": "has_active_subscription"}],
    }
    assert drill.check_drill_call(_context(), *_call(spec)) is None


def test_a_dropped_filter_is_rejected_and_named():
    spec = {"view": "customer_360_vw", "filters": [BASE_FILTERS[0], {"column": "tier_name", "op": "eq", "value": "premium"}]}
    problem = drill.check_drill_call(_context(), *_call(spec))
    assert problem and "dropped this previous filter" in problem and "has_visited" in problem


def test_a_changed_filter_value_counts_as_dropped():
    spec = {"view": "customer_360_vw", "filters": [BASE_FILTERS[0], {"column": "has_visited", "op": "is_true"}]}
    assert drill.check_drill_call(_context(), *_call(spec)) is not None


def test_a_dropped_rollup_is_rejected():
    rollup = {"alias": "visits_30d", "relation": "sessions", "agg": "count"}
    context = _context(rollups=[rollup])
    spec = {"view": "customer_360_vw", "filters": BASE_FILTERS}
    assert "rollup" in drill.check_drill_call(context, *_call(spec))
    assert drill.check_drill_call(context, *_call({**spec, "rollups": [rollup]})) is None


def test_another_view_or_another_tool_is_rejected():
    assert "same view" in drill.check_drill_call(_context(), *_call({"view": "subscription_360_vw", "filters": BASE_FILTERS}))
    assert "only the `query` tool" in drill.check_drill_call(_context(), "customer_profile", {"email": "a@x"})
    assert "object" in drill.check_drill_call(_context(), "query", {"spec": "oops"})


def test_short_view_names_are_the_same_view():
    spec = {"view": "customers", "filters": BASE_FILTERS}
    assert drill.check_drill_call(_context(), *_call(spec)) is None


# ---------------------------------------------------------------- inputs from the browser


def test_base_spec_is_checked_and_returned_as_plain_json():
    view, spec = drill.sanitize_base_spec("customers", BASE_SPEC)
    assert view == "customer_360_vw" and spec == BASE_SPEC and spec is not BASE_SPEC


def test_base_view_falls_back_to_the_view_inside_the_spec():
    assert drill.sanitize_base_spec("", BASE_SPEC)[0] == "customer_360_vw"


@pytest.mark.parametrize(
    ("view", "spec", "reason"),
    [
        ("customer_360_vw", None, "missing"),
        ("customer_360_vw", "text", "missing"),
        ("secrets_table", {"filters": []}, "unknown data view"),
        ("customer_360_vw", {"filters": [{"column": "x", "value": "y" * 25000}]}, "too large"),
    ],
)
def test_bad_base_spec_is_refused_with_a_reason(view, spec, reason):
    with pytest.raises(ValueError, match=reason):
        drill.sanitize_base_spec(view, spec)


def test_chain_is_cleaned_and_limited():
    chain = [{"question": f"  step  {i} ", "row_count": i} for i in range(25)]
    chain += [{"question": "x", "row_count": True}, {"question": "y", "row_count": -3}, {"question": ""}, "junk"]
    steps = drill.sanitize_chain(chain)
    assert len(steps) <= drill.MAX_CHAIN_DEPTH
    assert steps[-2:] == [DrillStep("x", None), DrillStep("y", None)]
    assert drill.sanitize_chain([{"question": "a" * 1000}])[0].question == "a" * 300


def test_drill_block_holds_the_steps_the_spec_and_the_rules():
    block = drill.build_drill_block(_context())
    assert "<DRILL_DOWN>" in block and block.rstrip().endswith("</DRILL_DOWN>")
    assert '1. "active customers who never visited" -> 393 rows' in block
    assert json.dumps(BASE_SPEC, ensure_ascii=False) in block
    assert "Copy EVERY filter and EVERY rollup" in block


# ---------------------------------------------------------------- inside the agent loop


def test_agent_makes_the_model_retry_when_it_drops_a_filter(monkeypatch):
    dropped = {"view": "customer_360_vw", "filters": [{"column": "tier_name", "op": "eq", "value": "premium"}], "columns": ["client_id"]}
    kept_filters = [*BASE_FILTERS, {"column": "tier_name", "op": "eq", "value": "premium"}]
    kept = {"view": "customer_360_vw", "filters": kept_filters, "columns": ["client_id", "full_name"]}
    server = FakeMcpServer({"query": query_result([{"client_id": "c1", "full_name": "A"}])})
    llm = FakeLlm(
        [tool_turn("query", {"spec": dropped}), tool_turn("query", {"spec": kept}, "call-2"), text_turn("1 of those customers is on Premium.")]
    )
    events = run_agent(monkeypatch, llm, server, conversation_history=[], drill=_context())

    assert len(server.calls("query")) == 1  # the first, wrong call never reached the server
    assert "dropped this previous filter" in llm.calls[1]["messages"][-1]["content"]
    assert "<DRILL_DOWN>" in llm.calls[0]["messages"][0]["content"]
    rows = of_type(events, "rows")[0]
    assert rows["spec"]["spec"]["filters"] == kept_filters  # comes back for the next drill step
    assert events[-1]["billable"] is True
