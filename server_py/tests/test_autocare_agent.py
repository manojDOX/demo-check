import json

import pytest

from app.modules.chat_bot import autocare_agent as agent
from app.modules.chat_bot.answer_utils import CUSTOMER_LEVEL_ACTIVE_NOTE
from app.modules.chat_bot.autocare_client import McpUnavailable

from .fakes import (
    FakeLlm,
    FakeMcpServer,
    HttpStatus,
    ToolError,
    default_tools,
    empty_turn,
    of_type,
    query_result,
    run_agent,
    text_turn,
    tool_turn,
)

ACTIVE_MEMBERS_SPEC = {
    "spec": {
        "view": "customer_360_vw",
        "filters": [{"column": "has_active_subscription", "op": "is_true"}],
        "metrics": [{"agg": "count", "alias": "active_members"}],
    }
}


def _members_result():
    return query_result(
        [{"active_members": 10577}], total_rows=1, sql="SELECT COUNT(*) FROM v WHERE n = @p0", params={"p0": "a'b"}
    )


# ---------------------------------------------------------------- the normal path


def test_successful_question_produces_the_events_the_screen_needs(monkeypatch):
    server = FakeMcpServer({"query": _members_result()})
    llm = FakeLlm([tool_turn("query", ACTIVE_MEMBERS_SPEC), text_turn("There are 10,577 active members.")])
    events = run_agent(monkeypatch, llm, server, conversation_history=[{"role": "user", "content": "hi"}])

    kinds = [event["type"] for event in events if event["type"] != "status"]
    assert kinds == ["sql", "rows", "text", "done"]

    sql = of_type(events, "sql")[0]
    assert sql["content"] == "SELECT COUNT(*) FROM v WHERE n = 'a\\'b'"  # parameters put into the text
    assert sql["tables_used"] == ["customer_360_vw"]

    rows = of_type(events, "rows")[0]
    assert rows["data"] == [{"active_members": 10577}]
    assert (rows["total_rows"], rows["truncated"], rows["engine"]) == (1, False, "autocare_mcp")
    assert rows["spec"]["view"] == "customer_360_vw"
    assert rows["spec"]["spec"] == ACTIVE_MEMBERS_SPEC["spec"]

    text = of_type(events, "text")[0]["content"]
    assert text.startswith("There are 10,577 active members.")
    assert text.endswith(CUSTOMER_LEVEL_ACTIVE_NOTE)

    done = events[-1]
    assert done == {"type": "done", "billable": True, "confidence": 0.9, "tables_used": ["customer_360_vw"]}


def test_system_prompt_history_and_key_header(monkeypatch):
    server = FakeMcpServer({"query": _members_result()}, instructions="BUSINESS DEFINITIONS")
    llm = FakeLlm([tool_turn("query", ACTIVE_MEMBERS_SPEC), text_turn("ok")])
    run_agent(monkeypatch, llm, server, message="how many?", conversation_history=[
        {"role": "user", "content": "earlier question"}, {"role": "assistant", "content": "earlier answer"}])

    messages = llm.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "BUSINESS DEFINITIONS" in messages[0]["content"] and "ANSWERING RULES" in messages[0]["content"]
    assert [m["content"] for m in messages[1:]] == ["earlier question", "earlier answer", "how many?"]
    assert llm.calls[0]["temperature"] == 0
    assert all(h["x-api-key"] == "test-key" for h in server.headers)


def test_model_sees_only_the_exposed_tools(monkeypatch):
    server = FakeMcpServer({"query": _members_result()})
    llm = FakeLlm([tool_turn("query", ACTIVE_MEMBERS_SPEC), text_turn("ok")])
    run_agent(monkeypatch, llm, server)
    names = {tool["function"]["name"] for tool in llm.calls[0]["tools"]}
    assert names == set(agent.EXPOSED_TOOLS)
    assert not names & {"compile_query", "refresh_schema", "query_customers", "list_views", "glossary"}


def test_without_a_query_tool_everything_but_admin_tools_is_exposed():
    tools = [t for t in default_tools() if t["name"] != "query"]
    names = {t["name"] for t in agent.select_tools(tools)}
    assert "query_customers" in names and "compile_query" not in names and "refresh_schema" not in names


