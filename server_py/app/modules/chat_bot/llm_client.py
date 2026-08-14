"""
Provider-agnostic LLM transport for the chatbot module.

Port of the reference architecture's `llm_client.py` (see CHATBOT_ARCHITECTURE.md,
section 8). Supported providers: openai, anthropic, gemini, groq, openrouter
(groq/openrouter route through the OpenAI-compatible chat-completions API with a
different base_url).

Public interface (depended on by sql_agent.py / service.py — do not change signatures):

    async def discover_models(provider: str, api_key: str) -> dict
    async def call_llm(provider, model, api_key, messages, max_tokens=3000, temperature=0.2) -> str
    async def stream_llm(provider, model, api_key, messages, max_tokens=1000, temperature=0.7) -> AsyncGenerator[str, None]
    def parse_llm_json(text: str) -> dict
    def recover_sql_from_truncated_json(text: str) -> str | None

Also (added for the MCP tool-calling pipeline, sql_agent.py — see CHATBOT_ARCHITECTURE.md
port task, "MCP tool-calling architecture"):

    def mcp_tools_to_openai_format(mcp_tools: list[dict]) -> list[dict]
    async def call_llm_with_tools(provider, model, api_key, messages, tools, max_tokens=3000, temperature=0.2) -> dict
    def messages_with_tool_result(provider, tool_call_id, tool_name, result_content) -> list[dict]

`messages` for call_llm_with_tools is a PROVIDER-NATIVE list the caller (sql_agent.py)
accumulates turn-by-turn — it starts as generic {"role","content"} dicts (system/user/
assistant, content always a str) but grows provider-specific shapes as tool-call/tool-
result turns are appended (the "raw_message" this function returns, plus whatever
`messages_with_tool_result` produces) — so the caller must never assume OpenAI's
`{"role":"tool",...}` shape works for every provider; use `messages_with_tool_result`
instead of building it inline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncGenerator

import anthropic
import google.generativeai as genai
import openai
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider constants
# ---------------------------------------------------------------------------

_SUPPORTED_PROVIDERS = ("openai", "anthropic", "gemini", "groq", "openrouter")

# groq/openrouter are OpenAI-compatible chat-completions APIs reached via base_url.
_OPENAI_COMPAT_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    # "openai" intentionally omitted -> AsyncOpenAI default base_url is used.
}

# Per-provider default-model preference ordering. `_pick_default` walks this list
# and returns the first entry present in the actually-available model set for the
# key being validated, falling back to available[0] if none match. These are
# reasonable current flagship/cost-efficient model ids; since the list is only a
# *preference* (with a safe fallback to whatever the provider actually returns),
# it degrades gracefully even if a specific id here is retired or renamed.
_MODEL_PREFERENCE: dict[str, list[str]] = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"],
    "anthropic": [
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-1-20250805",
        "claude-sonnet-4-20250514",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-haiku-20240307",
    ],
    "gemini": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-pro"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "openrouter": ["openai/gpt-4o-mini", "openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.3-70b-instruct"],
}

# Anthropic has no model-listing endpoint; candidates are probed in parallel with
# a live 1-token completion call, and whichever succeed form the available set.
_ANTHROPIC_CANDIDATE_MODELS = [
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-1-20250805",
    "claude-sonnet-4-20250514",
    "claude-3-7-sonnet-20250219",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
]

# Markers that identify a model id as NOT a general chat-completion model
# (embeddings, TTS/whisper/audio, image generation, moderation, legacy
# completion-only models) — filtered out of `/models` listings for openai/
# groq/openrouter.
_NON_CHAT_MODEL_MARKERS = (
    "embedding",
    "whisper",
    "tts",
    "dall-e",
    "dalle",
    "moderation",
    "davinci",
    "curie",
    "babbage",
    "ada-",
    ":ada",
    "-instruct",
    "audio-preview",
    "realtime-preview",
    "transcribe",
    "clip",
    "similarity",
)

# gen_max_tokens is bumped for Gemini specifically: the schema/rules payload for
# SQL-generation-style JSON prompts (discovery CTEs, entity-validation CTEs,
# multi-chart response_format, etc.) routinely exceeds the default 3000-token
# budget for Gemini and leaves the JSON response truncated. Only applied in
# call_llm (used for the JSON-producing SQL-gen/validation/fix calls), not in
# stream_llm (used for the plain-text streamed narrative answer).
_GEMINI_MIN_MAX_TOKENS = 6000
_DEFAULT_CALL_MAX_TOKENS = 3000


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _normalize_provider(provider: str) -> str:
    p = (provider or "").strip().lower()
    if p not in _SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported LLM provider: {provider!r}. "
            f"Supported providers: {', '.join(_SUPPORTED_PROVIDERS)}."
        )
    return p


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """Splits system-role messages out from the rest (needed for Anthropic/Gemini,
    which take the system prompt as a separate parameter rather than a message)."""
    system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    return "\n\n".join(p for p in system_parts if p), rest


def _to_gemini_contents(messages: list[dict]) -> list[dict]:
    """Gemini uses role "model" instead of "assistant"; each turn is {role, parts}."""
    contents = []
    for m in messages:
        role = "model" if m.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [m.get("content", "")]})
    return contents


def _gemini_wants_json(messages: list[dict]) -> bool:
    """Detects whether any message asks for JSON output (case-insensitive), and if
    so, JSON response mode is turned on. This was the single largest source of
    "LLM returned unparseable response" failures for Gemini — without it, the
    model would wrap JSON in markdown fences or prose despite instructions."""
    for m in messages:
        content = (m.get("content") or "")
        low = content.lower()
        if "valid json" in low or "respond with json" in low:
            return True
    return False


def _pick_default(provider: str, available: list[str]) -> str | None:
    if not available:
        return None
    available_set = set(available)
    for candidate in _MODEL_PREFERENCE.get(provider, []):
        if candidate in available_set:
            return candidate
    return available[0]


def _is_non_chat_model(model_id: str) -> bool:
    low = model_id.lower()
    return any(marker in low for marker in _NON_CHAT_MODEL_MARKERS)


# ---------------------------------------------------------------------------
# discover_models
# ---------------------------------------------------------------------------


async def discover_models(provider: str, api_key: str) -> dict:
    """Validates the key and returns {"default_model": str, "available_models": list[str]}.
    Raises ValueError with a user-facing message on invalid key / provider error."""
    p = _normalize_provider(provider)
    if not api_key or not api_key.strip():
        raise ValueError("An API key is required.")

    if p == "anthropic":
        return await _discover_anthropic_models(api_key)
    if p == "gemini":
        return await _discover_gemini_models(api_key)
    # openai / groq / openrouter
    return await _discover_openai_compat_models(p, api_key)


async def _discover_openai_compat_models(provider: str, api_key: str) -> dict:
    base_url = _OPENAI_COMPAT_BASE_URLS.get(provider)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url) if base_url else AsyncOpenAI(api_key=api_key)
    try:
        resp = await client.models.list()
    except openai.AuthenticationError:
        raise ValueError(f"Invalid {provider} API key.")
    except Exception as exc:  # noqa: BLE001 - surface as a user-facing message
        raise ValueError(f"Failed to validate {provider} API key: {exc}")

    ids = [m.id for m in resp.data]
    filtered = sorted({i for i in ids if not _is_non_chat_model(i)})
    if not filtered:
        raise ValueError(f"No chat-capable models were found for this {provider} key.")

    default = _pick_default(provider, filtered)
    return {"default_model": default, "available_models": filtered}


async def _discover_anthropic_models(api_key: str) -> dict:
    client = AsyncAnthropic(api_key=api_key)

    async def _probe(model_id: str) -> tuple[str, bool, str | None]:
        try:
            await client.messages.create(
                model=model_id,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return model_id, True, None
        except anthropic.AuthenticationError:
            return model_id, False, "auth"
        except Exception:  # noqa: BLE001 - model not accessible with this key/tier
            return model_id, False, "other"

    results = await asyncio.gather(*(_probe(m) for m in _ANTHROPIC_CANDIDATE_MODELS))

    # First AuthenticationError short-circuits the whole discovery.
    for _model_id, _ok, err in results:
        if err == "auth":
            raise ValueError("Invalid Anthropic API key.")

    available = [model_id for model_id, ok, _err in results if ok]
    if not available:
        raise ValueError("No accessible Anthropic models were found for this key.")

    default = _pick_default("anthropic", available)
    return {"default_model": default, "available_models": available}


async def _discover_gemini_models(api_key: str) -> dict:
    def _list_sync() -> list[str]:
        genai.configure(api_key=api_key)
        names: list[str] = []
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in methods:
                name = m.name
                if name.startswith("models/"):
                    name = name[len("models/"):]
                names.append(name)
        return names

    try:
        ids = await asyncio.to_thread(_list_sync)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid Gemini API key or error listing models: {exc}")

    if not ids:
        raise ValueError("No Gemini models available for this key.")

    default = _pick_default("gemini", ids)
    return {"default_model": default, "available_models": ids}


# ---------------------------------------------------------------------------
# call_llm (single non-streaming completion)
# ---------------------------------------------------------------------------


async def call_llm(
    provider: str,
    model: str,
    api_key: str,
    messages: list[dict],
    max_tokens: int = 3000,
    temperature: float = 0.2,
) -> str:
    """Single non-streaming completion. `messages` is
    [{"role": "system"|"user"|"assistant", "content": str}, ...].
    Returns the text content. Raises on failure (let caller handle)."""
    p = _normalize_provider(provider)
    if p == "anthropic":
        return await _anthropic_call(model, api_key, messages, max_tokens, temperature)
    if p == "gemini":
        return await _gemini_call(model, api_key, messages, max_tokens, temperature)
    return await _openai_compat_call(p, model, api_key, messages, max_tokens, temperature)


async def _anthropic_call(model: str, api_key: str, messages: list[dict], max_tokens: int, temperature: float) -> str:
    system_text, rest = _split_system(messages)
    client = AsyncAnthropic(api_key=api_key)
    kwargs = {"system": system_text} if system_text else {}
    resp = await client.messages.create(
        model=model, max_tokens=max_tokens, temperature=temperature, messages=rest, **kwargs
    )
    return "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")


async def _openai_compat_call(
    provider: str, model: str, api_key: str, messages: list[dict], max_tokens: int, temperature: float
) -> str:
    base_url = _OPENAI_COMPAT_BASE_URLS.get(provider)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url) if base_url else AsyncOpenAI(api_key=api_key)
    resp = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, temperature=temperature
    )
    return resp.choices[0].message.content or ""


async def _gemini_call(model: str, api_key: str, messages: list[dict], max_tokens: int, temperature: float) -> str:
    genai.configure(api_key=api_key)
    effective_max_tokens = max_tokens
    if effective_max_tokens <= _DEFAULT_CALL_MAX_TOKENS:
        effective_max_tokens = _GEMINI_MIN_MAX_TOKENS

    system_text, rest = _split_system(messages)
    gen_config_kwargs = {"max_output_tokens": effective_max_tokens, "temperature": temperature}
    if _gemini_wants_json(messages):
        gen_config_kwargs["response_mime_type"] = "application/json"
    generation_config = genai.types.GenerationConfig(**gen_config_kwargs)

    gm = genai.GenerativeModel(
        model, system_instruction=system_text or None, generation_config=generation_config
    )
    contents = _to_gemini_contents(rest)
    resp = await gm.generate_content_async(contents)
    return resp.text or ""


# ---------------------------------------------------------------------------
# stream_llm (async-generator chunk streaming)
# ---------------------------------------------------------------------------


async def stream_llm(
    provider: str,
    model: str,
    api_key: str,
    messages: list[dict],
    max_tokens: int = 1000,
    temperature: float = 0.7,
) -> AsyncGenerator[str, None]:
    """Async generator yielding text chunks (str) as they arrive from the provider."""
    p = _normalize_provider(provider)
    if p == "anthropic":
        async for chunk in _anthropic_stream(model, api_key, messages, max_tokens, temperature):
            yield chunk
    elif p == "gemini":
        async for chunk in _gemini_stream(model, api_key, messages, max_tokens, temperature):
            yield chunk
    else:
        async for chunk in _openai_compat_stream(p, model, api_key, messages, max_tokens, temperature):
            yield chunk


async def _anthropic_stream(
    model: str, api_key: str, messages: list[dict], max_tokens: int, temperature: float
) -> AsyncGenerator[str, None]:
    system_text, rest = _split_system(messages)
    client = AsyncAnthropic(api_key=api_key)
    kwargs = {"system": system_text} if system_text else {}
    async with client.messages.stream(
        model=model, max_tokens=max_tokens, temperature=temperature, messages=rest, **kwargs
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _openai_compat_stream(
    provider: str, model: str, api_key: str, messages: list[dict], max_tokens: int, temperature: float
) -> AsyncGenerator[str, None]:
    base_url = _OPENAI_COMPAT_BASE_URLS.get(provider)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url) if base_url else AsyncOpenAI(api_key=api_key)
    stream = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=True
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def _gemini_stream(
    model: str, api_key: str, messages: list[dict], max_tokens: int, temperature: float
) -> AsyncGenerator[str, None]:
    genai.configure(api_key=api_key)
    system_text, rest = _split_system(messages)
    gen_config_kwargs = {"max_output_tokens": max_tokens, "temperature": temperature}
    if _gemini_wants_json(messages):
        gen_config_kwargs["response_mime_type"] = "application/json"
    generation_config = genai.types.GenerationConfig(**gen_config_kwargs)

    gm = genai.GenerativeModel(
        model, system_instruction=system_text or None, generation_config=generation_config
    )
    contents = _to_gemini_contents(rest)
    resp = await gm.generate_content_async(contents, stream=True)
    async for chunk in resp:
        try:
            text = chunk.text
        except ValueError:
            # Chunk has no text parts (e.g. only a function-call/safety block); skip.
            text = ""
        if text:
            yield text


# ---------------------------------------------------------------------------
# parse_llm_json — tolerant JSON extraction
# ---------------------------------------------------------------------------

_BACKSLASH_NEWLINE_RE = re.compile(r"\\\r?\n")
_FENCED_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_balanced_json_object(text: str) -> str | None:
    """Scans for the first `{...}` substring with balanced braces, respecting
    JSON string literals (so braces inside quoted strings don't throw off the
    balance count)."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None  # never closed (truncated)


