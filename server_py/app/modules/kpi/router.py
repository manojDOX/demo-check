"""Port of the `/api/kpis*` routes from server/routes.ts (~lines 1799-2112).

The five BigQuery-backed routes compute their numbers from the curated marketing_analytics_ss views
(app/modules/kpi/metrics.py) and reuse each payload for KPI_CACHE_TTL_SECONDS (app/modules/kpi/
cache.py). Response shapes are unchanged — client/src/pages/dashboard.tsx and analytics.tsx read them
as-is. `GET /api/kpis` stays the mock it always was.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import can_access_client, get_user_id, require_authenticated_or_token
from app.modules.connections.bigquery_service import BigQueryService
from app.modules.kpi import cache, metrics, repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["kpis"], dependencies=[Depends(require_authenticated_or_token)])


def _js_iso(dt: datetime) -> str:
    """Mimic JS `new Date().toJSON()` formatting (ms precision + trailing Z)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _missing(value: Any) -> bool:
    """Mirrors JS falsy-check semantics (`!clientId || !dateFrom || !dateTo`) for the
    plain-JSON request bodies these routes accept."""
    return value is None or value == "" or value is False


_IDENTIFIER_RE = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"


def _safe_identifier(value: Any) -> bool:
    return isinstance(value, str) and re.match(_IDENTIFIER_RE, value) is not None


def _safe_date(value: Any) -> bool:
    return isinstance(value, str) and re.match(_DATE_RE, value) is not None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _load_connection(db: AsyncSession, client_id: Any) -> Any:
    """Common connection lookup shared by all BigQuery-backed KPI routes."""
    return await repo.get_connection_by_client_id(db, client_id)


async def _cache_read(
    db: AsyncSession, client_id: int | None, endpoint: str, params: dict, *, stale: bool = False
) -> dict | None:
    """Cache access is best-effort: if the table is missing (a migration that hasn't run — see
    app/main.py's _run_pending_migrations) or the read fails, fall through to a fresh query."""
    if client_id is None:
        return None
    try:
        reader = cache.get_stale if stale else cache.get
        return await reader(db, client_id, endpoint, params)
    except Exception:
        logger.warning("KPI cache read failed for %s", endpoint, exc_info=True)
        return None


async def _cache_write(
    db: AsyncSession, client_id: int | None, endpoint: str, params: dict, payload: dict
) -> None:
    if client_id is None:
        return
    try:
        await cache.put(db, client_id, endpoint, params, payload)
    except Exception:
        logger.warning("KPI cache write failed for %s", endpoint, exc_info=True)


async def _cached_payload(
    db: AsyncSession,
    request: Request,
    client_id: Any,
    endpoint: str,
    params: dict,
    compute: Callable[[BigQueryService], Awaitable[dict]],
    failure_detail: str,
) -> dict:
    """Access check -> cache read -> compute -> cache write, with a stale payload as the
    fallback when BigQuery is unavailable (a stale dashboard beats an empty one)."""
    if not await can_access_client(request, db, client_id):
        raise HTTPException(status_code=404, detail="Client not found")

    cache_client_id = _as_int(client_id)
    cached = await _cache_read(db, cache_client_id, endpoint, params)
    if cached is not None:
        return cached

    connection = await _load_connection(db, client_id)
    if connection is None:
        raise HTTPException(status_code=400, detail="No BigQuery connection found for this client")

    bq_service = BigQueryService.from_credentials_json(
        connection.project_id, connection.credentials, connection.dataset_id or None
    )

    try:
        payload = await compute(bq_service)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        stale = await _cache_read(db, cache_client_id, endpoint, params, stale=True)
        if stale is not None:
            logger.warning("KPI %s failed, serving stale cache: %s", endpoint, error)
            return stale
        logger.exception("KPI %s failed", endpoint)
        raise HTTPException(status_code=500, detail=str(error) or failure_detail) from error

    payload = {**payload, "cachedAt": _js_iso(datetime.now(timezone.utc))}
    await _cache_write(db, cache_client_id, endpoint, params, payload)
    return payload


def _require_period(client_id: Any, date_from: Any, date_to: Any) -> None:
    if _missing(client_id) or _missing(date_from) or _missing(date_to):
        raise HTTPException(status_code=400, detail="clientId, dateFrom, and dateTo are required")


# ---------------------------------------------------------------------------
# GET /api/kpis — mock data (verified: this is literally hardcoded in the TS
# source, not a real BigQuery-backed calculation). Ported as-is, mock included.
# ---------------------------------------------------------------------------


@router.get("/api/kpis")
async def get_kpis(request: Request, clientId: str | None = None):
    try:
        parsed_client_id: int | None = None
        if clientId:
            parsed_client_id = _as_int(clientId)

        now = _js_iso(datetime.now(timezone.utc))

        mock_kpis = [
            {
                "id": 1,
                "clientId": parsed_client_id or 1,
                "date": now,
                "totalSales": "1250000",
                "orderCount": 15234,
                "averageOrderValue": "82.05",
                "recurrenceRate": "34.5",
                "newCustomers": 3421,
                "recurringCustomers": 5280,
                "cartAbandonmentRate": "68.2",
                "customerLifetimeValue": "342",
                "returnRate": "8.5",
                "inventoryTurnover": "4.2",
                "rawData": {},
                "createdAt": now,
            }
        ]

        return mock_kpis
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch KPIs")