def test_gemini_gets_schemas_without_refs_others_get_the_original(monkeypatch):
    server = FakeMcpServer({"query": _members_result()})
    llm = FakeLlm([tool_turn("query", ACTIVE_MEMBERS_SPEC), text_turn("ok")])
    run_agent(monkeypatch, llm, server, provider="gemini")
    query_tool = next(t for t in llm.calls[0]["tools"] if t["function"]["name"] == "query")
    params = query_tool["function"]["parameters"]
    assert "$ref" not in json.dumps(params) and "$defs" not in params
    assert params["properties"]["spec"]["type"] == "object" and params["required"] == ["spec"]

    server = FakeMcpServer({"query": _members_result()})
    llm = FakeLlm([tool_turn("query", ACTIVE_MEMBERS_SPEC), text_turn("ok")])
    run_agent(monkeypatch, llm, server, provider="openrouter")
    query_tool = next(t for t in llm.calls[0]["tools"] if t["function"]["name"] == "query")
    assert "$defs" in query_tool["function"]["parameters"]


# ---------------------------------------------------------------- arguments


@pytest.mark.parametrize(
    ("spec", "expected_limit"),
    [
        ({"view": "customer_360_vw", "columns": ["email"]}, 500),
        ({"view": "customer_360_vw", "columns": ["email"], "limit": 10}, 10),
        ({"view": "customer_360_vw", "columns": ["email"], "limit": 9999}, 500),
        ({"view": "customer_360_vw", "columns": ["email"], "limit": 0}, 500),
        ({"view": "customer_360_vw", "metrics": [{"agg": "count"}]}, None),
        ({"view": "customer_360_vw", "metrics": [{"agg": "count"}], "limit": 7}, 7),
    ],
)
def test_list_questions_get_a_row_limit_aggregates_do_not(monkeypatch, spec, expected_limit):
    server = FakeMcpServer({"query": query_result([{"email": "a@x"}])})
    llm = FakeLlm([tool_turn("query", {"spec": spec}), text_turn("ok")])
    run_agent(monkeypatch, llm, server)
    assert server.calls("query")[0]["spec"].get("limit") == expected_limit


def test_inline_sql_params():
    sql = "x = @p0 AND y IN UNNEST(@p1) AND z > @p10 AND w = @p1x"
    out = agent.inline_sql_params(sql, {"p0": "it's", "p1": ["a", "b"], "p10": 5, "p1x": None})
    assert out == "x = 'it\\'s' AND y IN UNNEST(['a', 'b']) AND z > 5 AND w = NULL"
    assert agent.inline_sql_params("SELECT 1", None) == "SELECT 1"
    assert agent.inline_sql_params("a = @p0", {"p0": True}) == "a = TRUE"


# ---------------------------------------------------------------- tool errors


def test_bad_spec_text_goes_back_to_the_model_which_then_succeeds(monkeypatch):
    server = FakeMcpServer({"query": [ToolError("Invalid request: Unknown column 'x' in customer_360_vw."), _members_result()]})
    llm = FakeLlm([tool_turn("query", ACTIVE_MEMBERS_SPEC), tool_turn("query", ACTIVE_MEMBERS_SPEC, "call-2"), text_turn("ok")])
    events = run_agent(monkeypatch, llm, server)

    tool_message = llm.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["content"].startswith("ERROR: Invalid request: Unknown column 'x'")
    assert of_type(events, "text") and events[-1]["billable"] is True
    assert len(of_type(events, "rows")) == 1


def test_unknown_tool_is_not_sent_to_the_server(monkeypatch):
    server = FakeMcpServer()
    llm = FakeLlm([tool_turn("compile_query", {"spec": {}}), text_turn("ok")])
    run_agent(monkeypatch, llm, server)
    assert server.calls() == []
    assert llm.calls[1]["messages"][-1]["content"].startswith("ERROR: Unknown tool: 'compile_query'")


