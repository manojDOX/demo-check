"""Full CSV export of a chat result.

The table in the chat shows at most AUTOCARE_ROW_LIMIT rows. The saved query spec can be run again
without that limit. This module reads the answer page by page from the AutoCare MCP server and
writes it as CSV, so the browser only has to save a file.
"""

from __future__ import annotations

import csv
import io
from typing import AsyncIterator

from app.modules.chat_bot import autocare_drill
from app.modules.chat_bot.answer_utils import display_value
from app.modules.chat_bot.autocare_client import AutoCareClient

PAGE_SIZE = 5000  # The most rows the server returns in one call.
MAX_EXPORT_ROWS = 50000


class ExportTooLarge(Exception):
    def __init__(self, total_rows: int):
        super().__init__(f"This result has {total_rows:,} rows. The export limit is {MAX_EXPORT_ROWS:,} rows.")
        self.total_rows = total_rows


def prepare_spec(base_view, base_spec) -> tuple[str, dict]:
    """The spec to page through: the saved spec without its own `limit` and `offset`, and with a
    stable order. Without a stable order, two pages can overlap or skip rows."""
    view, spec = autocare_drill.sanitize_base_spec(base_view, base_spec)
    spec.pop("limit", None)
    spec.pop("offset", None)
    if not spec.get("order_by"):
        columns = spec.get("columns")
        if isinstance(columns, list) and "client_id" in columns:
            spec["order_by"] = [{"column": "client_id", "direction": "asc"}]
    return view, spec


def _csv_line(values: list) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerow(values)
    return buffer.getvalue()


def _cell(value):
    shown = display_value(value)
    return "" if shown is None else shown


async def _page(client: AutoCareClient, spec: dict, offset: int) -> dict:
    return await client.call_tool("query", {"spec": {**spec, "limit": PAGE_SIZE, "offset": offset}})


async def start_export(client: AutoCareClient, spec: dict) -> tuple[dict, int]:
    """Reads the first page. Raises ExportTooLarge before any byte is sent when the answer is too big."""
    first = await _page(client, spec, 0)
    rows = first.get("rows") if isinstance(first.get("rows"), list) else []
    total = first.get("total_rows")
    total = total if isinstance(total, int) and total >= len(rows) else len(rows)
    if total > MAX_EXPORT_ROWS:
        raise ExportTooLarge(total)
    return first, total


async def iter_csv(client: AutoCareClient, spec: dict, first: dict, total: int) -> AsyncIterator[bytes]:
    """CSV bytes, one page at a time. A UTF-8 byte order mark makes Excel read accents correctly."""
    page = first
    offset = 0
    columns: list[str] | None = None
    yield b"\xef\xbb\xbf"
    while True:
        rows = page.get("rows") if isinstance(page.get("rows"), list) else []
        if columns is None:
            columns = list(page.get("columns") or (rows[0].keys() if rows else []))
            yield _csv_line(columns).encode("utf-8")
        yield "".join(_csv_line([_cell(row.get(c)) for c in columns]) for row in rows).encode("utf-8")
        offset += len(rows)
        if not rows or offset >= total:
            return
        page = await _page(client, spec, offset)
