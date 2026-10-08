"""Test doubles: a fake AutoCare MCP server (httpx.MockTransport) and a scripted fake model."""

from __future__ import annotations

import asyncio
import json

import httpx

from app.modules.chat_bot import autocare_agent
from app.modules.chat_bot.autocare_client import AutoCareClient

TOOL_NAMES = [
    "list_views", "describe_view", "glossary", "query", "distinct_values", "customer_profile", "churn_rate",
    "engagement_quintiles", "upsell_uplift", "data_overview", "query_customers", "query_subscriptions",
    "query_sessions", "query_locations", "query_daily_metrics", "compile_query", "refresh_schema",
]


def default_tools() -> list[dict]:
    spec_schema = {
        "properties": {"spec": {"$ref": "#/$defs/QuerySpec"}},
        "required": ["spec"],
        "type": "object",
        "additionalProperties": False,
        "$defs": {
            "QuerySpec": {"type": "object", "properties": {"filters": {"type": "array", "items": {"$ref": "#/$defs/Filter"}}}},
            "Filter": {"type": "object", "properties": {"column": {"type": "string"}}},
        },
    }
    plain = {"properties": {"email": {"type": "string", "description": "Customer email"}}, "type": "object"}
    return [
        {"name": name, "description": f"{name} tool", "inputSchema": spec_schema if name.startswith("query") else plain}
        for name in TOOL_NAMES
    ]


class ToolError:
    """A tools/call result with isError = true (a bad spec)."""

    def __init__(self, text: str):
        self.text = text


class HttpStatus:
    def __init__(self, status: int):
        self.status = status


class FakeMcpServer:
    """Speaks the part of MCP the client uses. `results` maps a tool name to a result dict, a ToolError, an
    HttpStatus, an exception, a callable(arguments), or a list of those (used one per call)."""

    def __init__(self, results: dict | None = None, tools: list[dict] | None = None, instructions: str = "SERVER INSTRUCTIONS"):
        self.results = results or {}
        self.tools = default_tools() if tools is None else tools
        self.instructions = instructions
        self.requests: list[tuple[str, dict]] = []
        self.headers: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def calls(self, tool: str | None = None) -> list[dict]:
        return [
            params["arguments"]
            for method, params in self.requests
            if method == "tools/call" and (tool is None or params["name"] == tool)
        ]

    def _rpc(self, request_id, result) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_id, "result": result})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method, params = body["method"], body.get("params") or {}
        self.requests.append((method, params))
        self.headers.append(dict(request.headers))
        if method == "initialize":
            return self._rpc(body["id"], {"protocolVersion": "2025-06-18", "instructions": self.instructions})
        if method == "tools/list":
            return self._rpc(body["id"], {"tools": self.tools})
        if method == "tools/call":
            outcome = self.results.get(params["name"])
            if isinstance(outcome, list):
                outcome = outcome.pop(0)
            if callable(outcome) and not isinstance(outcome, (ToolError, HttpStatus)):
                outcome = outcome(params["arguments"])
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, HttpStatus):
                return httpx.Response(outcome.status, text="service error")
            if isinstance(outcome, ToolError):
                return self._rpc(body["id"], {"content": [{"type": "text", "text": outcome.text}], "isError": True})
            if outcome is None:
                return self._rpc(body["id"], {"content": [{"type": "text", "text": "Unknown tool"}], "isError": True})
            return self._rpc(
                body["id"],
                {"content": [{"type": "text", "text": json.dumps(outcome)}], "structuredContent": outcome, "isError": False},
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "no method"}})


def query_result(rows: list[dict], *, view="customer_360_vw", total_rows=None, sql="SELECT 1", params=None) -> dict:
    columns = list(rows[0].keys()) if rows else []
    return {
        "view": view,
        "mode": "rows",
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "total_rows": len(rows) if total_rows is None else total_rows,
        "truncated": False,
        "sql": sql,
        "params": params or {},
        "notes": [],
    }


class FakeLlm:
    """Replaces autocare_agent.call_llm_with_tools. `turns` are returned in order; an Exception is raised."""

    def __init__(self, turns: list):
        self.turns = list(turns)
        self.calls: list[dict] = []

    async def __call__(self, provider, model, api_key, messages, tools, max_tokens=3000, temperature=0.2):
        self.calls.append(
            {
                "provider": provider,
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


def tool_turn(name: str, arguments: dict, call_id: str = "call-1") -> dict:
    return {
        "content": None,
        "tool_calls": [{"id": call_id, "name": name, "arguments": arguments}],
        "raw_message": {"role": "assistant", "content": ""},
    }


def text_turn(text: str) -> dict:
    return {"content": text, "tool_calls": None, "raw_message": {"role": "assistant", "content": text}}


def empty_turn(finish_reason: str = "stop") -> dict:
    return {"content": None, "tool_calls": None, "raw_message": {"role": "assistant", "content": ""}, "finish_reason": finish_reason}


async def _collect(server: FakeMcpServer, **kwargs) -> list[dict]:
    client = AutoCareClient(url="http://mcp.test/mcp", key="test-key", transport=server.transport(), retry_delay=0)
    try:
        return [
            event
            async for event in autocare_agent.stream_autocare_query(
                provider=kwargs.pop("provider", "openrouter"),
                model="model",
                api_key="llm-key",
                message=kwargs.pop("message", "a question"),
                client=client,
                **kwargs,
            )
        ]
    finally:
        await client.aclose()


def run_agent(monkeypatch, llm: FakeLlm, server: FakeMcpServer, **kwargs) -> list[dict]:
    monkeypatch.setattr(autocare_agent, "call_llm_with_tools", llm)
    return asyncio.run(_collect(server, **kwargs))


def of_type(events: list[dict], kind: str) -> list[dict]:
    return [event for event in events if event["type"] == kind]
