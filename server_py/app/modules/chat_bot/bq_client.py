"""Thin wrapper around connections/bigquery_service.py's BigQueryService providing the
extra primitives the retry loop needs (dry_run, get_date_range) plus a passthrough for
execute_query. Every call into the synchronous BigQuery SDK is asyncio.to_thread-wrapped
(dry_run directly here; execute_query/discover_schema* already wrapped inside
BigQueryService itself).
"""

from __future__ import annotations

import asyncio

from google.cloud import bigquery

from app.modules.connections.bigquery_service import BigQueryService, QueryResult


def make_service(connection) -> BigQueryService:
    """Build a BigQueryService from a BigQueryConnection ORM row. `connection.credentials`
    is already the decrypted plaintext service-account JSON (EncryptedString column type
    decrypts transparently on attribute read)."""
    return BigQueryService.from_credentials_json(
        connection.project_id, connection.credentials, connection.dataset_id or None
    )


async def dry_run(bq: BigQueryService, sql: str) -> tuple[bool, str | None]:
    """Validates a query without executing/billing it. Returns (ok, error_message)."""

    def _run() -> None:
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        bq.client.query(sql, job_config=job_config)

    try:
        await asyncio.to_thread(_run)
        return True, None
    except Exception as error:
        return False, str(error)


async def execute_query(bq: BigQueryService, sql: str, max_rows: int = 2000, timeout_ms: int = 30000) -> QueryResult:
    return await bq.execute_query(sql, max_rows=max_rows, timeout_ms=timeout_ms)


async def get_date_range(bq: BigQueryService, table_full_name: str, date_column: str = "date") -> tuple[str | None, str | None]:
    """Best-effort MIN/MAX of a table's date column, used only to ground the schema
    context with real data recency. Returns (None, None) on any failure — never blocks
    the pipeline."""
    sql = f"SELECT MIN({date_column}) AS min_date, MAX({date_column}) AS max_date FROM `{table_full_name}`"
    try:
        result = await bq.execute_query(sql, max_rows=1)
        row = result.rows[0] if result.rows else {}
        min_date = row.get("min_date")
        max_date = row.get("max_date")
        return (str(min_date) if min_date is not None else None, str(max_date) if max_date is not None else None)
    except Exception:
        return None, None
