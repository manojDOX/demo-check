"""The old SQL engine is kept as the fallback. These tests keep it working after its shared helpers moved
to answer_utils and its drill-down code was removed."""

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.modules.chat_bot import prompts, sql_agent
from app.modules.chat_bot.answer_utils import CUSTOMER_LEVEL_ACTIVE_NOTE

CV = "`marketing_analytics_ss.customer_360_vw`"
SV = "`marketing_analytics_ss.subscription_360_vw`"


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (f"SELECT COUNT(*) AS active_members FROM {CV} WHERE has_active_subscription = TRUE", True),
        (f"select count(*) from {CV} where has_active_subscription = true and tier_name = 'x'", True),
        (f"SELECT client_id, full_name FROM {CV} WHERE has_active_subscription = TRUE", True),
        (f"SELECT COUNT(*) FROM {CV} WHERE has_active_subscription IS TRUE", True),
        (f"SELECT COUNT(DISTINCT subscription_id) FROM {SV} WHERE is_active_subscription = TRUE", False),
        (f"SELECT COUNT(*) FROM {CV} WHERE has_active_subscription = FALSE", False),
        (f"SELECT COUNT(*) FROM {CV} WHERE has_vehicle AND NOT has_active_subscription", False),
        (f"SELECT COUNT(*) FROM {CV} WHERE NOT COALESCE(has_active_subscription, FALSE)", False),
        (f"SELECT customer_status FROM {CV} WHERE LOWER(email) = LOWER('a@b.com')", False),
        (f"SELECT client_id FROM {CV} WHERE has_active_subscription = TRUE AND LOWER(email) = LOWER('a@b.com')", False),
        (f"SELECT COUNT(*) FROM {CV}", False),
        ("", False),
    ],
)
def test_customer_level_note_detection_on_sql(sql, expected):
    assert sql_agent._is_customer_level_active_query(sql) is expected


def test_old_engine_no_longer_has_drill_down():
    assert "drill" not in inspect.signature(sql_agent.stream_single_query).parameters
    assert "drill" not in inspect.signature(prompts.build_sql_generation_system_prompt).parameters
    prompt = prompts.build_sql_generation_system_prompt("how many?")
    assert "<DRILL_DOWN>" not in prompt and "</USER_PROMPT>\n\n<TABLE_GUIDE>" in prompt


def test_shared_helpers_are_the_same_objects_in_both_engines():
    from app.modules.chat_bot import answer_utils

    assert sql_agent.CUSTOMER_LEVEL_ACTIVE_NOTE is answer_utils.CUSTOMER_LEVEL_ACTIVE_NOTE
    assert sql_agent._strip_markdown_formatting is answer_utils.strip_markdown_formatting
    assert sql_agent._infer_charts is answer_utils.infer_charts


class FakeGoogleMcp:
    """Stands in for the Google BigQuery MCP client the old engine uses."""

    def __init__(self, *args, **kwargs):
        self.executed: list = []

    async def list_tools(self):
        return [{"name": "execute_sql_readonly", "inputSchema": {"type": "object"}}]

    async def call_tool(self, name, arguments):
        self.executed.append(arguments["query"])
        return {
            "structuredContent": {
                "schema": {"fields": [{"name": "active_members", "type": "INTEGER"}]},
                "rows": [{"f": [{"v": "10577"}]}],
                "totalRows": "1",
            }
        }

    async def aclose(self):
        pass


def _run_old_engine(monkeypatch, sql: str) -> list[dict]:
    async def min_dates(db, connection):
        return None, None

    turns = [
        {"content": None, "tool_calls": [{"id": "1", "name": "execute_sql_readonly", "arguments": {"query": sql}}],
         "raw_message": {"role": "assistant", "content": ""}},
        {"content": "There are 10,577 customers.", "tool_calls": None, "raw_message": {"role": "assistant", "content": "x"}},
    ]

    async def fake_llm(provider, model, api_key, messages, tools, max_tokens=3000, temperature=0.2):
        return turns.pop(0)

    monkeypatch.setattr(sql_agent, "BigQueryMCPClient", FakeGoogleMcp)
    monkeypatch.setattr(sql_agent, "call_llm_with_tools", fake_llm)
    monkeypatch.setattr(sql_agent.data_availability, "get_min_dates", min_dates)

    async def go():
        return [
            event
            async for event in sql_agent.stream_single_query(
                db=None, user_id="u", connection=SimpleNamespace(credentials="{}", project_id="p"), client_id=None,
                provider="openrouter", model="m", api_key="k", message="how many active members?", conversation_history=[],
            )
        ]

    return asyncio.run(go())


def test_old_engine_still_answers_and_adds_the_customer_note(monkeypatch):
    events = _run_old_engine(monkeypatch, f"SELECT COUNT(*) AS active_members FROM {CV} WHERE has_active_subscription = TRUE")
    text = next(e for e in events if e["type"] == "text")["content"]
    assert text.startswith("There are 10,577 customers.") and text.endswith(CUSTOMER_LEVEL_ACTIVE_NOTE)
    rows = next(e for e in events if e["type"] == "rows")
    # The old engine returns BigQuery REST values as text; that is how it always worked.
    assert rows["data"] == [{"active_members": "10577"}] and rows["total_rows"] == 1
    assert events[-1]["type"] == "done" and events[-1]["billable"] is True


def test_old_engine_adds_no_note_to_a_membership_count(monkeypatch):
    events = _run_old_engine(monkeypatch, f"SELECT COUNT(DISTINCT subscription_id) FROM {SV} WHERE is_active_subscription = TRUE")
    assert CUSTOMER_LEVEL_ACTIVE_NOTE not in next(e for e in events if e["type"] == "text")["content"]