def parse_llm_json(text: str) -> dict:
    """Tolerant JSON extraction: repairs backslash-newline artifacts, tries fenced
    ```json blocks first, then the full text, then a {...} substring scan.
    Raises ValueError if nothing parses."""
    if text is None or not text.strip():
        raise ValueError("Empty response from LLM; cannot parse JSON.")

    repaired = _BACKSLASH_NEWLINE_RE.sub("", text)

    for match in _FENCED_BLOCK_RE.finditer(repaired):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    try:
        return json.loads(repaired.strip())
    except json.JSONDecodeError:
        pass

    obj_text = _extract_balanced_json_object(repaired)
    if obj_text is not None:
        try:
            return json.loads(obj_text)
        except json.JSONDecodeError:
            pass

    raise ValueError("Could not parse a JSON object from the LLM response.")


# ---------------------------------------------------------------------------
# recover_sql_from_truncated_json
# ---------------------------------------------------------------------------

_SQL_FIELD_RE = re.compile(r'"sql"\s*:\s*"((?:\\.|[^"\\])*)"?', re.DOTALL)


def recover_sql_from_truncated_json(text: str) -> str | None:
    """Port of `_recover_sql_from_truncated_json` — regex-extracts just the "sql"
    field's string value from a JSON object that may never have closed (truncated
    by max_tokens). Returns None if no "sql" field pattern is found."""
    if not text:
        return None

    match = _SQL_FIELD_RE.search(text)
    if not match:
        return None

    raw = match.group(1)
    if not raw or not raw.strip():
        return None

    # Try to decode as a proper JSON string, trimming trailing characters in case
    # the value itself was cut mid-escape-sequence by truncation.
    candidate = raw
    for _ in range(4):
        try:
            return json.loads('"' + candidate + '"')
        except json.JSONDecodeError:
            if not candidate:
                break
            candidate = candidate[:-1]

    # Best-effort manual unescape fallback.
    return raw.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


