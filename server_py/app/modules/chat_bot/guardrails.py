"""
Chatbot guardrails: input-safety (prompt-injection / obfuscation detection) and
SQL-safety (read-only enforcement) checks.

Port of the reference architecture's `guardrails.py` (see CHATBOT_ARCHITECTURE.md, section 10).

Public interface (depended on by service.py / sql_agent.py):

    check_input_safety(message: str) -> tuple[bool, str | None]
    check_sql_safety(sql: str) -> tuple[bool, str | None]
    check_join_conditions(sql: str) -> str | None

The first two return (is_safe, block_reason); `block_reason` is a short, human-readable
string describing why the input/SQL was rejected, None when is_safe is True.
check_join_conditions is separate and retryable-by-design (unlike check_sql_safety's hard
abort): it returns a reason string when a JOIN's ON clause looks like a filter/comparison
instead of a key equality, or None when every JOIN looks fine. Callers should feed a non-None
result back to the model as a retryable error (like a BigQuery tool error), not abort the
whole turn — see sql_agent.py's call site.
"""

from __future__ import annotations

import base64
import codecs
import re
import unicodedata

# ---------------------------------------------------------------------------
# check_input_safety
# ---------------------------------------------------------------------------

# 1. Direct injection phrases (case-insensitive).
_DIRECT_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+instructions", re.IGNORECASE),
        "an 'ignore previous instructions' style prompt-injection phrase",
    ),
    (
        re.compile(r"\bact\s+as\b", re.IGNORECASE),
        "an 'act as' persona-override phrase",
    ),
    (
        re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
        "a 'you are now' persona-override phrase",
    ),
    (
        re.compile(r"\bpretend\s+to\s+be\b", re.IGNORECASE),
        "a 'pretend to be' persona-override phrase",
    ),
    (
        re.compile(r"\bjailbreak\b", re.IGNORECASE),
        "the word 'jailbreak'",
    ),
    (
        re.compile(r"\bforget\s+(your\s+|the\s+|all\s+)?instructions\b", re.IGNORECASE),
        "a 'forget instructions' phrase",
    ),
    (
        re.compile(
            r"\bdisregard\s+(all\s+|any\s+|previous\s+|the\s+)?(instructions|rules|prompt|guidelines)\b",
            re.IGNORECASE,
        ),
        "a 'disregard instructions/rules' phrase",
    ),
    (
        re.compile(r"\breveal\s+(your\s+)?(system\s+)?(prompt|instructions)\b", re.IGNORECASE),
        "a 'reveal your prompt/instructions' phrase",
    ),
    (
        re.compile(r"<\s*system\s*>", re.IGNORECASE),
        "a fake <system> tag",
    ),
    (
        re.compile(r"\bDAN\b"),
        "a reference to the 'DAN' jailbreak persona",
    ),
]

# ROT13 dangerous-word set (checked after ROT13-decoding the message).
_ROT13_DANGEROUS_WORDS = (
    "instructions",
    "system",
    "prompt",
    "ignore",
    "forget",
    "disregard",
    "password",
    "admin",
)

# Encoding/obfuscation smuggling patterns. Each requires 3+ consecutive occurrences
# to trigger, to avoid false positives on legitimate short strings (a single hex
# color code, one URL-encoded character, etc.).
_BASE64_FRAGMENT_RE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
_MORSE_RE = re.compile(r"(?:[.\-]{1,7}[ \t/]+){2,}[.\-]{1,7}")
_BINARY_RE = re.compile(r"(?:[01]{8}[ \t]+){2,}[01]{8}")
_HEX_PREFIXED_RE = re.compile(r"(?:0x[0-9a-fA-F]+[\s,]*){3,}")
_HEX_LONG_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_URL_ENCODED_RE = re.compile(r"(?:%[0-9a-fA-F]{2}){3,}")
_UNICODE_ESCAPE_RE = re.compile(r"(?:\\u[0-9a-fA-F]{4}){3,}")
_HTML_ENTITY_RE = re.compile(r"(?:&#?[a-zA-Z0-9]+;){3,}")


def _check_direct_injection(text: str) -> str | None:
    for pattern, description in _DIRECT_INJECTION_PATTERNS:
        if pattern.search(text):
            return f"Blocked: message contains {description}."
    return None


def _check_base64_smuggling(text: str) -> bool:
    for match in _BASE64_FRAGMENT_RE.finditer(text):
        fragment = match.group(0)
        # base64.b64decode needs padding-correct length; try as-is, then pad.
        for candidate in (fragment, fragment + "=" * (-len(fragment) % 4)):
            try:
                decoded_bytes = base64.b64decode(candidate, validate=False)
            except Exception:
                continue
            decoded_text = decoded_bytes.decode("utf-8", errors="ignore")
            if decoded_text and _check_direct_injection(decoded_text):
                return True
    return False


def _check_rot13(text: str) -> str | None:
    decoded = codecs.encode(text, "rot13").lower()
    for word in _ROT13_DANGEROUS_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", decoded):
            return f"Blocked: ROT13-obfuscated content referencing '{word}' was detected."
    return None