def test_giving_up_after_too_many_rounds_is_not_billed(monkeypatch):
    server = FakeMcpServer({"query": lambda arguments: ToolError("still wrong")})
    llm = FakeLlm([tool_turn("query", ACTIVE_MEMBERS_SPEC)] * agent.AUTOCARE_MAX_TOOL_ROUNDS)
    events = run_agent(monkeypatch, llm, server)
    assert "wasn't able to finish" in of_type(events, "text")[0]["content"]
    assert events[-1]["billable"] is False and events[-1]["confidence"] == 0.2


# ---------------------------------------------------------------- empty replies and model errors


def test_empty_reply_is_retried_once_with_more_room_when_it_ran_out_of_tokens(monkeypatch):
    server = FakeMcpServer({"query": _members_result()})
    llm = FakeLlm([empty_turn("length"), tool_turn("query", ACTIVE_MEMBERS_SPEC), text_turn("ok")])
    events = run_agent(monkeypatch, llm, server)
    assert llm.calls[1]["max_tokens"] == 2 * llm.calls[0]["max_tokens"]
    assert llm.calls[1]["messages"][-1]["content"].startswith("Your previous reply was empty")
    assert events[-1]["billable"] is True


def test_two_empty_replies_give_a_plain_failure_message(monkeypatch):
    llm = FakeLlm([empty_turn(), empty_turn()])
    events = run_agent(monkeypatch, llm, FakeMcpServer())
    assert "empty response" in of_type(events, "text")[0]["content"]
    assert events[-1]["billable"] is False


def test_model_error_becomes_an_error_event(monkeypatch):
    llm = FakeLlm([RuntimeError("401 bad api key")])
    events = run_agent(monkeypatch, llm, FakeMcpServer())
    assert of_type(events, "error")[0]["content"].startswith("Couldn't get a response from the model: 401")
    assert events[-1] == {"type": "done", "billable": False, "confidence": 0.0, "tables_used": []}


def test_text_only_answer_is_billed_with_lower_confidence(monkeypatch):
    llm = FakeLlm([text_turn("## Advice\nTry a **referral** offer.")])
    events = run_agent(monkeypatch, llm, FakeMcpServer())
    assert of_type(events, "text")[0]["content"] == "Advice\nTry a **referral** offer."
    assert events[-1]["billable"] is True and events[-1]["confidence"] == 0.8
    assert not of_type(events, "rows")


# ---------------------------------------------------------------- service failures


def test_service_down_before_any_result_raises_so_the_caller_can_fall_back(monkeypatch):
    server = FakeMcpServer({"query": [HttpStatus(503), HttpStatus(503)]})
    llm = FakeLlm([tool_turn("query", ACTIVE_MEMBERS_SPEC)])
    with pytest.raises(McpUnavailable):
        run_agent(monkeypatch, llm, server)


def test_service_down_after_a_first_result_is_an_error_event_not_an_exception(monkeypatch):
    server = FakeMcpServer({"query": [_members_result(), HttpStatus(500)]})
    llm = FakeLlm([tool_turn("query", ACTIVE_MEMBERS_SPEC), tool_turn("query", ACTIVE_MEMBERS_SPEC, "call-2")])
    events = run_agent(monkeypatch, llm, server)
    assert of_type(events, "rows") and "stopped responding" in of_type(events, "error")[0]["content"]
    assert events[-1]["billable"] is False


def test_missing_key_raises_unavailable(monkeypatch):
    from types import SimpleNamespace

    from app.modules.chat_bot import autocare_client

    monkeypatch.setattr(autocare_client, "get_settings", lambda: SimpleNamespace(AUTOCARE_MCP_URL="http://x", AUTOCARE_MCP_KEY=""))

    async def go():
        return [e async for e in agent.stream_autocare_query(provider="openrouter", model="m", api_key="k", message="q")]

    import asyncio

    with pytest.raises(McpUnavailable, match="AUTOCARE_MCP_KEY"):
        asyncio.run(go())


# ---------------------------------------------------------------- tables and notes


