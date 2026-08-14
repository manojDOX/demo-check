"""Port of server/routes.ts's `callOpenAIWithTimeoutAndRetry` helper (~lines 31-94) and
the `AIServiceError` class it raises on timeout / persistent 5xx.

This is deliberately duplicated per-module rather than hoisted into a shared location —
the (separately being rebuilt) chatbot module has its own copy of this pattern too, and a
future consolidation pass can dedupe both once that module lands.
"""

import asyncio
import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


class AIServiceError(Exception):
    """Raised when the AI service times out or returns a persistent 5xx."""

    def __init__(self, message: str, cause: BaseException | None = None):
        super().__init__(message)
        self.cause = cause


def get_openai_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.AI_INTEGRATIONS_OPENAI_API_KEY,
        base_url=settings.AI_INTEGRATIONS_OPENAI_BASE_URL or None,
    )


async def call_openai_with_timeout_and_retry(
    params: dict[str, Any],
    timeout_ms: int = 25000,
    max_retries: int = 1,
) -> Any:
    """Calls chat.completions.create with a hard timeout, retrying once (by default) on
    timeout or 5xx, with a 1.5s * (attempt+1) backoff — mirrors the JS AbortController +
    retry loop exactly."""
    client = get_openai_client()
    timeout_s = timeout_ms / 1000

    last_error: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return await asyncio.wait_for(
                client.chat.completions.create(**params), timeout=timeout_s
            )
        except Exception as err:  # noqa: BLE001 - mirrors JS catch(err: any)
            last_error = err

            is_abort = isinstance(err, (asyncio.TimeoutError, TimeoutError))
            status = getattr(err, "status_code", None)
            is_transient = is_abort or (isinstance(status, int) and status >= 500)

            if not is_transient or attempt >= max_retries:
                break

            backoff_s = 1.5 * (attempt + 1)
            logger.warning(
                "[AI] Transient failure (attempt %d/%d), retrying in %.1fs — %s",
                attempt + 1,
                max_retries + 1,
                backoff_s,
                "timeout" if is_abort else f"status {status}",
            )
            await asyncio.sleep(backoff_s)

    is_abort = isinstance(last_error, (asyncio.TimeoutError, TimeoutError))
    status = getattr(last_error, "status_code", None)

    if is_abort:
        raise AIServiceError("AI service timed out", last_error)
    if isinstance(status, int) and status >= 500:
        raise AIServiceError(f"AI service returned {status}", last_error)
    if last_error is not None:
        raise last_error
    raise AIServiceError("AI service call failed for an unknown reason")
