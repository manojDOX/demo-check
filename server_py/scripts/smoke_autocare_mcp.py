"""Live, read-only check of the AutoCare MCP server and of the chatbot's new engine.

    cd server_py
    AUTOCARE_MCP_KEY=<key> python -m scripts.smoke_autocare_mcp
    AUTOCARE_MCP_KEY=<key> SA_KEY_FILE=<service-account.json> python -m scripts.smoke_autocare_mcp

1. Connection: health, server instructions, tool list, the tools the chatbot exposes.
2. Ten question chains (a starting question and its drill-down follow-ups). Each step is counted two ways:
   by the MCP server from a `query` spec, and (when SA_KEY_FILE is set) by independent BigQuery SQL written
   from the same column definitions. A difference is printed, never hidden.
3. The chatbot engine itself (autocare_agent) against the live server, with a scripted model.

Nothing is written anywhere. The key is read from the environment and never printed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://user:password@localhost/smoke")  # Settings needs it; never used

URL = os.environ.get("AUTOCARE_MCP_URL", "https://autocare-mcp-199378855169.us-central1.run.app/mcp").rstrip("/")
KEY = os.environ.get("AUTOCARE_MCP_KEY", "").strip()
SA_KEY_FILE = os.environ.get("SA_KEY_FILE", "").strip()
PROJECT = "alpine-province-504014-a9"
DATASET = f"`{PROJECT}.marketing_analytics_ss"
TODAY = "CURRENT_DATE('America/Puerto_Rico')"


def pr_date(column: str) -> str:
    return f"DATE({column}, 'America/Puerto_Rico')"


def last_n(column: str, n: int, unit: str) -> str:
    return f"{pr_date(column)} BETWEEN DATE_SUB({TODAY}, INTERVAL {n} {unit.upper()}) AND {TODAY}"


def next_n(column: str, n: int, unit: str) -> str:
    return f"{pr_date(column)} BETWEEN {TODAY} AND DATE_ADD({TODAY}, INTERVAL {n} {unit.upper()})"


def flt(column: str, op: str, value=None, nulls: bool = False) -> dict:
    item: dict = {"column": column, "op": op}
    if value is not None:
        item["value"] = value
    if nulls:
        item["include_nulls"] = True
    return item


@dataclass
class Step:
    label: str
    filters: list[dict]
    sql: str  # a SQL condition equal to the filters, written independently
    rollups: list[dict] = field(default_factory=list)


@dataclass
class Chain:
    title: str
    view: str
    steps: list[Step]
    # SQL FROM + count expression. {where} is the cumulative condition.
    sql_template: str


CUSTOMERS = f"SELECT COUNT(*) AS n FROM {DATASET}.customer_360_vw` c WHERE {{where}}"
CANCELLED_SUBS = (
    f"WITH s AS (SELECT subscription_id, ANY_VALUE(client_id) AS client_id, ANY_VALUE(is_cancelled_subscription) AS cancelled, "
    f"ANY_VALUE(COALESCE(canceled_at, ended_at)) AS cancelled_at, ANY_VALUE(tier_name) AS tier_name "
    f"FROM {DATASET}.subscription_360_vw` GROUP BY subscription_id) "
    # LEFT JOIN: a few cancelled subscriptions have no linked customer, and the MCP count keeps them
    # until a `customer.` filter is added (an inner join would drop them from the first step).
    f"SELECT COUNT(*) AS n FROM s LEFT JOIN {DATASET}.customer_360_vw` c USING (client_id) WHERE {{where}}"
)
VISITS_90D = (
    f"(SELECT COUNT(*) FROM {DATASET}.session_360_vw` x WHERE x.client_id = c.client_id AND "
    f"{last_n('x.session_date', 90, 'day')}) >= 3"
)

CHAINS = [
    Chain("1. Inactive 60+ days (or never) with a phone", "customer_360_vw", [
        Step("start", [flt("phone_number", "not_null"), flt("days_since_last_visit", "gt", 60, nulls=True)],
             "c.phone_number IS NOT NULL AND (c.days_since_last_visit > 60 OR c.days_since_last_visit IS NULL)"),
        Step("has an active subscription", [flt("has_active_subscription", "is_true")], "c.has_active_subscription"),
        Step("is on Premium", [flt("tier_name", "eq", "premium")], "c.tier_name = 'Unlimited Premium Wash'"),
    ], CUSTOMERS),
    Chain("2. Customers with an active subscription", "customer_360_vw", [
        Step("start", [flt("has_active_subscription", "is_true")], "c.has_active_subscription"),
        Step("on Basic", [flt("tier_name", "eq", "basic")], "c.tier_name = 'Unlimited Basic Wash'"),
        Step("not visited in 30 days (or never)", [flt("days_since_last_visit", "gt", 30, nulls=True)],
             "(c.days_since_last_visit > 30 OR c.days_since_last_visit IS NULL)"),
        Step("more than one vehicle", [flt("vehicle_count", "gt", 1)], "c.vehicle_count > 1"),
    ], CUSTOMERS),
    Chain("3. Subscriptions cancelled in the last 90 days", "subscription_360_vw", [
        Step("start", [flt("is_cancelled_subscription", "is_true"), flt("cancelled_or_ended_at", "in_last", {"n": 90, "unit": "day"})],
             f"s.cancelled AND {last_n('s.cancelled_at', 90, 'day')}"),
        Step("customer has more than 10 visits", [flt("customer.total_sessions", "gt", 10)], "c.total_sessions > 10"),
        Step("was on Premium", [flt("tier_name", "eq", "premium")], "s.tier_name = 'Unlimited Premium Wash'"),
        Step("customer has an email", [flt("customer.email", "not_null")], "c.email IS NOT NULL"),
    ], CANCELLED_SUBS),
    Chain("4. Delinquent payment", "customer_360_vw", [
        Step("start", [flt("is_payment_delinquent", "is_true")], "c.is_payment_delinquent"),
        Step("visited in the last 30 days", [flt("days_since_last_visit", "lte", 30)], "c.days_since_last_visit <= 30"),
        Step("pays more than 30 a month", [flt("current_mrr", "gt", 30)], "c.current_mrr > 30"),
    ], CUSTOMERS),
    Chain("5. Signed up in the last 6 months", "customer_360_vw", [
        Step("start", [flt("customer_created_date", "in_last", {"n": 6, "unit": "month"})], last_n("c.customer_created_date", 6, "month")),
        Step("never visited", [flt("has_visited", "is_false")], "NOT c.has_visited"),
        Step("active subscription", [flt("has_active_subscription", "is_true")], "c.has_active_subscription"),
    ], CUSTOMERS),
    Chain("6. Visited more than one location", "customer_360_vw", [
        Step("start", [flt("total_locations_visited", "gt", 1)], "c.total_locations_visited > 1"),
        Step("visited in the last 14 days", [flt("days_since_last_visit", "lte", 14)], "c.days_since_last_visit <= 14"),
        Step("on a Road Assistance plan", [flt("tier_name", "eq", "connect")], "LOWER(c.tier_name) LIKE '%road assistance%'"),
    ], CUSTOMERS),
    Chain("7. Subscription renews in the next 7 days", "customer_360_vw", [
        Step("start", [flt("has_active_subscription", "is_true"), flt("current_period_end", "in_next", {"n": 7, "unit": "day"})],
             f"c.has_active_subscription AND {next_n('c.current_period_end', 7, 'day')}"),
        Step("not visited in 30 days (or never)", [flt("days_since_last_visit", "gt", 30, nulls=True)],
             "(c.days_since_last_visit > 30 OR c.days_since_last_visit IS NULL)"),
        Step("on a yearly plan", [flt("subscription_interval", "eq", "year")], "c.subscription_interval = 'year'"),
    ], CUSTOMERS),
    Chain("8. Visited at least 20 times", "customer_360_vw", [
        Step("start", [flt("total_sessions", "gte", 20)], "c.total_sessions >= 20"),
        Step("no active subscription", [flt("has_active_subscription", "is_false")], "NOT c.has_active_subscription"),
        Step("has a vehicle", [flt("has_vehicle", "is_true")], "c.has_vehicle"),
    ], CUSTOMERS),
    Chain("9. Has a vehicle, no active subscription", "customer_360_vw", [
        Step("start", [flt("has_vehicle", "is_true"), flt("has_active_subscription", "is_false")], "c.has_vehicle AND NOT c.has_active_subscription"),
        Step("visited in the last 90 days", [flt("days_since_last_visit", "lte", 90)], "c.days_since_last_visit <= 90"),
        Step("3 or more visits in the last 90 days", [flt("visits_90d", "gte", 3)], VISITS_90D, rollups=[{
            "alias": "visits_90d", "relation": "sessions", "agg": "count",
            "filters": [flt("session_date", "in_last", {"n": 90, "unit": "day"})]}]),
    ], CUSTOMERS),
    Chain("10. On a trial subscription", "customer_360_vw", [
        Step("start", [flt("current_subscription_status", "eq", "trialing")], "c.current_subscription_status = 'trialing'"),
        Step("visited at least once", [flt("has_visited", "is_true")], "c.has_visited"),
        Step("has an email and a phone", [flt("email", "not_null"), flt("phone_number", "not_null")], "c.email IS NOT NULL AND c.phone_number IS NOT NULL"),
    ], CUSTOMERS),
]


class Mcp:
    def __init__(self):
        self.http = httpx.Client(timeout=120, headers={
            "X-API-Key": KEY, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        self.n = 0

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        reply = self.http.post(URL, json={"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})
        reply.raise_for_status()
        body = reply.json()
        if "error" in body:
            raise RuntimeError(body["error"])
        return body["result"]

    def count(self, view: str, filters: list[dict], rollups: list[dict]) -> int:
        spec: dict = {"view": view, "filters": filters, "metrics": [{"agg": "count", "alias": "n"}]}
        if rollups:
            spec["rollups"] = rollups
        result = self.rpc("tools/call", {"name": "query", "arguments": {"spec": spec}})
        if result.get("isError"):
            raise RuntimeError(result["content"][0]["text"])
        return int(result["structuredContent"]["rows"][0]["n"])


def bigquery_client():
    if not SA_KEY_FILE:
        return None
    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw = Path(SA_KEY_FILE).read_bytes().decode("utf-8").replace("\xa0", " ")  # some copies hold non-breaking spaces
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/bigquery"])
    return bigquery.Client(project=PROJECT, credentials=credentials)


def part_connection(mcp: Mcp) -> bool:
    print("1. CONNECTION")
    health = httpx.get(URL.rsplit("/mcp", 1)[0] + "/health", timeout=120)
    print(f"   health: HTTP {health.status_code} {health.text[:100]}")
    unauthorized = httpx.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=120)
    print(f"   without a key: HTTP {unauthorized.status_code} (expected 401)")
    started = time.time()
    instructions = mcp.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}})
    tools = mcp.rpc("tools/list")["tools"]
    names = {t["name"] for t in tools}
    from app.modules.chat_bot.autocare_agent import EXPOSED_TOOLS

    missing = [name for name in EXPOSED_TOOLS if name not in names]
    print(f"   instructions: {len(instructions.get('instructions', '')):,} chars | tools: {len(tools)} | {time.time() - started:.1f}s")
    print(f"   tools the chatbot exposes that the server lacks: {missing or 'none'}")
    return unauthorized.status_code == 401 and not missing and bool(instructions.get("instructions"))


def part_chains(mcp: Mcp, bq, only: set[str]) -> list[str]:
    print("\n2. QUESTION CHAINS (MCP count | BigQuery count)")
    problems: list[str] = []
    matched = total = 0
    for chain in CHAINS:
        if only and chain.title.split(".")[0] not in only:
            continue
        print(f"\n   {chain.title}")
        filters: list[dict] = []
        rollups: list[dict] = []
        conditions: list[str] = []
        for step in chain.steps:
            filters += step.filters
            rollups += step.rollups
            conditions.append(step.sql)
            try:
                mcp_count = mcp.count(chain.view, filters, rollups)
            except Exception as error:  # noqa: BLE001
                print(f"     {step.label:42s} MCP ERROR: {str(error)[:120]}")
                problems.append(f"{chain.title} / {step.label}: MCP error")
                continue
            if bq is None:
                print(f"     {step.label:42s} {mcp_count:>8,}")
                continue
            sql = chain.sql_template.format(where=" AND ".join(f"({c})" for c in conditions))
            bq_count = list(bq.query(sql).result())[0]["n"]
            total += 1
            same = mcp_count == bq_count
            matched += same
            note = "ok" if same else f"DIFFERENT by {mcp_count - bq_count:+,}"
            print(f"     {step.label:42s} {mcp_count:>8,} | {bq_count:>8,}  {note}")
            if not same:
                problems.append(f"{chain.title} / {step.label}: MCP {mcp_count:,} vs SQL {bq_count:,}")
    if bq is not None:
        print(f"\n   matched {matched} of {total} steps")
    else:
        print("\n   (set SA_KEY_FILE to compare with BigQuery)")
    return problems


async def part_agent() -> bool:
    print("\n3. CHATBOT ENGINE (autocare_agent with a scripted model)")
    from app.modules.chat_bot import autocare_agent, autocare_client

    autocare_client.reset_catalog_cache()
    turns = [
        {"content": None, "tool_calls": [{"id": "1", "name": "query", "arguments": {"spec": {
            "view": "subscription_360_vw", "filters": [flt("is_active_subscription", "is_true")],
            "metrics": [{"agg": "count", "alias": "active_memberships"}]}}}], "raw_message": {"role": "assistant", "content": ""}},
        {"content": "There are active memberships.", "tool_calls": None, "raw_message": {"role": "assistant", "content": "x"}},
    ]

    async def scripted(provider, model, api_key, messages, tools, max_tokens=3000, temperature=0.2):
        return turns.pop(0)

    autocare_agent.call_llm_with_tools = scripted
    events = [e async for e in autocare_agent.stream_autocare_query(provider="openrouter", model="m", api_key="k", message="active memberships?")]
    rows = next((e for e in events if e["type"] == "rows"), None)
    done = events[-1]
    print(f"   rows: {rows['data'] if rows else None} | done: billable={done.get('billable')} tables={done.get('tables_used')}")
    return bool(rows) and done["type"] == "done" and done["billable"]


def main() -> int:
    if not KEY:
        print("Set AUTOCARE_MCP_KEY first.")
        return 2
    only = {arg for arg in sys.argv[1:] if arg.isdigit()}
    mcp = Mcp()
    ok = part_connection(mcp)
    problems = part_chains(mcp, bigquery_client(), only)
    ok = asyncio.run(part_agent()) and ok
    print("\nRESULT:", "all good" if ok and not problems else "SEE ABOVE")
    for line in problems:
        print("  -", line)
    return 0 if ok and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
