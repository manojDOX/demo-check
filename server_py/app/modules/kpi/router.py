"""Port of the `/api/kpis*` routes from server/routes.ts (~lines 1799-2112).

Pure orchestration over `BigQueryService` (app/modules/connections/bigquery_service.py) —
no SQL / calculation logic is reimplemented here.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import can_access_client, get_user_id, require_authenticated_or_token
from app.modules.connections.bigquery_service import BigQueryService
from app.modules.kpi import repo

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
    import re

    return isinstance(value, str) and re.match(_IDENTIFIER_RE, value) is not None


def _safe_date(value: Any) -> bool:
    import re

    return isinstance(value, str) and re.match(_DATE_RE, value) is not None


async def _load_connection(db: AsyncSession, client_id: Any) -> Any:
    """Common connection lookup shared by all BigQuery-backed KPI routes."""
    return await repo.get_connection_by_client_id(db, client_id)


# ---------------------------------------------------------------------------
# GET /api/kpis — mock data (verified: this is literally hardcoded in the TS
# source, not a real BigQuery-backed calculation). Ported as-is, mock included.
# ---------------------------------------------------------------------------


@router.get("/api/kpis")
async def get_kpis(request: Request, clientId: str | None = None):
    try:
        parsed_client_id: int | None = None
        if clientId:
            try:
                parsed_client_id = int(clientId)
            except ValueError:
                parsed_client_id = None

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
async def dashboard_kpis(
    body: DashboardBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        get_user_id(request)
        client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo

        if _missing(client_id) or _missing(date_from) or _missing(date_to):
            raise HTTPException(
                status_code=400, detail="clientId, dateFrom, and dateTo are required"
            )

        has_access = await can_access_client(request, db, client_id)
        if not has_access:
            raise HTTPException(status_code=404, detail="Client not found")

        connection = await _load_connection(db, client_id)
        if connection is None:
            raise HTTPException(
                status_code=400, detail="No BigQuery connection found for this client"
            )

        bq_service = BigQueryService.from_credentials_json(
            connection.project_id, connection.credentials, connection.dataset_id or None
        )

        kpis = await bq_service.calculate_dashboard_kpis(
            connection.dataset_id or "", date_from, date_to
        )

        return {
            **kpis,
            "period": {"from": date_from, "to": date_to},
            "source": "bigquery",
        }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500, detail=str(error) or "Failed to calculate dashboard KPIs"
        )


# ---------------------------------------------------------------------------
# POST /api/kpis/calculate
# ---------------------------------------------------------------------------


class CalculateBody(BaseModel):
    clientId: Any = None
    dateFrom: Any = None
    dateTo: Any = None
    dateColumn: str = "created"
    salesTable: str = "subscriptions"
    salesColumn: str = "amount"
    customerIdColumn: str = "customer_id"


def _calculate_change(current: float, previous: float) -> float:
    if previous == 0:
        return 100 if current > 0 else 0
    return ((current - previous) / previous) * 100


@router.post("/api/kpis/calculate")
async def calculate_kpis(
    body: CalculateBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        get_user_id(request)
        client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo

        if _missing(client_id) or _missing(date_from) or _missing(date_to):
            raise HTTPException(
                status_code=400, detail="clientId, dateFrom, and dateTo are required"
            )

        has_access = await can_access_client(request, db, client_id)
        if not has_access:
            raise HTTPException(status_code=404, detail="Client not found")

        connection = await _load_connection(db, client_id)
        if connection is None:
            raise HTTPException(
                status_code=400, detail="No BigQuery connection found for this client"
            )

        bq_service = BigQueryService.from_credentials_json(
            connection.project_id, connection.credentials, connection.dataset_id or None
        )

        kpis = await bq_service.calculate_kpis(
            connection.dataset_id or "",
            date_from,
            date_to,
            body.dateColumn,
            body.salesTable,
            body.salesColumn,
            body.customerIdColumn,
        )

        previous = kpis["previousPeriod"]

        return {
            "totalSales": kpis["totalSales"],
            "orderCount": kpis["orderCount"],
            "averageOrderValue": kpis["averageOrderValue"],
            "newCustomers": kpis["newCustomers"],
            "recurringCustomers": kpis["recurringCustomers"],
            "recurrenceRate": kpis["recurrenceRate"],
            "customerLtv": kpis["customerLtv"],
            "changes": {
                "totalSales": _calculate_change(kpis["totalSales"], previous["totalSales"]),
                "orderCount": _calculate_change(kpis["orderCount"], previous["orderCount"]),
                "averageOrderValue": _calculate_change(
                    kpis["averageOrderValue"], previous["averageOrderValue"]
                ),
                "newCustomers": _calculate_change(kpis["newCustomers"], previous["newCustomers"]),
                "recurringCustomers": _calculate_change(
                    kpis["recurringCustomers"], previous["recurringCustomers"]
                ),
                "recurrenceRate": _calculate_change(
                    kpis["recurrenceRate"], previous["recurrenceRate"]
                ),
                "customerLtv": _calculate_change(kpis["customerLtv"], previous["customerLtv"]),
            },
            "period": {"from": date_from, "to": date_to},
            "source": "bigquery",
        }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error) or "Failed to calculate KPIs")


# ---------------------------------------------------------------------------
# POST /api/kpis/trends
# ---------------------------------------------------------------------------


class TrendsBody(BaseModel):
    clientId: Any = None
    dateFrom: Any = None
    dateTo: Any = None
    dateColumn: str = "created"
    salesTable: str = "subscriptions"
    salesColumn: str = "amount"
    customerIdColumn: str = "customer_id"


@router.post("/api/kpis/trends")
async def calculate_trends(
    body: TrendsBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        get_user_id(request)
        client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo

        if _missing(client_id) or _missing(date_from) or _missing(date_to):
            raise HTTPException(
                status_code=400, detail="clientId, dateFrom, and dateTo are required"
            )

        has_access = await can_access_client(request, db, client_id)
        if not has_access:
            raise HTTPException(status_code=404, detail="Client not found")

        connection = await _load_connection(db, client_id)
        if connection is None:
            raise HTTPException(
                status_code=400, detail="No BigQuery connection found for this client"
            )

        bq_service = BigQueryService.from_credentials_json(
            connection.project_id, connection.credentials, connection.dataset_id or None
        )

        trends = await bq_service.calculate_trends(
            connection.dataset_id or "",
            date_from,
            date_to,
            body.dateColumn,
            body.salesTable,
            body.salesColumn,
            body.customerIdColumn,
        )

        return trends
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error) or "Failed to calculate trends")


# ---------------------------------------------------------------------------
# POST /api/kpis/product-analytics
# ---------------------------------------------------------------------------


class ProductAnalyticsBody(BaseModel):
    clientId: Any = None
    dateFrom: Any = None
    dateTo: Any = None
    dateColumn: str = "created"
    salesTable: str = "subscriptions"
    salesColumn: str = "amount"
    customerIdColumn: str = "customer_id"


@router.post("/api/kpis/product-analytics")
async def product_analytics(
    body: ProductAnalyticsBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        get_user_id(request)
        client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo

        if _missing(client_id) or _missing(date_from) or _missing(date_to):
            raise HTTPException(
                status_code=400, detail="clientId, dateFrom, and dateTo are required"
            )

        identifiers = {
            "dateColumn": body.dateColumn,
            "salesTable": body.salesTable,
            "salesColumn": body.salesColumn,
            "customerIdColumn": body.customerIdColumn,
        }
        for name, val in identifiers.items():
            if not _safe_identifier(val):
                raise HTTPException(status_code=400, detail=f"Invalid identifier: {name}")
        if not _safe_date(date_from) or not _safe_date(date_to):
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        has_access = await can_access_client(request, db, client_id)
        if not has_access:
            raise HTTPException(status_code=404, detail="Client not found")

        connection = await _load_connection(db, client_id)
        if connection is None:
            raise HTTPException(
                status_code=400, detail="No BigQuery connection found for this client"
            )

        bq_service = BigQueryService.from_credentials_json(
            connection.project_id, connection.credentials, connection.dataset_id or None
        )

        result = await bq_service.calculate_product_analytics(
            connection.dataset_id or "",
            date_from,
            date_to,
            body.dateColumn,
            body.salesTable,
            body.salesColumn,
            body.customerIdColumn,
        )

        return result
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500, detail=str(error) or "Failed to calculate product analytics"
        )


# ---------------------------------------------------------------------------
# POST /api/kpis/churn-analytics
# ---------------------------------------------------------------------------


class ChurnAnalyticsBody(BaseModel):
    clientId: Any = None
    dateFrom: Any = None
    dateTo: Any = None
    dateColumn: str = "created"
    salesTable: str = "subscriptions"
    salesColumn: str = "amount"


@router.post("/api/kpis/churn-analytics")
async def churn_analytics(
    body: ChurnAnalyticsBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        get_user_id(request)
        client_id, date_from, date_to = body.clientId, body.dateFrom, body.dateTo

        if _missing(client_id) or _missing(date_from) or _missing(date_to):
            raise HTTPException(
                status_code=400, detail="clientId, dateFrom, and dateTo are required"
            )

        identifiers = {
            "dateColumn": body.dateColumn,
            "salesTable": body.salesTable,
            "salesColumn": body.salesColumn,
        }
        for name, val in identifiers.items():
            if not _safe_identifier(val):
                raise HTTPException(status_code=400, detail=f"Invalid identifier: {name}")
        if not _safe_date(date_from) or not _safe_date(date_to):
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        has_access = await can_access_client(request, db, client_id)
        if not has_access:
            raise HTTPException(status_code=404, detail="Client not found")

        connection = await _load_connection(db, client_id)
        if connection is None:
            raise HTTPException(
                status_code=400, detail="No BigQuery connection found for this client"
            )

        bq_service = BigQueryService.from_credentials_json(
            connection.project_id, connection.credentials, connection.dataset_id or None
        )

        result = await bq_service.calculate_churn_analytics(
            connection.dataset_id or "",
            date_from,
            date_to,
            body.dateColumn,
            body.salesTable,
            body.salesColumn,
        )

        return result
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500, detail=str(error) or "Failed to calculate churn analytics"
        )
