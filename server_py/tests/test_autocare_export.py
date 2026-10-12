import asyncio
import csv
import io

import pytest

from app.modules.chat_bot import autocare_export as ex


class PagingClient:
    """Answers `query` like the AutoCare server: `limit` rows from `offset`, plus the true total."""

    def __init__(self, total: int, page_size: int | None = None):
        self.total = total
        self.page_size = page_size
        self.calls: list[dict] = []

    async def call_tool(self, name, arguments):
        assert name == "query"
        spec = arguments["spec"]
        self.calls.append(spec)
        limit = min(spec["limit"], self.page_size or spec["limit"])
        offset = spec.get("offset", 0)
        rows = [{"client_id": i, "name": f"Customer, {i}"} for i in range(offset, min(offset + limit, self.total))]
        return {"columns": ["client_id", "name"], "rows": rows, "total_rows": self.total}


def _export(client, spec) -> list[list[str]]:
    async def go():
        first, total = await ex.start_export(client, spec)
        out = b""
        async for chunk in ex.iter_csv(client, spec, first, total):
            out += chunk
        return out

    raw = asyncio.run(go())
    assert raw.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


def test_prepare_spec_drops_limit_and_offset_and_adds_a_stable_order():
    view, spec = ex.prepare_spec(
        "customer_360_vw",
        {"view": "customer_360_vw", "columns": ["client_id", "name"], "limit": 100, "offset": 7},
    )
    assert view == "customer_360_vw"
    assert "limit" not in spec and "offset" not in spec
    assert spec["order_by"] == [{"column": "client_id", "direction": "asc"}]


def test_prepare_spec_keeps_the_order_the_user_asked_for():
    order = [{"column": "total_sessions", "direction": "desc"}]
    _view, spec = ex.prepare_spec(
        "customer_360_vw", {"view": "customer_360_vw", "columns": ["client_id"], "order_by": order}
    )
    assert spec["order_by"] == order


def test_prepare_spec_rejects_an_unknown_view():
    with pytest.raises(ValueError):
        ex.prepare_spec("not_a_view", {"view": "not_a_view"})


def test_export_reads_every_page_in_order_without_gaps():
    client = PagingClient(total=12000)
    rows = _export(client, {"view": "customer_360_vw"})
    assert rows[0] == ["client_id", "name"]
    assert len(rows) == 12001
    assert [r[0] for r in rows[1:]] == [str(i) for i in range(12000)]
    assert [c["offset"] for c in client.calls] == [0, 5000, 10000]
    assert all(c["limit"] == ex.PAGE_SIZE for c in client.calls)


def test_export_handles_a_server_that_returns_smaller_pages():
    client = PagingClient(total=7, page_size=3)
    rows = _export(client, {"view": "customer_360_vw"})
    assert [r[0] for r in rows[1:]] == [str(i) for i in range(7)]


def test_export_quotes_commas_in_cells():
    rows = _export(PagingClient(total=2), {"view": "customer_360_vw"})
    assert rows[1] == ["0", "Customer, 0"]


def test_export_of_an_empty_result_is_a_header_only_file():
    client = PagingClient(total=0)

    async def go():
        first, total = await ex.start_export(client, {"view": "customer_360_vw"})
        return [c async for c in ex.iter_csv(client, {"view": "customer_360_vw"}, first, total)]

    chunks = asyncio.run(go())
    assert len(client.calls) == 1
    assert b"".join(chunks) == b"\xef\xbb\xbfclient_id,name\n"


def test_export_refuses_a_result_above_the_cap_before_sending_anything():
    client = PagingClient(total=ex.MAX_EXPORT_ROWS + 1)
    with pytest.raises(ex.ExportTooLarge) as caught:
        asyncio.run(ex.start_export(client, {"view": "customer_360_vw"}))
    assert str(ex.MAX_EXPORT_ROWS + 1) not in str(caught.value) or "50,000" in str(caught.value)
    assert len(client.calls) == 1