def _check_encoding_smuggling(text: str) -> str | None:
    if _check_base64_smuggling(text):
        return "Blocked: base64-encoded content resembling a prompt-injection phrase was detected."
    if _MORSE_RE.search(text):
        return "Blocked: morse-code-encoded content was detected (possible obfuscation attempt)."
    if _BINARY_RE.search(text):
        return "Blocked: binary-encoded content was detected (possible obfuscation attempt)."
    if _HEX_PREFIXED_RE.search(text) or _HEX_LONG_RE.search(text):
        return "Blocked: hex-encoded content was detected (possible obfuscation attempt)."
    if _URL_ENCODED_RE.search(text):
        return "Blocked: URL-percent-encoded content was detected (possible obfuscation attempt)."
    if _UNICODE_ESCAPE_RE.search(text):
        return "Blocked: unicode-escape-encoded content was detected (possible obfuscation attempt)."
    if _HTML_ENTITY_RE.search(text):
        return "Blocked: HTML/XML-entity-encoded content was detected (possible obfuscation attempt)."
    rot13_reason = _check_rot13(text)
    if rot13_reason:
        return rot13_reason
    return None


def _normalize_homoglyphs(text: str) -> str:
    """NFKC-normalize (folds many homoglyphs/fullwidth variants to their ASCII
    equivalents) and strip combining diacritical marks (defeats Zalgo-style text)."""
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def check_input_safety(message: str) -> tuple[bool, str | None]:
    """Returns (is_safe, block_reason). is_safe=False means the request should be
    rejected before any LLM/DB work happens."""
    if message is None or not message.strip():
        return True, None

    reason = _check_direct_injection(message)
    if reason:
        return False, reason

    reason = _check_encoding_smuggling(message)
    if reason:
        return False, reason

    normalized = _normalize_homoglyphs(message)
    if normalized != message:
        reason = _check_direct_injection(normalized)
        if reason:
            return False, (
                "Blocked: message contains a homoglyph/Zalgo-obfuscated "
                "prompt-injection phrase."
            )

    return True, None


# ---------------------------------------------------------------------------
# check_sql_safety
# ---------------------------------------------------------------------------

_WRITE_DDL_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "CREATE", "ALTER",
    "MERGE", "REPLACE", "CALL", "EXEC", "EXECUTE", "GRANT", "REVOKE", "COPY", "LOAD",
)

_PROCEDURAL_KEYWORDS = ("BEGIN", "DECLARE", "LOOP")

# Matches a `JOIN ... ON <condition>` clause, capturing the condition up to whatever comes
# next (another JOIN, WHERE/GROUP/ORDER/LIMIT, or end of string). Deliberately narrow: this
# only checks that the ON clause contains at least one top-level equality (`=`, not `==`/
# `!=`), which is enough to catch a join condition that's actually a filter/comparison
# predicate (e.g. `ON l.total_customers > 0`) — a real cartesian-join bug seen in practice —
# without attempting to parse or validate general join correctness.
_JOIN_ON_RE = re.compile(
    r"\bJOIN\b.+?\bON\b\s*(.+?)(?=\bJOIN\b|\bWHERE\b|\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bQUALIFY\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_EQUALITY_RE = re.compile(r"(?<![!<>=])=(?!=)")


def check_join_conditions(sql: str) -> str | None:
    for match in _JOIN_ON_RE.finditer(sql):
        condition = match.group(1)
        if not _EQUALITY_RE.search(condition):
            return (
                "Blocked: a JOIN's ON condition has no key-column equality (found: "
                f"'{condition.strip()}'). A join condition must equate two of the documented "
                "key columns (e.g. client_id = client_id, location_id = location_id) — a "
                "filter/comparison predicate is not a valid join condition and produces a "
                "cartesian/incorrect result. Re-check the documented table relationships and "
                "retry, or don't join these tables if they don't share a key."
            )
    return None


def check_sql_safety(sql: str) -> tuple[bool, str | None]:
    """Returns (is_safe, block_reason). Called after SQL generation AND on every
    retry attempt."""
    if sql is None or not sql.strip():
        return False, "Blocked: empty SQL query."

    stripped = sql.strip()

    if not re.match(r"^\s*(SELECT|WITH)\b", stripped, re.IGNORECASE):
        return False, "Blocked: only SELECT/WITH read-only queries are permitted."

    for keyword in _WRITE_DDL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", stripped, re.IGNORECASE):
            return False, f"Blocked: SQL contains a disallowed write/DDL keyword: {keyword}."

    for keyword in _PROCEDURAL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", stripped, re.IGNORECASE):
            return False, f"Blocked: SQL contains a disallowed procedural construct: {keyword}."

    if re.search(r"\bIF\s+EXISTS\b", stripped, re.IGNORECASE):
        return False, "Blocked: SQL contains a disallowed procedural construct: IF EXISTS."

    if re.search(r"\bSET\s+@", stripped, re.IGNORECASE):
        return False, "Blocked: SQL contains a disallowed procedural construct: SET @."

    statements = [s for s in stripped.split(";") if s.strip()]
    if len(statements) > 1:
        return False, "Blocked: multi-statement SQL is not permitted."

    return True, None