# ---------------------------------------------------------------------------
# Tool-calling (MCP) support
# ---------------------------------------------------------------------------


def mcp_tools_to_openai_format(mcp_tools: list[dict]) -> list[dict]:
    """Converts MCP `tools/list` results into OpenAI-format function-tool defs. Used
    directly for openai/groq/openrouter; re-converted per-provider inside
    call_llm_with_tools for anthropic/gemini."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
            },
        }
        for tool in mcp_tools
    ]


def _struct_to_dict(value):
    """Best-effort conversion of a Gemini function_call's `.args` (a proto-plus
    MapComposite/Struct-like object) into a plain JSON-serializable dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return {k: _struct_to_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_struct_to_dict(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    try:
        return {k: _struct_to_dict(v) for k, v in dict(value).items()}
    except Exception:  # noqa: BLE001
        return value


async def call_llm_with_tools(
    provider: str,
    model: str,
    api_key: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int = 3000,
    temperature: float = 0.2,
) -> dict:
    """Returns a NORMALIZED shape regardless of provider:
        {
          "content": str | None,
          "tool_calls": list[{"id": str, "name": str, "arguments": dict}] | None,
          "raw_message": <the provider-native assistant-turn value to append to
                           `messages` for the next round trip>,
        }
    Exactly one of content/tool_calls is meaningfully populated per the model's turn
    (content when it's done, tool_calls when it wants to call tools).
    `messages` is provider-native (see module docstring) — openai/groq/openrouter get
    tools passed straight through; anthropic/gemini get `tools` converted internally."""
    p = _normalize_provider(provider)
    if p == "anthropic":
        return await _anthropic_tools_call(model, api_key, messages, tools, max_tokens, temperature)
    if p == "gemini":
        return await _gemini_tools_call(model, api_key, messages, tools, max_tokens, temperature)
    return await _openai_compat_tools_call(p, model, api_key, messages, tools, max_tokens, temperature)


async def _openai_compat_tools_call(
    provider: str, model: str, api_key: str, messages: list[dict], tools: list[dict], max_tokens: int, temperature: float
) -> dict:
    base_url = _OPENAI_COMPAT_BASE_URLS.get(provider)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url) if base_url else AsyncOpenAI(api_key=api_key)
    kwargs = {}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    resp = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, temperature=temperature, **kwargs
    )
    message = resp.choices[0].message
    raw_message = message.model_dump(exclude_none=True)

    tool_calls = None
    if message.tool_calls:
        tool_calls = []
        for call in message.tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append({"id": call.id, "name": call.function.name, "arguments": arguments})

    return {"content": message.content, "tool_calls": tool_calls, "raw_message": raw_message}


