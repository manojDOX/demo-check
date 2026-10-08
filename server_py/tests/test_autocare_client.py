import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.modules.chat_bot import autocare_client
from app.modules.chat_bot.autocare_client import AutoCareClient, McpToolError, McpUnavailable

from .fakes import FakeMcpServer, HttpStatus, ToolError


def _client(server: FakeMcpServer, **kwargs) -> AutoCareClient:
    return AutoCareClient(url="http://mcp.test", key="secret-key", transport=server.transport(), retry_delay=0, **kwargs)


def _run(coro):
    return asyncio.run(coro)


def test_sends_the_key_and_reads_instructions_and_tools():
    server = FakeMcpServer(instructions="DEFINITIONS")

    async def go():
        async with _client(server) as client:
            return await client.initialize(), await client.list_tools()

    instructions, tools = _run(go())
    assert instructions == "DEFINITIONS"
    assert len(tools) == 17
    assert all(h["x-api-key"] == "secret-key" for h in server.headers)
    assert all(h["content-type"] == "application/json" for h in server.headers)


def test_url_always_ends_with_mcp():
    assert AutoCareClient(url="http://mcp.test", key="k").url == "http://mcp.test/mcp"
    assert AutoCareClient(url="http://mcp.test/mcp/", key="k").url == "http://mcp.test/mcp"


def test_call_tool_returns_structured_content():
    server = FakeMcpServer({"query": {"rows": [{"n": 1}], "total_rows": 1}})

    async def go():
        async with _client(server) as client:
            return await client.call_tool("query", {"spec": {}})

    assert _run(go()) == {"rows": [{"n": 1}], "total_rows": 1}


def test_is_error_result_becomes_a_tool_error_with_the_server_text():
    server = FakeMcpServer({"query": ToolError("Unknown column 'x' in customer_360_vw")})

    async def go():
        async with _client(server) as client:
            await client.call_tool("query", {"spec": {}})

    with pytest.raises(McpToolError, match="Unknown column 'x'"):
        _run(go())


def test_wrong_key_is_unavailable_and_not_retried():
    server = FakeMcpServer({"query": HttpStatus(401)})

    async def go():
        async with _client(server) as client:
            await client.call_tool("query", {})

    with pytest.raises(McpUnavailable, match="rejected the API key"):
        _run(go())
    assert len(server.calls("query")) == 1


def test_one_transient_failure_is_retried_once():
    server = FakeMcpServer({"query": [HttpStatus(503), {"rows": [], "total_rows": 0}]})

    async def go():
        async with _client(server) as client:
            return await client.call_tool("query", {})

    assert _run(go())["total_rows"] == 0
    assert len(server.calls("query")) == 2


def test_two_transient_failures_are_unavailable():
    server = FakeMcpServer({"query": [HttpStatus(503), HttpStatus(502)]})

    async def go():
        async with _client(server) as client:
            await client.call_tool("query", {})

    with pytest.raises(McpUnavailable, match="HTTP 502"):
        _run(go())


def test_other_server_errors_are_unavailable_without_retry():
    server = FakeMcpServer({"query": HttpStatus(500)})

    async def go():
        async with _client(server) as client:
            await client.call_tool("query", {})

    with pytest.raises(McpUnavailable, match="HTTP 500"):
        _run(go())
    assert len(server.calls("query")) == 1


def test_timeout_is_unavailable():
    server = FakeMcpServer({"query": [httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow")]})

    async def go():
        async with _client(server) as client:
            await client.call_tool("query", {})

    with pytest.raises(McpUnavailable, match="ReadTimeout"):
        _run(go())


def test_reply_that_is_not_json_is_unavailable():
    def handler(request):
        return httpx.Response(200, text="<html>gateway</html>")

    async def go():
        client = AutoCareClient(url="http://mcp.test", key="k", transport=httpx.MockTransport(handler))
        async with client:
            await client.list_tools()

    with pytest.raises(McpUnavailable, match="not JSON"):
        _run(go())


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        autocare_client, "get_settings", lambda: SimpleNamespace(AUTOCARE_MCP_URL="http://mcp.test", AUTOCARE_MCP_KEY="  ")
    )
    with pytest.raises(McpUnavailable, match="AUTOCARE_MCP_KEY is not set"):
        AutoCareClient()


def test_jsonrpc_errors_split_into_caller_and_service_errors():
    def handler_for(code):
        def handler(request):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": "boom"}})

        return handler

    async def go(code):
        client = AutoCareClient(url="http://mcp.test", key="k", transport=httpx.MockTransport(handler_for(code)))
        async with client:
            await client.call_tool("query", {})

    with pytest.raises(McpToolError):
        _run(go(-32602))
    with pytest.raises(McpUnavailable):
        _run(go(-32603))


def test_catalog_is_cached_and_can_be_refreshed():
    server = FakeMcpServer()

    async def go():
        async with _client(server) as client:
            await autocare_client.load_catalog(client)
            await autocare_client.load_catalog(client)
            first = len([m for m, _ in server.requests if m == "tools/list"])
            await autocare_client.load_catalog(client, force=True)
            return first, len([m for m, _ in server.requests if m == "tools/list"])

    assert _run(go()) == (1, 2)


def test_catalog_without_tools_is_unavailable():
    server = FakeMcpServer(tools=[])

    async def go():
        async with _client(server) as client:
            await autocare_client.load_catalog(client)

    with pytest.raises(McpUnavailable, match="no tools"):
        _run(go())
