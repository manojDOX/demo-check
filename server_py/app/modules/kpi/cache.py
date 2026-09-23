"""Postgres cache for the BigQuery-backed /api/kpis/* payloads.

The dashboard and analytics pages fire 2-4 BigQuery queries per client/date-range on every load, so
each computed payload is stored and reused for KPI_CACHE_TTL_SECONDS. Rows are keyed by client,
endpoint and a hash of the request parameters, so each date range caches separately.

Naive UTC datetimes throughout, matching the other models' TIMESTAMP WITHOUT TIME ZONE columns.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kpi import KpiCache
from app.modules.kpi.config import KPI_CACHE_TTL_SECONDS


def params_hash(params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _get_row(db: AsyncSession, client_id: int, endpoint: str, params: dict) -> KpiCache | None:
    result = await db.execute(
        select(KpiCache).where(
            KpiCache.client_id == client_id,
            KpiCache.endpoint == endpoint,
            KpiCache.params_hash == params_hash(params),
        )
    )
    return result.scalar_one_or_none()


async def get(db: AsyncSession, client_id: int, endpoint: str, params: dict) -> dict | None:
    """The stored payload if it hasn't expired yet, else None."""
    row = await _get_row(db, client_id, endpoint, params)
    if row is None or row.expires_at <= datetime.utcnow():
        return None
    return row.payload


async def get_stale(db: AsyncSession, client_id: int, endpoint: str, params: dict) -> dict | None:
    """The stored payload regardless of age — used when BigQuery is unavailable."""
    row = await _get_row(db, client_id, endpoint, params)
    return row.payload if row is not None else None


async def put(db: AsyncSession, client_id: int, endpoint: str, params: dict, payload: dict) -> None:
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=KPI_CACHE_TTL_SECONDS)
    row = await _get_row(db, client_id, endpoint, params)
    if row is None:
        db.add(
            KpiCache(
                client_id=client_id,
                endpoint=endpoint,
                params_hash=params_hash(params),
                params=params,
                payload=payload,
                computed_at=now,
                expires_at=expires_at,
            )
        )
    else:
        row.params = params
        row.payload = payload
        row.computed_at = now
        row.expires_at = expires_at
    await db.commit()
