"""Minimal async JSON-RPC client for Google's hosted remote BigQuery MCP server
(https://bigquery.googleapis.com/mcp) — no local MCP server process, it's a real Google
Cloud service reached over HTTP.

Adapted from the reference implementation's `BigQueryMCPClient`
(F:\\prowiz\\bq-mcp\\MCP-Chat_bot\\app\\mcp_client.py), which used `requests` + a
synchronous service-account-from-file flow. This version:
  - is async throughout (httpx.AsyncClient, matching the rest of this codebase)
  - builds credentials from an in-memory JSON string (already-decrypted connection
    credentials), not a file path
  - wraps the blocking `google-auth` token refresh in `asyncio.to_thread`, matching the
    established pattern in connections/bigquery_service.py for blocking Google SDK calls

Live-verified (2026-08-14) against the real hosted MCP server using connection id=7's
real service-account credentials. The server currently exposes exactly 6 tools:
  list_dataset_ids(projectId, pageSize?, pageToken?)
  get_dataset_info(projectId, datasetId)
  list_table_ids(projectId, datasetId, pageSize?, pageToken?)
  get_table_info(projectId, datasetId, tableId)
  execute_sql_readonly(projectId, query, dryRun?)   -- SELECT-only, argument key is "query"
  execute_sql(projectId, query, dryRun?)            -- unrestricted, argument key is "query"

`execute_sql_readonly`/`execute_sql` results come back as:
  {"content": [{"type": "text", "text": "<json string>"}],
   "structuredContent": {"schema": {"fields": [{"name","type","mode"}, ...]},
                          "rows": [{"f": [{"v": "1"}, ...]}, ...],
                          "jobComplete": true, ...}}
i.e. BigQuery's legacy REST tabledata shape (rows as positional {"f":[{"v":...}]} arrays
keyed by `schema.fields` order) nested inside `structuredContent` — already parsed, no
need to re-parse `content[0].text`. sql_agent.py's row-parsing relies on this shape.
"""

from __future__ import annotations

import asyncio
import itertools
import json

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from app.modules.chat_bot.config import BQ_MCP_URL, BQ_OAUTH_SCOPE


class BigQueryMCPClient:
    def __init__(self, credentials_json: str, project_id: str):
        info = json.loads(credentials_json)
        self._creds = service_account.Credentials.from_service_account_info(
            info, scopes=[BQ_OAUTH_SCOPE]
        )
        self.project_id = project_id
        self._client = httpx.AsyncClient(timeout=60.0)
        self._session_id: str | None = None
        self._ids = itertools.count(1)
        self._initialized = False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _access_token(self) -> str:
        if not self._creds.valid:
            await asyncio.to_thread(self._creds.refresh, GoogleAuthRequest())
        return self._creds.token

    async def _headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {await self._access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _rpc(self, method: str, params: dict | None = None, notification: bool = False) -> dict | None:
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            payload["id"] = next(self._ids)

        resp = await self._client.post(BQ_MCP_URL, headers=await self._headers(), json=payload)
        resp.raise_for_status()

        session_id = resp.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id

        if notification or not resp.content:
            return None

        content_type = resp.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            data = self._parse_sse(resp.text)
        else:
            data = resp.json()

        if data is None:
            return None
        if "error" in data:
            raise RuntimeError(f"MCP error calling {method}: {data['error']}")
        return data.get("result")

    @staticmethod
    def _parse_sse(text: str) -> dict | None:
        last = None
        for block in text.split("\n\n"):
            lines = [ln[len("data:"):].strip() for ln in block.splitlines() if ln.startswith("data:")]
            if lines:
                last = json.loads("".join(lines))
        return last

    async def initialize(self) -> None:
        if self._initialized:
            return
        await self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "xiomara-chatbot", "version": "0.1.0"},
            },
        )
        await self._rpc("notifications/initialized", notification=True)
        self._initialized = True

    async def list_tools(self) -> list[dict]:
        await self.initialize()
        result = await self._rpc("tools/list", {})
        return (result or {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        await self.initialize()
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})
