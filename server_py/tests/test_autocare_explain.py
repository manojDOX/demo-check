import json

import pytest

from app.modules.chat_bot.autocare_agent import build_table_events
from app.modules.chat_bot.autocare_explain import ACTIVE_MEMBERS_NOTE, ACTIVE_MEMBERSHIPS_NOTE, explain_profile, explain_query


def lines(view, spec, total=10, shown=10):
    block = explain_query(view, spec, total, shown)
    assert block is not None
    return [(line["label"], line["value"]) for line in block["lines"]]


def values(view, spec, label, **kwargs):
    return [value for key, value in lines(view, spec, **kwargs) if key == label]


def test_active_memberships_count():
    spec = {
        "view": "subscription_360_vw",
        "filters": [{"column": "is_active_subscription", "op": "is_true"}],
        "metrics": [{"agg": "count", "alias": "active_memberships"}],
    }
    result = lines("subscription_360_vw", spec, total=1, shown=1)
    assert result[0] == ("Data source", "Memberships")
    assert ("Filter", "membership is active") in result
    assert ("Calculation", "Number of rows") in result
    assert ("Result", "1 result row") in result
    assert ("Definition", ACTIVE_MEMBERSHIPS_NOTE) in result


def test_customer_level_definition_only_for_the_customer_view():
    spec = {"filters": [{"column": "has_active_subscription", "op": "is_true"}], "metrics": [{"agg": "count"}]}
    assert ("Definition", ACTIVE_MEMBERS_NOTE) in lines("customer_360_vw", spec)
    assert not values("session_360_vw", spec, "Definition")


def test_date_filters_in_plain_words():
    filters = [
        {"column": "session_date", "op": "in_last", "value": {"n": 7, "unit": "day"}},
        {"column": "current_period_end", "op": "in_next", "value": {"n": 1, "unit": "month"}},
        {"column": "cancelled_or_ended_at", "op": "older_than", "value": {"n": 90, "unit": "day"}},
        {"column": "current_period_end", "op": "preset", "value": "this_month"},
    ]
    text = values("subscription_360_vw", {"filters": filters}, "Filter")
    assert text == [
        "visit date is in the last 7 days",
        "renewal date is in the next 1 month",
        "cancellation date is more than 90 days ago",
        "renewal date is this month",
    ]


def test_comparison_list_null_and_or_filters():
    filters = [
        {"column": "tier_name", "op": "eq", "value": "premium"},
        {"column": "days_until_renewal", "op": "between", "value": [7, 10]},
        {"column": "tier_name", "op": "in", "value": ["basic", "pro"]},
        {"column": "days_since_last_visit", "op": "gt", "value": 30, "include_nulls": True},
        {"column": "has_visited", "op": "is_false"},
        {"any_of": [{"column": "days_since_last_visit", "op": "gte", "value": 90}, {"column": "has_visited", "op": "is_false"}]},
    ]
    assert values("customer_360_vw", {"filters": filters}, "Filter") == [
        "plan is 'premium'",
        "days until renewal is between 7 and 10",
        "plan is one of 'basic', 'pro'",
        "days since last visit is more than 30 (also when the value is empty)",
        "NOT: has visited",
        "(days since last visit is at least 90 OR NOT: has visited)",
    ]


def test_no_filter_group_by_metrics_and_sort():
    spec = {
        "view": "customer_360_vw",
        "group_by": ["tier_name", {"column": "session_date", "grain": "week"}],
        "metrics": [
            {"agg": "count", "alias": "customers", "pct_of_total": True},
            {"agg": "avg", "column": "washes_per_month"},
            {"agg": "count", "alias": "late", "filters": [{"column": "is_payment_delinquent", "op": "is_true"}]},
        ],
        "order_by": [{"column": "customers", "direction": "desc"}],
    }
    result = lines("customer_360_vw", spec, total=4, shown=4)
    assert ("Filter", "None. All rows are used.") in result
    assert ("Grouped by", "plan, visit date by week") in result
    assert ("Calculation", "Number of rows, shown as a share of the total") in result
    assert ("Calculation", "Average of washes per month") in result
    assert ("Calculation", "Number of rows, only where payment is overdue") in result
    assert ("Sorted by", "customers (highest first)") in result