def _anthropic_tools_from_openai_format(tools: list[dict]) -> list[dict]:
    converted = []
    for tool in tools:
        fn = tool["function"]
        converted.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted


async def _anthropic_tools_call(
    model: str, api_key: str, messages: list[dict], tools: list[dict], max_tokens: int, temperature: float
) -> dict:
    system_text, rest = _split_system(messages)
    client = AsyncAnthropic(api_key=api_key)
    kwargs = {"system": system_text} if system_text else {}
    if tools:
        kwargs["tools"] = _anthropic_tools_from_openai_format(tools)
    resp = await client.messages.create(
        model=model, max_tokens=max_tokens, temperature=temperature, messages=rest, **kwargs
    )

    text_parts = []
    tool_calls = None
    for block in resp.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(block.text)
        elif block_type == "tool_use":
            if tool_calls is None:
                tool_calls = []
            tool_calls.append({"id": block.id, "name": block.name, "arguments": block.input or {}})

    # Anthropic wants the assistant turn's raw content blocks passed back verbatim on
    # the next call — the SDK accepts the response's own `.content` list directly.
    raw_message = {"role": "assistant", "content": resp.content}
    content = "".join(text_parts) if text_parts else None
    return {"content": content, "tool_calls": tool_calls, "raw_message": raw_message}


