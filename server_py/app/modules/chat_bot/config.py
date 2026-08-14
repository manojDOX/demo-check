"""Chatbot-module-local config constants.

Deliberately NOT added to app/config.py (out of scope per task instructions — that file
is shared across all modules and owned elsewhere). These mirror the `CHATBOT_*` settings
documented in CHATBOT_ARCHITECTURE.md §11, minus the semantic-cache-only settings (that
feature is deferred/stubbed in this port — see sql_agent.py's CACHE-HOOK comment).
"""

# Process-local TTL (seconds) for schema_service.get_connection_tables' in-memory cache.
CHATBOT_SCHEMA_CACHE_TTL_SECONDS = 1800

# Process-local TTL (seconds) for schema_service.classify_tables' in-memory cache (7 days).
CHATBOT_CLASSIFY_CACHE_TTL_SECONDS = 604800

# Max dry-run/fix attempts before giving up on a generated query.
CHATBOT_MAX_SQL_RETRIES = 5

# Kept for interface parity with the reference doc's semantic-cache config; unused while
# the cache is stubbed (see sql_agent.py's cache_candidates hook).
CHATBOT_SEMANTIC_CACHE_TOP_K = 5

# --- MCP tool-calling pipeline (sql_agent.py) -------------------------------------------

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