def test_long_list_shows_500_rows_and_adds_the_partial_note(monkeypatch):
    rows = [{"client_id": f"c{i}", "full_name": f"N{i}"} for i in range(500)]
    server = FakeMcpServer({"query": query_result(rows, total_rows=91516, view="session_360_vw")})
    llm = FakeLlm([tool_turn("query", {"spec": {"view": "session_360_vw", "columns": ["client_id", "full_name"]}}), text_turn("Many visits.")])
    events = run_agent(monkeypatch, llm, server)
    table = of_type(events, "rows")[0]
    assert (len(table["data"]), table["total_rows"], table["truncated"]) == (500, 91516, True)
    text = of_type(events, "text")[0]["content"]
    assert "the first 500 of 91,516 matching rows" in text and CUSTOMER_LEVEL_ACTIVE_NOTE not in text


def test_model_gets_a_short_copy_without_sql_and_with_a_row_sample(monkeypatch):
    rows = [{"client_id": f"c{i}"} for i in range(200)]
    server = FakeMcpServer({"query": query_result(rows, total_rows=200, sql="SECRET SQL", params={"p0": 1})})
    llm = FakeLlm([tool_turn("query", {"spec": {"view": "customer_360_vw", "columns": ["client_id"]}}), text_turn("ok")])
    run_agent(monkeypatch, llm, server)
    seen = json.loads(llm.calls[1]["messages"][-1]["content"])
    assert "sql" not in seen and "params" not in seen
    assert len(seen["rows"]) == 60 and seen["rows_note"] == "first 60 of 200 rows"
    assert seen["total_rows"] == 200


def test_chart_for_a_time_series(monkeypatch):
    weeks = [{"week": "2026-09-28", "visits": 12}, {"week": "2026-10-05", "visits": 9}]
    server = FakeMcpServer({"query": query_result(weeks, view="session_360_vw")})
    llm = FakeLlm([tool_turn("query", {"spec": {"view": "session_360_vw", "metrics": [{"agg": "count", "alias": "visits"}]}}), text_turn("ok")])
    events = run_agent(monkeypatch, llm, server)
    assert of_type(events, "rows")[0]["viz"]["charts"][0]["type"] == "line"


def test_customer_profile_result_becomes_a_small_table_without_a_drill_spec(monkeypatch):
    customer = {"full_name": "Agustin Negron", "email": "a@x.com", "customer_status": "Prospect", "vehicle_count": 1, "stripe_customer_id": "cus_1"}
    server = FakeMcpServer({"customer_profile": {"matches": 1, "customers": [customer], "subscriptions": []}})
    llm = FakeLlm([tool_turn("customer_profile", {"email": "a@x.com"}), text_turn("He never subscribed.")])
    events = run_agent(monkeypatch, llm, server)
    table = of_type(events, "rows")[0]
    assert table["columns"] == ["full_name", "email", "customer_status"]
    assert table["spec"] is None and not of_type(events, "sql")
    assert CUSTOMER_LEVEL_ACTIVE_NOTE not in of_type(events, "text")[0]["content"]


@pytest.mark.parametrize(
    ("view", "filters", "expected"),
    [
        ("customer_360_vw", [{"column": "has_active_subscription", "op": "is_true"}], True),
        ("customer_360_vw", [{"column": "has_active_subscription", "op": "eq", "value": True}, {"column": "tier_name", "op": "eq", "value": "basic"}], True),
        ("customer_360_vw", [{"column": "has_active_subscription", "op": "is_false"}], False),
        ("customer_360_vw", [{"column": "has_active_subscription", "op": "is_true"}, {"column": "email", "op": "eq", "value": "a@x"}], False),
        ("customer_360_vw", [{"any_of": [{"column": "has_active_subscription", "op": "is_true"}]}], False),
        ("customer_360_vw", [{"column": "has_visited", "op": "is_false"}], False),
        ("subscription_360_vw", [{"column": "is_active_subscription", "op": "is_true"}], False),
        ("subscription_360_vw", [{"column": "has_active_subscription", "op": "is_true"}], False),
    ],
)
def test_customer_level_note_rule(view, filters, expected):
    assert agent.is_customer_level_active_spec(view, {"filters": filters}) is expected


def test_customer_level_note_rule_handles_missing_spec():
    assert agent.is_customer_level_active_spec("customer_360_vw", None) is False
    assert agent.is_customer_level_active_spec(None, {"filters": []}) is False