def _gemini_tools_from_openai_format(tools: list[dict]) -> list:
    declarations = []
    for tool in tools:
        fn = tool["function"]
        declarations.append(
            genai.types.FunctionDeclaration(
                name=fn["name"],
                description=fn.get("description", ""),
                parameters=fn.get("parameters") or {"type": "object", "properties": {}},
            )
        )
    return [genai.types.Tool(function_declarations=declarations)]


def _gemini_contents_from_messages(messages: list[dict]) -> list[dict]:
    """Like _to_gemini_contents, but tolerant of a message's "content" already being a
    list of Gemini `parts` dicts (used by the tool-calling round trip for function_call/
    function_response parts) instead of a plain string."""
    contents = []
    for m in messages:
        role = "model" if m.get("role") == "assistant" else m.get("role") or "user"
        if role not in ("user", "model", "function"):
            role = "user"
        content = m.get("content", "")
        parts = content if isinstance(content, list) else [content]
        contents.append({"role": role, "parts": parts})
    return contents


async def _gemini_tools_call(
    model: str, api_key: str, messages: list[dict], tools: list[dict], max_tokens: int, temperature: float
) -> dict:
    genai.configure(api_key=api_key)
    effective_max_tokens = max_tokens if max_tokens > _DEFAULT_CALL_MAX_TOKENS else _GEMINI_MIN_MAX_TOKENS

    system_text, rest = _split_system(messages)
    generation_config = genai.types.GenerationConfig(max_output_tokens=effective_max_tokens, temperature=temperature)
    gemini_tools = _gemini_tools_from_openai_format(tools) if tools else None

    gm = genai.GenerativeModel(
        model, system_instruction=system_text or None, generation_config=generation_config, tools=gemini_tools
    )
    contents = _gemini_contents_from_messages(rest)
    resp = await gm.generate_content_async(contents)

    candidate = resp.candidates[0] if resp.candidates else None
    text_parts = []
    tool_calls = None
    raw_parts: list[dict] = []
    if candidate is not None:
        for part in candidate.content.parts:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                if tool_calls is None:
                    tool_calls = []
                args = _struct_to_dict(fc.args)
                tool_calls.append({"id": fc.name, "name": fc.name, "arguments": args})
                raw_parts.append({"function_call": {"name": fc.name, "args": args}})
            else:
                text = getattr(part, "text", None)
                if text:
                    text_parts.append(text)
                    raw_parts.append({"text": text})

    raw_message = {"role": "model", "content": raw_parts}
    content = "".join(text_parts) if text_parts else None
    return {"content": content, "tool_calls": tool_calls, "raw_message": raw_message}


def messages_with_tool_result(
    provider: str, tool_call_id: str, tool_name: str, result_content: str
) -> list[dict]:
    """Builds the message(s) to append after a tool call executes, in the shape the
    given provider expects for its NEXT call_llm_with_tools round trip. Returns a list
    (always length 1 today) so callers can `messages.extend(...)` uniformly."""
    p = _normalize_provider(provider)
    if p == "anthropic":
        return [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tool_call_id, "content": result_content}
                ],
            }
        ]
    if p == "gemini":
        try:
            response_obj = json.loads(result_content)
        except (json.JSONDecodeError, TypeError):
            response_obj = {"result": result_content}
        if not isinstance(response_obj, dict):
            response_obj = {"result": response_obj}
        return [
            {
                "role": "function",
                "content": [{"function_response": {"name": tool_name, "response": response_obj}}],
            }
        ]
    # openai / groq / openrouter
    return [{"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result_content}]
