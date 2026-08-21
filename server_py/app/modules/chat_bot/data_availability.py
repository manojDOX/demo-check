"""Computes, once per connection, the true earliest date present in the raw AutoCare-sourced
BigQuery tables that feed the marketing_analytics_ss.* semantic views (see prompts.py).

Unlike stripe_ss.subscription/stripe_ss.customer (pulled from Stripe's API, which can return full
history), autocare_ss.data and autocare_ss.stripe_customers are pulled from AutoCare's own API,
which cannot backfill data before a fixed point in time (confirmed with the client: a fixed
backfill start date, not a rolling window — so this genuinely only needs to be computed once per
connection, not refreshed periodically). Without knowing that floor, the SQL-generation prompt has
no way to tell the model that an empty result for a date-scoped question reaching further back
means "no data exists," not "nothing happened."

Public interface (depended on by sql_agent.py):

    async def get_min_dates(db: AsyncSession, connection: BigQueryConnection) -> tuple[str | None, str | None]
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connections import BigQueryConnection
from app.modules.connections import repo as connections_repo
from app.modules.connections.bigquery_service import BigQueryService

logger = logging.getLogger(__name__)

# Hardcoded, matching how prompts.py already hardcodes the marketing_analytics_ss.* view names as
# constants — this deployment is single-schema (one specific AutoCare BigQuery layout), not a
# generic multi-tenant arbitrary-schema product.
_SESSION_DATE_SQL = (
    "SELECT MIN(session_date) AS min_date FROM `{project_id}.autocare_ss.data` "
    "WHERE session_id IS NOT NULL AND session_date IS NOT NULL"
)
_CUSTOMER_CREATED_SQL = (
    "SELECT MIN(customer_created_date) AS min_date FROM `{project_id}.autocare_ss.stripe_customers` "
    "WHERE customer_created_date IS NOT NULL"
)


def _format_date(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _to_naive_utc(value: datetime | date | None) -> datetime | date | None:
    """BigQuery's client library returns TIMESTAMP columns as timezone-aware datetimes, but
    bigquery_connections.min_session_date/min_customer_created_date are naive DateTime columns
    (TIMESTAMP WITHOUT TIME ZONE, matching this codebase's existing convention — see repo.py's
    touch_session/clear_session_history comments). Persisting an aware value straight through
    breaks asyncpg's encoder ("can't subtract offset-naive and offset-aware datetimes"), so
    convert to naive UTC first — the same normalization, just applied here instead of via
    datetime.utcnow() since this value comes from BigQuery, not generated locally."""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


async def _query_min_date_raw(service: BigQueryService, sql_template: str, project_id: str):
    """Returns the raw datetime/date value from BigQuery, normalized to naive UTC (suitable for
    persisting straight into the DateTime column), or None on an empty/failed result. Uses the
    public execute_query (not the MCP client — this reads the raw autocare_ss tables directly,
    not the semantic views the chat pipeline queries through MCP) so the same SELECT-only safety
    validation applies."""
    try:
        result = await service.execute_query(sql_template.format(project_id=project_id), max_rows=1)
    except Exception as exc:  # noqa: BLE001 - best-effort, never blocks the chat turn
        logger.warning("data_availability: min-date query failed: %s", exc)
        return None
    if not result.rows:
        return None
    return _to_naive_utc(result.rows[0].get("min_date"))


async def get_min_dates(db: AsyncSession, connection: BigQueryConnection) -> tuple[str | None, str | None]:
    """Returns (min_session_date, min_customer_created_date) as 'YYYY-MM-DD' strings.

    Fast path: both already cached on `connection` (the common case after the first-ever chat
    turn for this connection) — no BigQuery call at all.
    Slow path: runs the two MIN() queries once, persists whichever succeed (as real datetime
    values, not strings — the model column is DateTime) via connections_repo.update_connection,
    and returns what was found as formatted strings for the prompt. A query that fails logs and
    returns None for that value without persisting, so it's naturally retried on the next turn
    rather than permanently caching a failure as if it were a real (missing) result.
    """
    if connection.min_session_date is not None and connection.min_customer_created_date is not None:
        return _format_date(connection.min_session_date), _format_date(connection.min_customer_created_date)

    try:
        service = BigQueryService.from_credentials_json(connection.project_id, connection.credentials)
    except Exception as exc:  # noqa: BLE001 - best-effort, never blocks the chat turn
        logger.warning("data_availability: couldn't build BigQueryService: %s", exc)
        return _format_date(connection.min_session_date), _format_date(connection.min_customer_created_date)

    min_session_date_raw = connection.min_session_date or await _query_min_date_raw(
        service, _SESSION_DATE_SQL, connection.project_id
    )
    min_customer_created_raw = connection.min_customer_created_date or await _query_min_date_raw(
        service, _CUSTOMER_CREATED_SQL, connection.project_id
    )

    update_fields = {}
    if connection.min_session_date is None and min_session_date_raw is not None:
        update_fields["min_session_date"] = min_session_date_raw
    if connection.min_customer_created_date is None and min_customer_created_raw is not None:
        update_fields["min_customer_created_date"] = min_customer_created_raw
    if update_fields:
        await connections_repo.update_connection(db, connection.id, update_fields)

    return _format_date(min_session_date_raw), _format_date(min_customer_created_raw)
