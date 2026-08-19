"""Chatbot-module-local config constants for the MCP tool-calling pipeline (sql_agent.py).

Deliberately NOT added to app/config.py (out of scope per task instructions — that file
is shared across all modules and owned elsewhere).
"""

# Google's hosted remote BigQuery MCP server. Not a local process — a real Google Cloud
# service reached over HTTP/JSON-RPC. See mcp_client.py.
BQ_MCP_URL = "https://bigquery.googleapis.com/mcp"
BQ_OAUTH_SCOPE = "https://www.googleapis.com/auth/bigquery"

# Max LLM<->tool round trips per user turn before giving up (mirrors the reference
# implementation's MAX_TOOL_ROUNDS).
CHATBOT_MAX_TOOL_ROUNDS = 8

# A tool result fed back to the LLM larger than this is truncated (mirrors the reference
# implementation's MAX_TOOL_RESULT_CHARS).
CHATBOT_MAX_TOOL_RESULT_CHARS = 20000

# Row sample sizes for what's actually fed to an LLM, independent of the up-to-500-row cap
# used for the frontend table/chart display (sql_agent.py's `data_rows`). Both are
# deliberately much smaller than the display cap — an LLM narrating or sanity-checking a
# result doesn't need hundreds of raw rows, just enough to ground it, plus total_rows/
# truncated so it can still speak to the full size accurately.
CHATBOT_TOOL_ECHO_ROW_SAMPLE = 50
CHATBOT_ANSWER_ROWS_SAMPLE = 30