def test_rollup_having_and_top_percent():
    spec = {
        "rollups": [
            {
                "alias": "visits_3m",
                "relation": "sessions",
                "agg": "count",
                "filters": [{"column": "session_date", "op": "in_last", "value": {"n": 3, "unit": "month"}}],
            }
        ],
        "filters": [{"column": "visits_3m", "op": "gt", "value": 0}],
        "top_percent": {"column": "visits_3m", "percent": 10},
    }
    result = lines("customer_360_vw", spec, total=20, shown=20)
    assert ("Counted per row", "visits 3m = number of visits, counting only: visit date is in the last 3 months") in result
    assert ("Top share", "Only the top 10% by visits 3m") in result


def test_ref_compares_with_the_same_row():
    rollup = {"alias": "v", "relation": "sessions", "agg": "count", "filters": [{"column": "session_date", "op": "lt", "ref": "cancelled_or_ended_at"}]}
    text = values("subscription_360_vw", {"rollups": [rollup]}, "Counted per row")[0]
    assert "visit date is less than the cancellation date of the same row" in text


def test_result_line_for_complete_and_partial_lists():
    assert values("customer_360_vw", {"columns": ["client_id"]}, "Result", total=10577, shown=10577) == ["10,577 rows matched (all shown)."]
    assert values("customer_360_vw", {"columns": ["client_id"]}, "Result", total=10577, shown=500) == [
        "10,577 rows matched. The first 500 are shown in the table."
    ]
    assert values("customer_360_vw", {}, "Result", total=1, shown=1) == ["1 row matched (all shown)."]


def test_lookup_columns_are_named_in_words():
    spec = {"filters": [{"column": "customer.tier_name", "op": "eq", "value": "basic"}], "metrics": [{"agg": "count"}]}
    assert values("session_360_vw", spec, "Filter") == ["plan of the customer is 'basic'"]


def test_unreadable_specs_never_raise():
    assert explain_query("customer_360_vw", None, 1, 1) is None
    assert explain_query("customer_360_vw", "text", 1, 1) is None
    odd = {"filters": [{"column": None, "op": None}, {"any_of": ["x"]}], "metrics": [{}], "group_by": [None], "order_by": [{}]}
    assert explain_query("customer_360_vw", odd, 1, 1) is not None
    assert explain_query("customer_360_vw", {"metrics": [{"ratio_of": 5}]}, 1, 1) is None  # bad shape -> None, no crash


def test_same_spec_gives_the_same_text():
    spec = {"filters": [{"column": "tier_name", "op": "eq", "value": "basic"}], "metrics": [{"agg": "count"}]}
    assert json.dumps(explain_query("customer_360_vw", spec, 1, 1)) == json.dumps(explain_query("customer_360_vw", spec, 1, 1))


def test_profile_block():
    assert explain_profile(1)["lines"][-1]["value"] == "1 customer found."
    assert explain_profile(2)["lines"][-1]["value"] == "2 customers found."


def test_rows_event_carries_the_explain_block():
    spec = {"view": "customer_360_vw", "filters": [{"column": "has_active_subscription", "op": "is_true"}], "metrics": [{"agg": "count", "alias": "n"}]}
    result = {"view": "customer_360_vw", "columns": ["n"], "rows": [{"n": 10577}], "total_rows": 1, "sql": "SELECT 1", "params": []}
    events, _ = build_table_events("query", {"spec": spec}, result)
    rows = next(e for e in events if e["type"] == "rows")
    assert rows["explain"]["lines"][0] == {"label": "Data source", "value": "Customers"}
    assert rows["spec"]["spec"] == spec

    profile_events, _ = build_table_events("customer_profile", {}, {"customers": [{"client_id": "c1", "email": "a@b.c"}]})
    assert profile_events[0]["explain"]["lines"][0]["value"] == "Customer profile lookup"


@pytest.mark.parametrize("op", ["is_null", "not_null", "contains", "not_contains", "starts_with", "ends_with", "array_contains", "ne", "lte", "before", "after", "on", "not_in"])
def test_every_operator_gives_readable_text(op):
    text = values("customer_360_vw", {"filters": [{"column": "email", "op": op, "value": "x"}]}, "Filter")[0]
    assert "email" in text and "None" not in text