# ---------------------------------------------------------------------------
# POST /api/kpis/dashboard
# ---------------------------------------------------------------------------


class DashboardBody(BaseModel):
    clientId: Any = None
    dateFrom: Any = None
    dateTo: Any = None


@router.post("/api/kpis/dashboard")
async def dashboard_kpis(body: DashboardBody, request: Request, db: AsyncSession = Depends(get_db)):
    get_user_id(request)
    client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo
    _require_period(client_id, date_from, date_to)

    async def compute(bq: BigQueryService) -> dict:
        kpis = await metrics.dashboard_kpis(bq, date_from, date_to)
        return {**kpis, "period": {"from": date_from, "to": date_to}, "source": "bigquery"}

    return await _cached_payload(
        db,
        request,
        client_id,
        "dashboard",
        {"dateFrom": date_from, "dateTo": date_to},
        compute,
        "Failed to calculate dashboard KPIs",
    )


# ---------------------------------------------------------------------------
# POST /api/kpis/calculate
# ---------------------------------------------------------------------------


class CalculateBody(BaseModel):
    clientId: Any = None
    dateFrom: Any = None
    dateTo: Any = None


def _calculate_change(current: float, previous: float) -> float:
    if previous == 0:
        return 100 if current > 0 else 0
    return ((current - previous) / previous) * 100


@router.post("/api/kpis/calculate")
async def calculate_kpis(body: CalculateBody, request: Request, db: AsyncSession = Depends(get_db)):
    get_user_id(request)
    client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo
    _require_period(client_id, date_from, date_to)

    async def compute(bq: BigQueryService) -> dict:
        kpis = await metrics.period_kpis(bq, date_from, date_to)
        previous = kpis["previousPeriod"]
        metric_names = (
            "totalSales",
            "orderCount",
            "averageOrderValue",
            "newCustomers",
            "recurringCustomers",
            "recurrenceRate",
            "customerLtv",
        )
        return {
            **{name: kpis[name] for name in metric_names},
            "changes": {name: _calculate_change(kpis[name], previous[name]) for name in metric_names},
            "period": {"from": date_from, "to": date_to},
            "source": "bigquery",
        }

    return await _cached_payload(
        db,
        request,
        client_id,
        "calculate",
        {"dateFrom": date_from, "dateTo": date_to},
        compute,
        "Failed to calculate KPIs",
    )


# ---------------------------------------------------------------------------
# POST /api/kpis/trends
# ---------------------------------------------------------------------------


class TrendsBody(BaseModel):
    clientId: Any = None
    dateFrom: Any = None
    dateTo: Any = None


@router.post("/api/kpis/trends")
async def calculate_trends(body: TrendsBody, request: Request, db: AsyncSession = Depends(get_db)):
    get_user_id(request)
    client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo
    _require_period(client_id, date_from, date_to)

    return await _cached_payload(
        db,
        request,
        client_id,
        "trends",
        {"dateFrom": date_from, "dateTo": date_to},
        lambda bq: metrics.trends(bq, date_from, date_to),
        "Failed to calculate trends",
    )


# ---------------------------------------------------------------------------
# POST /api/kpis/product-analytics
# ---------------------------------------------------------------------------


class ProductAnalyticsBody(BaseModel):
    clientId: Any = None
    dateFrom: Any = None
    dateTo: Any = None


@router.post("/api/kpis/product-analytics")
async def product_analytics(
    body: ProductAnalyticsBody, request: Request, db: AsyncSession = Depends(get_db)
):
    get_user_id(request)
    client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo
    _require_period(client_id, date_from, date_to)
    if not _safe_date(date_from) or not _safe_date(date_to):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    return await _cached_payload(
        db,
        request,
        client_id,
        "product-analytics",
        {"dateFrom": date_from, "dateTo": date_to},
        lambda bq: metrics.product_analytics(bq, date_from, date_to),
        "Failed to calculate product analytics",
    )


# ---------------------------------------------------------------------------
# POST /api/kpis/churn-analytics
# ---------------------------------------------------------------------------


class ChurnAnalyticsBody(BaseModel):
    clientId: Any = None
    dateFrom: Any = None
    dateTo: Any = None


@router.post("/api/kpis/churn-analytics")
async def churn_analytics(
    body: ChurnAnalyticsBody, request: Request, db: AsyncSession = Depends(get_db)
):
    get_user_id(request)
    client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo
    _require_period(client_id, date_from, date_to)
    if not _safe_date(date_from) or not _safe_date(date_to):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    return await _cached_payload(
        db,
        request,
        client_id,
        "churn-analytics",
        {"dateFrom": date_from, "dateTo": date_to},
        lambda bq: metrics.churn_analytics(bq, date_from, date_to),
        "Failed to calculate churn analytics",
    )
