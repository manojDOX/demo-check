"""Async client for the AutoCare MCP server (Google Cloud Run).

The server speaks MCP "Streamable HTTP" in stateless mode: every POST to /mcp stands alone (no session
id, no handshake needed) and answers with plain JSON. The key goes in the `X-API-Key` header.
See the AutoCare MCP guide (MCP_CHATBOT_GUIDE.md) for the protocol and the tool list.

Two kinds of failure are kept apart, because the chat reacts to them differently:
  * McpUnavailable - the service itself failed (cannot connect, timeout, HTTP 5xx, wrong or missing key,
    unreadable reply). The caller may fall back to the old SQL engine.
  * McpToolError   - the service answered, but the call was wrong (bad spec, unknown column, unknown
    tool). The text is written for a model to read and fix, so it goes back to the model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
# The first call after the service has been idle can take ~20 s (cold start).
DEFAULT_TIMEOUT_SECONDS = 90.0
CONNECT_TIMEOUT_SECONDS = 15.0
# The tool list and the server instructions only change when the server is redeployed.
CATALOG_TTL_SECONDS = 3600
_TRANSIENT_STATUS = {502, 503, 504}
# JSON-RPC codes that mean "your request was wrong" (method not found, invalid params).
_CALLER_ERROR_CODES = {-32601, -32602}


class McpUnavailable(Exception):
    """The AutoCare MCP service failed. Safe to fall back to another engine."""


class McpToolError(Exception):
    """The AutoCare MCP service rejected the call. The message is meant for the model."""


def _endpoint(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    return url if url.endswith("/mcp") else url + "/mcp"


class AutoCareClient:
    def __init__(
        self,
        *,
        url: str | None = None,
        key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_delay: float = 1.0,
    ):
        settings = get_settings()
        self.url = _endpoint(url if url is not None else settings.AUTOCARE_MCP_URL)
        api_key = (key if key is not None else settings.AUTOCARE_MCP_KEY).strip()
        if not api_key:
            raise McpUnavailable("AUTOCARE_MCP_KEY is not set")
        self._retry_delay = retry_delay
        self._next_id = 0
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT_SECONDS),
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AutoCareClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def _rpc(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}}

        failure = ""
        for attempt in (1, 2):
            transient = False
            try:
                response = await self._http.post(self.url, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as error:
                failure = f"{type(error).__name__}: {error}" or type(error).__name__
                transient = True
            else:
                status = response.status_code
                if status in (401, 403):
                    raise McpUnavailable(f"AutoCare MCP rejected the API key (HTTP {status})")
                if status in _TRANSIENT_STATUS:
                    failure = f"AutoCare MCP returned HTTP {status}"
                    transient = True
                elif status >= 400:
                    raise McpUnavailable(f"AutoCare MCP returned HTTP {status}: {response.text[:200]}")
                else:
                    try:
                        body = response.json()
                    except ValueError as error:
                        raise McpUnavailable(f"AutoCare MCP returned a reply that is not JSON: {error}") from error
                    if not isinstance(body, dict):
                        raise McpUnavailable("AutoCare MCP returned an unexpected reply")
                    if "error" in body:
                        error = body["error"] if isinstance(body["error"], dict) else {}
                        message = str(error.get("message") or body["error"])
                        if error.get("code") in _CALLER_ERROR_CODES:
                            raise McpToolError(message)
                        raise McpUnavailable(f"AutoCare MCP error {error.get('code')}: {message}")
                    result = body.get("result")
                    if not isinstance(result, dict):
                        raise McpUnavailable("AutoCare MCP reply has no result")
                    return result
            if attempt == 1 and transient:
                logger.warning("AutoCare MCP %s failed (%s); retrying once", method, failure)
                await asyncio.sleep(self._retry_delay)
                continue
            raise McpUnavailable(failure)
        raise McpUnavailable(failure)  # pragma: no cover - the loop always returns or raises

    async def initialize(self) -> str:
        """Returns the server `instructions`: business definitions, the spec cheat sheet, and worked
        examples. They are the core of the model's system prompt."""
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "xiomara-chatbot", "version": "1.0"},
            },
        )
        return str(result.get("instructions") or "")

    async def list_tools(self) -> list[dict]:
        result = await self._rpc("tools/list")
        tools = result.get("tools")
        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Runs one tool and returns its result (`structuredContent`). Raises McpToolError when the
        server marks the result `isError` (bad spec, unknown column, unknown tool)."""
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        text = ""
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "")
                break
        if result.get("isError"):
            raise McpToolError(text or "The tool call failed.")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        try:
            parsed = json.loads(text)
        except ValueError:
            return {"text": text}
        return parsed if isinstance(parsed, dict) else {"result": parsed}


# ---------------------------------------------------------------------------
# Catalog cache (instructions + tool list), shared by every request in this process.
# ---------------------------------------------------------------------------

_catalog: dict = {"loaded_at": 0.0, "instructions": "", "tools": []}


def reset_catalog_cache() -> None:
    _catalog.update({"loaded_at": 0.0, "instructions": "", "tools": []})


async def load_catalog(client: AutoCareClient, *, force: bool = False) -> tuple[str, list[dict]]:
    fresh = bool(_catalog["tools"]) and (time.monotonic() - _catalog["loaded_at"]) < CATALOG_TTL_SECONDS
    if fresh and not force:
        return _catalog["instructions"], _catalog["tools"]
    instructions = await client.initialize()
    tools = await client.list_tools()
    if not tools:
        raise McpUnavailable("AutoCare MCP returned no tools")
    _catalog.update({"loaded_at": time.monotonic(), "instructions": instructions, "tools": tools})
    return instructions, tools
