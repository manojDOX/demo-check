"""Port of server/services/bigquery.ts's BigQueryService class.

Every blocking call into the synchronous google-cloud-bigquery SDK is wrapped in
asyncio.to_thread(...) so it never stalls the event loop / other concurrent requests.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field

from google.cloud import bigquery
from google.oauth2 import service_account


@dataclass
class SchemaColumn:
    dataset_name: str
    table_name: str
    column_name: str
    data_type: str
    is_nullable: bool
    description: str | None = None


@dataclass
class QueryResult:
    rows: list[dict]
    total_rows: int
    schema: list[dict]
    execution_time_ms: int


# DDL/DML keywords that should never appear anywhere in a query we execute.
_FORBIDDEN_KEYWORDS = [
    "DROP", "DELETE", "TRUNCATE", "INSERT", "UPDATE", "CREATE",
    "ALTER", "GRANT", "REVOKE", "MERGE", "CALL", "EXECUTE",
]


class BigQueryService:
    def __init__(self, project_id: str, credentials: dict, dataset_id: str | None = None):
        # Trim whitespace from projectId and datasetId to prevent errors.
        self.project_id = (project_id or "").strip()
        self.dataset_id = dataset_id.strip() if dataset_id else None

        if not self.project_id:
            raise ValueError("ProjectId is required and cannot be empty")

        creds = service_account.Credentials.from_service_account_info(credentials)
        self.client = bigquery.Client(project=self.project_id, credentials=creds)

    @classmethod
    def from_credentials_json(
        cls, project_id: str, credentials_json: str, dataset_id: str | None = None
    ) -> "BigQueryService":
        try:
            credentials = json.loads(credentials_json)
        except Exception as e:
            raise ValueError("Invalid service account JSON credentials") from e
        return cls(
            project_id=(project_id or "").strip(),
            credentials=credentials,
            dataset_id=dataset_id.strip() if dataset_id else None,
        )

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict:
        try:
            def _run():
                return list(self.client.list_datasets(max_results=1))

            datasets = await asyncio.to_thread(_run)
            return {
                "success": True,
                "message": f"Connected successfully. Found {'datasets' if len(datasets) > 0 else 'no datasets'} in project.",
            }
        except Exception as error:
            message = str(error) or "Unknown error"
            if "Permission denied" in message or "403" in message:
                return {
                    "success": False,
                    "message": "Permission denied. Ensure service account has BigQuery Data Viewer role.",
                }
            if "Invalid JWT" in message or "invalid_grant" in message:
                return {
                    "success": False,
                    "message": "Invalid credentials. Check your service account JSON.",
                }
            return {"success": False, "message": message}

    # ------------------------------------------------------------------
    # Schema discovery (BigQuery API based)
    # ------------------------------------------------------------------

    async def discover_schema(self, dataset_id: str | None = None) -> list[SchemaColumn]:
        target_dataset = dataset_id or self.dataset_id

        def _run() -> list[SchemaColumn]:
            schemas: list[SchemaColumn] = []
            if target_dataset:
                tables = list(self.client.list_tables(target_dataset))
                for table_item in tables:
                    full_table = self.client.get_table(table_item.reference)
                    for field_ in full_table.schema:
                        schemas.append(
                            SchemaColumn(
                                dataset_name=target_dataset,
                                table_name=table_item.table_id or "",
                                column_name=field_.name or "",
                                data_type=field_.field_type or "STRING",
                                is_nullable=field_.mode != "REQUIRED",
                                description=field_.description,
                            )
                        )
            else:
                datasets = list(self.client.list_datasets())
                for dataset in datasets:
                    dataset_name = dataset.dataset_id or ""
                    tables = list(self.client.list_tables(dataset_name))
                    for table_item in tables:
                        full_table = self.client.get_table(table_item.reference)
                        for field_ in full_table.schema:
                            schemas.append(
                                SchemaColumn(
                                    dataset_name=dataset_name,
                                    table_name=table_item.table_id or "",
                                    column_name=field_.name or "",
                                    data_type=field_.field_type or "STRING",
                                    is_nullable=field_.mode != "REQUIRED",
                                    description=field_.description,
                                )
                            )
            return schemas

        try:
            return await asyncio.to_thread(_run)
        except Exception as error:
            raise RuntimeError(f"Failed to discover schema: {error}") from error

    # ------------------------------------------------------------------
    # SQL safety validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_query_safety(sql: str) -> None:
        normalized_sql = re.sub(r"\s+", " ", sql).strip().upper()

        # Reject queries with semicolons (multi-statement prevention).
        if ";" in sql:
            raise ValueError("Multi-statement queries are not allowed.")

        for keyword in _FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{keyword}\b", normalized_sql, re.IGNORECASE):
                raise ValueError(
                    f"Query contains forbidden keyword '{keyword}'. Only SELECT queries are permitted."
                )

        if not normalized_sql.startswith("SELECT") and not normalized_sql.startswith("WITH"):
            raise ValueError("Query must start with SELECT or WITH. Only SELECT queries are permitted.")

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    async def execute_query(
        self, sql: str, max_rows: int = 2000, timeout_ms: int = 30000
    ) -> QueryResult:
        self._validate_query_safety(sql)

        start_time = time.monotonic()

        def _run():
            job_config = bigquery.QueryJobConfig(maximum_bytes_billed=1_000_000_000)
            job = self.client.query(sql, job_config=job_config)
            result_iter = job.result(max_results=max_rows, timeout=timeout_ms / 1000)
            rows = [dict(row.items()) for row in result_iter]
            schema_fields = job.schema or []
            schema = [{"name": f.name, "type": f.field_type} for f in schema_fields]
            total_rows = result_iter.total_rows if result_iter.total_rows is not None else len(rows)
            return rows, schema, total_rows

        try:
            rows, schema, total_rows = await asyncio.to_thread(_run)
        except Exception as error:
            raise RuntimeError(f"Query execution failed: {error}") from error

        return QueryResult(
            rows=rows,
            total_rows=total_rows,
            schema=schema,
            execution_time_ms=int((time.monotonic() - start_time) * 1000),
        )

    # ------------------------------------------------------------------
    # Schema discovery via INFORMATION_SCHEMA (SQL fallback)
    # ------------------------------------------------------------------

    async def discover_schema_via_sql(self, dataset_id: str | None = None) -> list[SchemaColumn]:
        target_dataset = dataset_id or self.dataset_id

        if target_dataset:
            sql = f"""
          SELECT
            table_catalog as project_id,
            table_schema as dataset_name,
            table_name,
            column_name,
            data_type,
            is_nullable
          FROM `{self.project_id}.{target_dataset}.INFORMATION_SCHEMA.COLUMNS`
          ORDER BY table_name, ordinal_position
        """
            try:
                result = await self.execute_query(sql, max_rows=5000)
            except Exception as error:
                raise RuntimeError(f"Failed to discover schema via SQL: {error}") from error

            schemas: list[SchemaColumn] = []
            for row in result.rows:
                schemas.append(
                    SchemaColumn(
                        dataset_name=row.get("dataset_name") or target_dataset,
                        table_name=row.get("table_name"),
                        column_name=row.get("column_name"),
                        data_type=row.get("data_type"),
                        is_nullable=row.get("is_nullable") == "YES",
                        description=None,
                    )
                )
            return schemas

        # No specific dataset - iterate ALL datasets in the project.
        all_schemas: list[SchemaColumn] = []
        try:
            datasets = await asyncio.to_thread(lambda: list(self.client.list_datasets()))
        except Exception as error:
            raise RuntimeError(f"Failed to discover schema via SQL: {error}") from error

        for dataset in datasets:
            ds_id = dataset.dataset_id
            if not ds_id:
                continue
            try:
                ds_schemas = await self.discover_schema_via_sql(ds_id)
                all_schemas.extend(ds_schemas)
            except Exception:
                # matches JS behavior: log and skip this dataset, don't fail the whole call
                pass
        return all_schemas

    # ------------------------------------------------------------------
    # Raw (unvalidated, non-throttled) query helper used by the analytics
    # methods below - mirrors `this.client.query({ query: sql })` in the JS
    # source, which bypasses executeQuery's safety validation & row cap.
    # ------------------------------------------------------------------

    async def _query_all(self, sql: str) -> list[dict]:
        def _run():
            job = self.client.query(sql)
            return [dict(row.items()) for row in job.result()]

        return await asyncio.to_thread(_run)

    # ------------------------------------------------------------------
    # KPI / trend / product / churn analytics SQL-builder methods
    # ------------------------------------------------------------------

    async def calculate_kpis(
        self,
        dataset_id: str,
        date_from: str,
        date_to: str,
        date_column: str = "created",
        sales_table: str = "subscriptions",
        sales_column: str = "amount",
        customer_id_column: str = "customer_id",
    ) -> dict:
        target_dataset = dataset_id or self.dataset_id
        if not target_dataset:
            raise ValueError("Dataset ID is required for KPI calculation")

        fully_qualified_table = f"`{self.project_id}.{target_dataset}.{sales_table}`"

        sql = f"""
      WITH date_params AS (
        SELECT
          DATE('{date_from}') as current_start,
          DATE('{date_to}') as current_end,
          DATE_DIFF(DATE('{date_to}'), DATE('{date_from}'), DAY) as period_days
      ),
      previous_params AS (
        SELECT
          DATE_SUB(current_start, INTERVAL period_days + 1 DAY) as prev_start,
          DATE_SUB(current_start, INTERVAL 1 DAY) as prev_end,
          current_start,
          current_end
        FROM date_params
      ),
      current_period AS (
        SELECT
          COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as total_sales,
          COUNT(*) as order_count,
          COALESCE(AVG(CAST({sales_column} AS FLOAT64)), 0) as avg_order_value,
          COUNT(DISTINCT {customer_id_column}) as unique_customers
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) BETWEEN (SELECT current_start FROM previous_params) AND (SELECT current_end FROM previous_params)
      ),
      previous_period AS (
        SELECT
          COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as total_sales,
          COUNT(*) as order_count,
          COALESCE(AVG(CAST({sales_column} AS FLOAT64)), 0) as avg_order_value,
          COUNT(DISTINCT {customer_id_column}) as unique_customers
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) BETWEEN (SELECT prev_start FROM previous_params) AND (SELECT prev_end FROM previous_params)
      ),
      returning_customers_current AS (
        SELECT COUNT(DISTINCT c.{customer_id_column}) as returning_count
        FROM {fully_qualified_table} c
        WHERE DATE(c.{date_column}) BETWEEN (SELECT current_start FROM previous_params) AND (SELECT current_end FROM previous_params)
        AND c.{customer_id_column} IN (
          SELECT DISTINCT {customer_id_column}
          FROM {fully_qualified_table}
          WHERE DATE({date_column}) < (SELECT current_start FROM previous_params)
        )
      ),
      returning_customers_prev AS (
        SELECT COUNT(DISTINCT c.{customer_id_column}) as returning_count
        FROM {fully_qualified_table} c
        WHERE DATE(c.{date_column}) BETWEEN (SELECT prev_start FROM previous_params) AND (SELECT prev_end FROM previous_params)
        AND c.{customer_id_column} IN (
          SELECT DISTINCT {customer_id_column}
          FROM {fully_qualified_table}
          WHERE DATE({date_column}) < (SELECT prev_start FROM previous_params)
        )
      ),
      ltv_current AS (
        SELECT COALESCE(AVG(customer_total), 0) as avg_ltv
        FROM (
          SELECT {customer_id_column}, SUM(CAST({sales_column} AS FLOAT64)) as customer_total
          FROM {fully_qualified_table}
          WHERE {customer_id_column} IN (
            SELECT DISTINCT {customer_id_column}
            FROM {fully_qualified_table}
            WHERE DATE({date_column}) BETWEEN (SELECT current_start FROM previous_params) AND (SELECT current_end FROM previous_params)
          )
          GROUP BY {customer_id_column}
        )
      ),
      ltv_prev AS (
        SELECT COALESCE(AVG(customer_total), 0) as avg_ltv
        FROM (
          SELECT {customer_id_column}, SUM(CAST({sales_column} AS FLOAT64)) as customer_total
          FROM {fully_qualified_table}
          WHERE {customer_id_column} IN (
            SELECT DISTINCT {customer_id_column}
            FROM {fully_qualified_table}
            WHERE DATE({date_column}) BETWEEN (SELECT prev_start FROM previous_params) AND (SELECT prev_end FROM previous_params)
          )
          GROUP BY {customer_id_column}
        )
      )
      SELECT
        cp.total_sales as current_total_sales,
        cp.order_count as current_order_count,
        cp.avg_order_value as current_avg_order_value,
        cp.unique_customers as current_unique_customers,
        COALESCE(rcc.returning_count, 0) as current_returning_customers,
        COALESCE(lc.avg_ltv, 0) as current_ltv,
        pp.total_sales as prev_total_sales,
        pp.order_count as prev_order_count,
        pp.avg_order_value as prev_avg_order_value,
        pp.unique_customers as prev_unique_customers,
        COALESCE(rcp.returning_count, 0) as prev_returning_customers,
        COALESCE(lp.avg_ltv, 0) as prev_ltv
      FROM current_period cp
      CROSS JOIN previous_period pp
      CROSS JOIN returning_customers_current rcc
      CROSS JOIN returning_customers_prev rcp
      CROSS JOIN ltv_current lc
      CROSS JOIN ltv_prev lp
    """

        try:
            result = await self.execute_query(sql, max_rows=1)
            row = result.rows[0] if result.rows else {}

            current_returning = float(row.get("current_returning_customers") or 0)
            current_unique = float(row.get("current_unique_customers") or 0)
            current_new = current_unique - current_returning
            current_recurrence_rate = (current_returning / current_unique) * 100 if current_unique > 0 else 0

            prev_returning = float(row.get("prev_returning_customers") or 0)
            prev_unique = float(row.get("prev_unique_customers") or 0)
            prev_new = prev_unique - prev_returning
            prev_recurrence_rate = (prev_returning / prev_unique) * 100 if prev_unique > 0 else 0

            return {
                "totalSales": float(row.get("current_total_sales") or 0),
                "orderCount": float(row.get("current_order_count") or 0),
                "averageOrderValue": float(row.get("current_avg_order_value") or 0),
                "newCustomers": max(0, current_new),
                "recurringCustomers": current_returning,
                "recurrenceRate": current_recurrence_rate,
                "customerLtv": float(row.get("current_ltv") or 0),
                "previousPeriod": {
                    "totalSales": float(row.get("prev_total_sales") or 0),
                    "orderCount": float(row.get("prev_order_count") or 0),
                    "averageOrderValue": float(row.get("prev_avg_order_value") or 0),
                    "newCustomers": max(0, prev_new),
                    "recurringCustomers": prev_returning,
                    "recurrenceRate": prev_recurrence_rate,
                    "customerLtv": float(row.get("prev_ltv") or 0),
                },
            }
        except Exception as error:
            raise RuntimeError(f"KPI calculation failed: {error}") from error

    async def calculate_trends(
        self,
        dataset_id: str,
        date_from: str,
        date_to: str,
        date_column: str = "created",
        sales_table: str = "subscriptions",
        sales_column: str = "amount",
        customer_id_column: str = "customer_id",
    ) -> dict:
        from datetime import datetime

        target_dataset = dataset_id or self.dataset_id
        if not target_dataset:
            raise ValueError("Dataset ID is required for trend calculation")

        fully_qualified_table = f"`{self.project_id}.{target_dataset}.{sales_table}`"

        days_diff = (datetime.fromisoformat(date_to) - datetime.fromisoformat(date_from)).days
        group_by = "MONTH" if days_diff > 90 else "ISOWEEK" if days_diff > 31 else "DAY"
        trunc_expr = (
            f"DATE({date_column})"
            if group_by == "DAY"
            else f"DATE_TRUNC(DATE({date_column}), ISOWEEK)"
            if group_by == "ISOWEEK"
            else f"DATE_TRUNC(DATE({date_column}), MONTH)"
        )

        sales_sql = f"""
      SELECT
        {trunc_expr} as period_date,
        COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as total_sales,
        COUNT(*) as order_count
      FROM {fully_qualified_table}
      WHERE DATE({date_column}) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
      GROUP BY period_date
      ORDER BY period_date
    """

        customer_sql = f"""
      WITH first_purchase AS (
        SELECT {customer_id_column}, MIN(DATE({date_column})) as first_date
        FROM {fully_qualified_table}
        GROUP BY {customer_id_column}
      ),
      period_customers AS (
        SELECT
          {trunc_expr} as period_date,
          t.{customer_id_column},
          fp.first_date
        FROM {fully_qualified_table} t
        JOIN first_purchase fp ON t.{customer_id_column} = fp.{customer_id_column}
        WHERE DATE(t.{date_column}) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
      )
      SELECT
        period_date,
        COUNT(DISTINCT CASE WHEN first_date >= DATE('{date_from}') THEN {customer_id_column} END) as new_customers,
        COUNT(DISTINCT CASE WHEN first_date < DATE('{date_from}') THEN {customer_id_column} END) as returning_customers
      FROM period_customers
      GROUP BY period_date
      ORDER BY period_date
    """

        sales_rows, customer_rows = await asyncio.gather(
            self._query_all(sales_sql), self._query_all(customer_sql)
        )

        sales_trend = [
            {
                "date": str(row.get("period_date")),
                "sales": float(row.get("total_sales") or 0),
                "orders": float(row.get("order_count") or 0),
            }
            for row in sales_rows
        ]

        customer_trend = [
            {
                "date": str(row.get("period_date")),
                "newCustomers": float(row.get("new_customers") or 0),
                "returningCustomers": float(row.get("returning_customers") or 0),
            }
            for row in customer_rows
        ]

        return {"salesTrend": sales_trend, "customerTrend": customer_trend}

    async def calculate_product_analytics(
        self,
        dataset_id: str,
        date_from: str,
        date_to: str,
        date_column: str = "created",
        sales_table: str = "subscriptions",
        sales_column: str = "amount",
        customer_id_column: str = "customer_id",
    ) -> dict:
        from datetime import datetime

        target_dataset = dataset_id or self.dataset_id
        if not target_dataset:
            raise ValueError("Dataset ID is required for product analytics")

        fully_qualified_table = f"`{self.project_id}.{target_dataset}.{sales_table}`"

        top_products_sql = f"""
      SELECT
        COALESCE(plan_name, 'Unknown') as plan_name,
        COALESCE(product_id, 'N/A') as product_id,
        COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as revenue,
        COUNT(*) as subscription_count,
        COALESCE(AVG(CAST({sales_column} AS FLOAT64)), 0) as avg_amount
      FROM {fully_qualified_table}
      WHERE DATE({date_column}) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
      GROUP BY plan_name, product_id
      ORDER BY revenue DESC
      LIMIT 20
    """

        status_sql = f"""
      SELECT
        COALESCE(status, 'unknown') as status,
        COUNT(*) as count,
        COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as revenue
      FROM {fully_qualified_table}
      WHERE DATE({date_column}) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
      GROUP BY status
      ORDER BY count DESC
    """

        interval_sql = f"""
      SELECT
        COALESCE(subscription_interval, 'unknown') as sub_interval,
        COUNT(*) as count,
        COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as revenue
      FROM {fully_qualified_table}
      WHERE DATE({date_column}) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
      GROUP BY subscription_interval
      ORDER BY revenue DESC
    """

        days_diff = (datetime.fromisoformat(date_to) - datetime.fromisoformat(date_from)).days
        group_by = "MONTH" if days_diff > 90 else "ISOWEEK" if days_diff > 31 else "DAY"
        trunc_expr = (
            f"DATE({date_column})"
            if group_by == "DAY"
            else f"DATE_TRUNC(DATE({date_column}), ISOWEEK)"
            if group_by == "ISOWEEK"
            else f"DATE_TRUNC(DATE({date_column}), MONTH)"
        )

        product_trend_sql = f"""
      SELECT
        {trunc_expr} as period_date,
        COALESCE(plan_name, 'Unknown') as plan_name,
        COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as revenue,
        COUNT(*) as count
      FROM {fully_qualified_table}
      WHERE DATE({date_column}) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
      GROUP BY period_date, plan_name
      ORDER BY period_date, revenue DESC
    """

        try:
            top_products_rows, status_rows, interval_rows, trend_rows = await asyncio.gather(
                self._query_all(top_products_sql),
                self._query_all(status_sql),
                self._query_all(interval_sql),
                self._query_all(product_trend_sql),
            )

            top_products = [
                {
                    "planName": str(row.get("plan_name") or "Unknown"),
                    "productId": str(row.get("product_id") or "N/A"),
                    "revenue": float(row.get("revenue") or 0),
                    "subscriptions": float(row.get("subscription_count") or 0),
                    "avgAmount": float(row.get("avg_amount") or 0),
                }
                for row in top_products_rows
            ]

            status_breakdown = [
                {
                    "status": str(row.get("status") or "unknown"),
                    "count": float(row.get("count") or 0),
                    "revenue": float(row.get("revenue") or 0),
                }
                for row in status_rows
            ]

            interval_breakdown = [
                {
                    "interval": str(row.get("sub_interval") or "unknown"),
                    "count": float(row.get("count") or 0),
                    "revenue": float(row.get("revenue") or 0),
                }
                for row in interval_rows
            ]

            product_trend = [
                {
                    "date": str(row.get("period_date")),
                    "planName": str(row.get("plan_name") or "Unknown"),
                    "revenue": float(row.get("revenue") or 0),
                    "count": float(row.get("count") or 0),
                }
                for row in trend_rows
            ]

            return {
                "topProducts": top_products,
                "statusBreakdown": status_breakdown,
                "intervalBreakdown": interval_breakdown,
                "productTrend": product_trend,
            }
        except Exception as error:
            raise RuntimeError(f"Product analytics failed: {error}") from error

    async def calculate_dashboard_kpis(
        self,
        dataset_id: str,
        date_from: str,
        date_to: str,
        date_column: str = "created",
        sales_table: str = "subscriptions",
        sales_column: str = "amount",
    ) -> dict:
        from datetime import datetime, timedelta

        target_dataset = dataset_id or self.dataset_id
        if not target_dataset:
            raise ValueError("Dataset ID is required for dashboard KPI calculation")

        fully_qualified_table = f"`{self.project_id}.{target_dataset}.{sales_table}`"

        days_diff = (datetime.fromisoformat(date_to) - datetime.fromisoformat(date_from)).days
        prev_to_date = datetime.fromisoformat(date_from) - timedelta(days=1)
        prev_from_date = prev_to_date - timedelta(days=days_diff)
        previous_from = prev_from_date.date().isoformat()
        previous_to = prev_to_date.date().isoformat()

        sql = f"""
      WITH
      -- Current period: total sales and count
      current_sales AS (
        SELECT COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as total_sales,
               COUNT(*) as sales_count
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
      ),
      prev_sales AS (
        SELECT COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as total_sales,
               COUNT(*) as sales_count
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) BETWEEN DATE('{previous_from}') AND DATE('{previous_to}')
      ),
      -- Active memberships: subscriptions created before end date that are not canceled (or canceled after end date)
      current_active AS (
        SELECT COUNT(*) as active_count
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) <= DATE('{date_to}')
          AND (canceled_at IS NULL OR DATE(canceled_at) > DATE('{date_to}'))
      ),
      prev_active AS (
        SELECT COUNT(*) as active_count
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) <= DATE('{previous_to}')
          AND (canceled_at IS NULL OR DATE(canceled_at) > DATE('{previous_to}'))
      ),
      -- Inactive (canceled) subscriptions as of end date
      current_inactive AS (
        SELECT COUNT(*) as inactive_count
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) <= DATE('{date_to}')
          AND canceled_at IS NOT NULL AND DATE(canceled_at) <= DATE('{date_to}')
      ),
      prev_inactive AS (
        SELECT COUNT(*) as inactive_count
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) <= DATE('{previous_to}')
          AND canceled_at IS NOT NULL AND DATE(canceled_at) <= DATE('{previous_to}')
      ),
      -- Net growth: new subs created in period minus cancellations in period
      current_growth AS (
        SELECT
          (SELECT COUNT(*) FROM {fully_qualified_table} WHERE DATE({date_column}) BETWEEN DATE('{date_from}') AND DATE('{date_to}')) as new_subs,
          (SELECT COUNT(*) FROM {fully_qualified_table} WHERE canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('{date_from}') AND DATE('{date_to}')) as canceled_subs
      ),
      prev_growth AS (
        SELECT
          (SELECT COUNT(*) FROM {fully_qualified_table} WHERE DATE({date_column}) BETWEEN DATE('{previous_from}') AND DATE('{previous_to}')) as new_subs,
          (SELECT COUNT(*) FROM {fully_qualified_table} WHERE canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('{previous_from}') AND DATE('{previous_to}')) as canceled_subs
      ),
      -- Monthly Recurring Revenue: sum of amount for all active subscriptions
      current_mrr AS (
        SELECT COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as mrr
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) <= DATE('{date_to}')
          AND (canceled_at IS NULL OR DATE(canceled_at) > DATE('{date_to}'))
      ),
      prev_mrr AS (
        SELECT COALESCE(SUM(CAST({sales_column} AS FLOAT64)), 0) as mrr
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) <= DATE('{previous_to}')
          AND (canceled_at IS NULL OR DATE(canceled_at) > DATE('{previous_to}'))
      )
      SELECT
        cs.total_sales as current_total_sales,
        cs.sales_count as current_sales_count,
        ps.total_sales as prev_total_sales,
        ps.sales_count as prev_sales_count,
        ca.active_count as current_active,
        pa.active_count as prev_active,
        ci.inactive_count as current_inactive,
        pi.inactive_count as prev_inactive,
        cg.new_subs as current_new,
        cg.canceled_subs as current_canceled,
        pg.new_subs as prev_new,
        pg.canceled_subs as prev_canceled,
        cm.mrr as current_mrr,
        pm.mrr as prev_mrr
      FROM current_sales cs
      CROSS JOIN prev_sales ps
      CROSS JOIN current_active ca
      CROSS JOIN prev_active pa
      CROSS JOIN current_inactive ci
      CROSS JOIN prev_inactive pi
      CROSS JOIN current_growth cg
      CROSS JOIN prev_growth pg
      CROSS JOIN current_mrr cm
      CROSS JOIN prev_mrr pm
    """

        try:
            result = await self.execute_query(sql, max_rows=1)
            row = result.rows[0] if result.rows else {}

            current_total_sales = float(row.get("current_total_sales") or 0)
            current_sales_count = float(row.get("current_sales_count") or 0)
            prev_total_sales = float(row.get("prev_total_sales") or 0)
            prev_sales_count = float(row.get("prev_sales_count") or 0)

            current_avg_purchase = current_total_sales / current_sales_count if current_sales_count > 0 else 0
            prev_avg_purchase = prev_total_sales / prev_sales_count if prev_sales_count > 0 else 0

            current_active = float(row.get("current_active") or 0)
            prev_active = float(row.get("prev_active") or 0)

            current_inactive = float(row.get("current_inactive") or 0)
            prev_inactive = float(row.get("prev_inactive") or 0)

            current_new = float(row.get("current_new") or 0)
            current_canceled = float(row.get("current_canceled") or 0)
            prev_new = float(row.get("prev_new") or 0)
            prev_canceled = float(row.get("prev_canceled") or 0)

            current_net_growth = current_new - current_canceled
            prev_net_growth = prev_new - prev_canceled

            current_total = current_active + current_inactive
            prev_total = prev_active + prev_inactive
            current_inactive_percent = (
                round(current_inactive * 10000 / current_total) / 100 if current_total > 0 else 0
            )
            prev_inactive_percent = round(prev_inactive * 10000 / prev_total) / 100 if prev_total > 0 else 0

            current_mrr = float(row.get("current_mrr") or 0)
            prev_mrr = float(row.get("prev_mrr") or 0)

            def calc_change(curr: float, prev: float) -> float:
                if prev == 0:
                    return 100 if curr > 0 else -100 if curr < 0 else 0
                return ((curr - prev) / abs(prev)) * 100

            return {
                "totalSales": current_total_sales,
                "activeMemberships": current_active,
                "netMonthlyGrowth": current_net_growth,
                "inactivePercent": current_inactive_percent,
                "monthlyRecurringRevenue": current_mrr,
                "averagePurchaseAmount": current_avg_purchase,
                "changes": {
                    "totalSales": calc_change(current_total_sales, prev_total_sales),
                    "activeMemberships": calc_change(current_active, prev_active),
                    "netMonthlyGrowth": calc_change(current_net_growth, prev_net_growth),
                    "inactivePercent": calc_change(current_inactive_percent, prev_inactive_percent),
                    "monthlyRecurringRevenue": calc_change(current_mrr, prev_mrr),
                    "averagePurchaseAmount": calc_change(current_avg_purchase, prev_avg_purchase),
                },
            }
        except Exception as error:
            raise RuntimeError(f"Dashboard KPI calculation failed: {error}") from error

    async def calculate_churn_analytics(
        self,
        dataset_id: str,
        date_from: str,
        date_to: str,
        date_column: str = "created",
        sales_table: str = "subscriptions",
        sales_column: str = "amount",
    ) -> dict:
        from datetime import datetime, timedelta

        target_dataset = dataset_id or self.dataset_id
        if not target_dataset:
            raise ValueError("Dataset ID is required for churn analytics")

        fully_qualified_table = f"`{self.project_id}.{target_dataset}.{sales_table}`"

        days_diff = (datetime.fromisoformat(date_to) - datetime.fromisoformat(date_from)).days
        previous_from = (datetime.fromisoformat(date_from) - timedelta(days=days_diff)).date().isoformat()
        previous_to = date_from

        summary_sql = f"""
      WITH active_at_start AS (
        SELECT *
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) < DATE('{date_from}')
          AND (canceled_at IS NULL OR DATE(canceled_at) >= DATE('{date_from}'))
      )
      SELECT
        COUNT(*) as total,
        COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('{date_from}') AND DATE('{date_to}')) as canceled,
        COALESCE(SUM(CASE WHEN canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('{date_from}') AND DATE('{date_to}') THEN CAST({sales_column} AS FLOAT64) ELSE 0 END), 0) as canceled_revenue
      FROM active_at_start
    """

        monthly_trend_sql = f"""
      WITH date_range AS (
        SELECT
          DATE_TRUNC(d, MONTH) as month_start,
          DATE_ADD(DATE_TRUNC(d, MONTH), INTERVAL 1 MONTH) as month_end
        FROM UNNEST(
          GENERATE_DATE_ARRAY(
            DATE_TRUNC(DATE('{date_from}'), MONTH),
            DATE('{date_to}'),
            INTERVAL 1 MONTH
          )
        ) as d
      ),
      monthly AS (
        SELECT
          dr.month_start,
          (SELECT COUNT(*) FROM {fully_qualified_table}
           WHERE DATE({date_column}) < dr.month_start
             AND (canceled_at IS NULL OR DATE(canceled_at) >= dr.month_start)
          ) as active_at_start,
          (SELECT COUNT(*) FROM {fully_qualified_table}
           WHERE DATE({date_column}) < dr.month_start
             AND (canceled_at IS NULL OR DATE(canceled_at) >= dr.month_start)
             AND canceled_at IS NOT NULL
             AND DATE(canceled_at) >= dr.month_start
             AND DATE(canceled_at) < dr.month_end
          ) as canceled_during
        FROM date_range dr
      )
      SELECT
        month_start,
        active_at_start as total_in_month,
        canceled_during as canceled_in_month,
        CASE WHEN active_at_start > 0 THEN ROUND(canceled_during * 100.0 / active_at_start, 2) ELSE 0 END as churn_rate
      FROM monthly
      WHERE active_at_start > 0
      ORDER BY month_start
    """

        churn_by_product_sql = f"""
      WITH active_at_start AS (
        SELECT *
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) < DATE('{date_from}')
          AND (canceled_at IS NULL OR DATE(canceled_at) >= DATE('{date_from}'))
      )
      SELECT
        COALESCE(plan_name, 'Unknown') as plan_name,
        COALESCE(product_id, 'N/A') as product_id,
        COUNT(*) as total,
        COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('{date_from}') AND DATE('{date_to}')) as canceled,
        CASE WHEN COUNT(*) > 0 THEN ROUND(
          COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('{date_from}') AND DATE('{date_to}')) * 100.0 / COUNT(*), 2
        ) ELSE 0 END as churn_rate,
        COALESCE(SUM(CASE WHEN canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
          THEN CAST({sales_column} AS FLOAT64) ELSE 0 END), 0) as canceled_revenue
      FROM active_at_start
      GROUP BY plan_name, product_id
      ORDER BY canceled DESC
    """

        previous_period_sql = f"""
      WITH active_at_start AS (
        SELECT *
        FROM {fully_qualified_table}
        WHERE DATE({date_column}) < DATE('{previous_from}')
          AND (canceled_at IS NULL OR DATE(canceled_at) >= DATE('{previous_from}'))
      )
      SELECT
        COUNT(*) as total,
        COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('{previous_from}') AND DATE('{previous_to}')) as canceled
      FROM active_at_start
    """

        try:
            summary_rows, monthly_rows, product_rows, previous_rows = await asyncio.gather(
                self._query_all(summary_sql),
                self._query_all(monthly_trend_sql),
                self._query_all(churn_by_product_sql),
                self._query_all(previous_period_sql),
            )

            summary_row = summary_rows[0] if summary_rows else {}
            total_start = float(summary_row.get("total") or 0)
            total_canceled = float(summary_row.get("canceled") or 0)
            canceled_revenue = float(summary_row.get("canceled_revenue") or 0)
            churn_rate = round(total_canceled * 10000 / total_start) / 100 if total_start > 0 else 0

            month_names = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
            monthly_trend = []
            for row in monthly_rows:
                raw = str(row.get("month_start"))
                parts = raw.split("-")
                year = parts[0] if parts else raw
                month_idx = int(parts[1]) - 1 if len(parts) > 1 else 0
                label = f"{month_names[month_idx]} {year}"
                short_label = f"{month_names[month_idx]} {year[-2:]}"
                safe_date_str = f"{year}-{parts[1] if len(parts) > 1 else '01'}-15"
                monthly_trend.append(
                    {
                        "month": safe_date_str,
                        "monthLabel": label,
                        "monthShortLabel": short_label,
                        "activeStart": float(row.get("total_in_month") or 0),
                        "canceled": float(row.get("canceled_in_month") or 0),
                        "churnRate": float(row.get("churn_rate") or 0),
                    }
                )

            churn_by_product = [
                {
                    "planName": str(row.get("plan_name") or "Unknown"),
                    "productId": str(row.get("product_id") or "N/A"),
                    "total": float(row.get("total") or 0),
                    "canceled": float(row.get("canceled") or 0),
                    "churnRate": float(row.get("churn_rate") or 0),
                    "canceledRevenue": float(row.get("canceled_revenue") or 0),
                }
                for row in product_rows
            ]

            prev_row = previous_rows[0] if previous_rows else {}
            prev_total = float(prev_row.get("total") or 0)
            prev_canceled = float(prev_row.get("canceled") or 0)
            previous_rate = round(prev_canceled * 10000 / prev_total) / 100 if prev_total > 0 else 0

            return {
                "summary": {
                    "totalStart": total_start,
                    "totalCanceled": total_canceled,
                    "churnRate": churn_rate,
                    "canceledRevenue": canceled_revenue,
                },
                "monthlyTrend": monthly_trend,
                "churnByProduct": churn_by_product,
                "periodComparison": {
                    "currentRate": churn_rate,
                    "previousRate": previous_rate,
                    "change": round((churn_rate - previous_rate) * 100) / 100,
                },
            }
        except Exception as error:
            raise RuntimeError(f"Churn analytics failed: {error}") from error

    # ------------------------------------------------------------------
    # Schema -> prompt text formatting (used by AI prompt building elsewhere)
    # ------------------------------------------------------------------

    def format_schema_for_prompt(self, schemas: list[SchemaColumn], project_id: str | None = None) -> str:
        table_map: dict[str, list[SchemaColumn]] = {}

        for col in schemas:
            key = f"{col.dataset_name}.{col.table_name}"
            table_map.setdefault(key, []).append(col)

        prompt = "Available BigQuery tables:\n\n"

        for table_name, columns in table_map.items():
            fully_qualified_name = f"{project_id}.{table_name}" if project_id else table_name
            prompt += f"Table: {fully_qualified_name}\n"
            prompt += f"  Full reference: `{fully_qualified_name}`\n"
            prompt += "Columns:\n"
            for col in columns:
                nullable_str = "nullable" if col.is_nullable else "required"
                desc_str = f" - {col.description}" if col.description else ""
                prompt += f"  - {col.column_name} ({col.data_type}, {nullable_str}){desc_str}\n"
            prompt += "\n"

        return prompt
