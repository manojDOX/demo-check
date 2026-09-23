"""Dashboard/Analytics KPIs computed from the curated marketing_analytics_ss views.

Replaces BigQueryService.calculate_* , which queried a raw `{dataset}.subscriptions` table that
doesn't exist in this deployment — every call failed and the dashboard rendered "--" for each tile.
The period arithmetic and every returned key are ported unchanged, so the frontend contracts in
client/src/pages/dashboard.tsx and analytics.tsx keep working with no frontend change.

Two deliberate semantic changes: plan labels use the human `tier_name` rather than the raw Stripe
product id the old `plan_name` held, and monthly recurring revenue uses `current_mrr` (a yearly plan
counts as its monthly equivalent) rather than summing raw subscription amounts.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta

from app.modules.connections.bigquery_service import BigQueryService

MARKETING_DATASET = "marketing_analytics_ss"
SUBSCRIPTION_VIEW = "subscription_360_vw"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# One row per subscription, except where a single Stripe subscription is linked to two customer
# records (verified live: 2 of 21,706). Those copies differ only in customer columns, so keeping the
# most recently created customer row leaves money/date fields untouched while stopping the amount
# from being counted twice. `SELECT DISTINCT *` would NOT collapse them.
_SUBS_COLUMNS = (
    "subscription_id",
    "client_id",
    "subscription_created_at",
    "canceled_at",
    "subscription_amount",
    "current_mrr",
    "subscription_status",
    "subscription_interval",
    "tier_name",
    "product_id",
)

_MONTH_NAMES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _check_date(value, field: str) -> str:
    """Dates are interpolated into SQL, so reject anything that isn't a plain calendar date."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError(f"{field} must be a YYYY-MM-DD date")
    date.fromisoformat(value)
    return value


def _subs_cte(project_id: str) -> str:
    columns = ", ".join(_SUBS_COLUMNS)
    return (
        "subs AS (\n"
        f"    SELECT {columns}\n"
        "    FROM (\n"
        f"      SELECT {columns},\n"
        "             ROW_NUMBER() OVER (PARTITION BY subscription_id "
        "ORDER BY customer_created_date DESC) AS rn\n"
        f"      FROM `{project_id}.{MARKETING_DATASET}.{SUBSCRIPTION_VIEW}`\n"
        "    )\n"
        "    WHERE rn = 1\n"
        "  )"
    )


def _previous_period(date_from: str, date_to: str) -> tuple[str, str]:
    """The equally long window ending the day before `date_from` (as the old code computed it)."""
    start = date.fromisoformat(date_from)
    span = (date.fromisoformat(date_to) - start).days
    previous_end = start - timedelta(days=1)
    return (previous_end - timedelta(days=span)).isoformat(), previous_end.isoformat()


def _bucket_expr(date_from: str, date_to: str, column: str) -> str:
    """Day / ISO week / month buckets by range length — same thresholds as the old trends code."""
    span = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days
    if span > 90:
        return f"DATE_TRUNC(DATE({column}), MONTH)"
    if span > 31:
        return f"DATE_TRUNC(DATE({column}), ISOWEEK)"
    return f"DATE({column})"


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _change(current: float, previous: float) -> float:
    if previous == 0:
        return 100 if current > 0 else -100 if current < 0 else 0
    return ((current - previous) / abs(previous)) * 100


async def _rows(bq: BigQueryService, sql: str, max_rows: int = 2000) -> list[dict]:
    result = await bq.execute_query(sql, max_rows=max_rows)
    return result.rows


# ---------------------------------------------------------------------------
# POST /api/kpis/dashboard
# ---------------------------------------------------------------------------


async def dashboard_kpis(bq: BigQueryService, date_from: str, date_to: str) -> dict:
    _check_date(date_from, "dateFrom")
    _check_date(date_to, "dateTo")
    previous_from, previous_to = _previous_period(date_from, date_to)

    def sales(alias: str, start: str, end: str) -> str:
        return (
            f"{alias} AS (\n"
            "    SELECT COALESCE(SUM(subscription_amount), 0) AS total_sales, COUNT(*) AS sales_count\n"
            f"    FROM subs WHERE DATE(subscription_created_at) BETWEEN DATE('{start}') AND DATE('{end}')\n"
            "  )"
        )

    def standing(alias: str, as_of: str) -> str:
        # Active/inactive/MRR as they stood at the end of a period. current_mrr is a present-day
        # column, so the previous-period MRR is an approximation — as it was before this change.
        return (
            f"{alias} AS (\n"
            "    SELECT\n"
            f"      COUNTIF(canceled_at IS NULL OR DATE(canceled_at) > DATE('{as_of}')) AS active_count,\n"
            f"      COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) <= DATE('{as_of}')) AS inactive_count,\n"
            "      COALESCE(SUM(IF(canceled_at IS NULL OR DATE(canceled_at) > DATE("
            f"'{as_of}'), current_mrr, 0)), 0) AS mrr\n"
            f"    FROM subs WHERE DATE(subscription_created_at) <= DATE('{as_of}')\n"
            "  )"
        )

    def growth(alias: str, start: str, end: str) -> str:
        return (
            f"{alias} AS (\n"
            "    SELECT\n"
            f"      COUNTIF(DATE(subscription_created_at) BETWEEN DATE('{start}') AND DATE('{end}')) AS new_subs,\n"
            "      COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE("
            f"'{start}') AND DATE('{end}')) AS canceled_subs\n"
            "    FROM subs\n"
            "  )"
        )

    sql = f"""WITH {_subs_cte(bq.project_id)},
  {sales('current_sales', date_from, date_to)},
  {sales('prev_sales', previous_from, previous_to)},
  {standing('current_standing', date_to)},
  {standing('prev_standing', previous_to)},
  {growth('current_growth', date_from, date_to)},
  {growth('prev_growth', previous_from, previous_to)}
SELECT
  cs.total_sales AS current_total_sales,
  cs.sales_count AS current_sales_count,
  ps.total_sales AS prev_total_sales,
  ps.sales_count AS prev_sales_count,
  cst.active_count AS current_active,
  cst.inactive_count AS current_inactive,
  cst.mrr AS current_mrr,
  pst.active_count AS prev_active,
  pst.inactive_count AS prev_inactive,
  pst.mrr AS prev_mrr,
  cg.new_subs AS current_new,
  cg.canceled_subs AS current_canceled,
  pg.new_subs AS prev_new,
  pg.canceled_subs AS prev_canceled
FROM current_sales cs
CROSS JOIN prev_sales ps
CROSS JOIN current_standing cst
CROSS JOIN prev_standing pst
CROSS JOIN current_growth cg
CROSS JOIN prev_growth pg"""

    rows = await _rows(bq, sql, max_rows=1)
    row = rows[0] if rows else {}

    current_total_sales = _num(row.get("current_total_sales"))
    current_sales_count = _num(row.get("current_sales_count"))
    prev_total_sales = _num(row.get("prev_total_sales"))
    prev_sales_count = _num(row.get("prev_sales_count"))
    current_avg_purchase = current_total_sales / current_sales_count if current_sales_count > 0 else 0
    prev_avg_purchase = prev_total_sales / prev_sales_count if prev_sales_count > 0 else 0

    current_active = _num(row.get("current_active"))
    prev_active = _num(row.get("prev_active"))
    current_inactive = _num(row.get("current_inactive"))
    prev_inactive = _num(row.get("prev_inactive"))

    current_net_growth = _num(row.get("current_new")) - _num(row.get("current_canceled"))
    prev_net_growth = _num(row.get("prev_new")) - _num(row.get("prev_canceled"))

    current_total = current_active + current_inactive
    prev_total = prev_active + prev_inactive
    current_inactive_percent = round(current_inactive * 10000 / current_total) / 100 if current_total > 0 else 0
    prev_inactive_percent = round(prev_inactive * 10000 / prev_total) / 100 if prev_total > 0 else 0

    current_mrr = _num(row.get("current_mrr"))
    prev_mrr = _num(row.get("prev_mrr"))

    return {
        "totalSales": current_total_sales,
        "activeMemberships": current_active,
        "netMonthlyGrowth": current_net_growth,
        "inactivePercent": current_inactive_percent,
        "monthlyRecurringRevenue": current_mrr,
        "averagePurchaseAmount": current_avg_purchase,
        "changes": {
            "totalSales": _change(current_total_sales, prev_total_sales),
            "activeMemberships": _change(current_active, prev_active),
            "netMonthlyGrowth": _change(current_net_growth, prev_net_growth),
            "inactivePercent": _change(current_inactive_percent, prev_inactive_percent),
            "monthlyRecurringRevenue": _change(current_mrr, prev_mrr),
            "averagePurchaseAmount": _change(current_avg_purchase, prev_avg_purchase),
        },
    }


# ---------------------------------------------------------------------------
# POST /api/kpis/calculate
# ---------------------------------------------------------------------------


async def period_kpis(bq: BigQueryService, date_from: str, date_to: str) -> dict:
    _check_date(date_from, "dateFrom")
    _check_date(date_to, "dateTo")
    previous_from, previous_to = _previous_period(date_from, date_to)

    def period(alias: str, start: str, end: str) -> str:
        return (
            f"{alias} AS (\n"
            "    SELECT\n"
            "      COALESCE(SUM(subscription_amount), 0) AS total_sales,\n"
            "      COUNT(*) AS order_count,\n"
            "      COALESCE(AVG(subscription_amount), 0) AS avg_order_value,\n"
            "      COUNT(DISTINCT client_id) AS unique_customers,\n"
            "      COUNT(DISTINCT IF(client_id IN (SELECT client_id FROM subs WHERE DATE("
            f"subscription_created_at) < DATE('{start}')), client_id, NULL)) AS returning_customers\n"
            f"    FROM subs WHERE DATE(subscription_created_at) BETWEEN DATE('{start}') AND DATE('{end}')\n"
            "  )"
        )

    def ltv(alias: str, start: str, end: str) -> str:
        # Average lifetime spend of the customers active in the window (all of their subscriptions).
        return (
            f"{alias} AS (\n"
            "    SELECT COALESCE(AVG(customer_total), 0) AS avg_ltv FROM (\n"
            "      SELECT client_id, SUM(subscription_amount) AS customer_total FROM subs\n"
            "      WHERE client_id IN (SELECT client_id FROM subs WHERE DATE(subscription_created_at) "
            f"BETWEEN DATE('{start}') AND DATE('{end}'))\n"
            "      GROUP BY client_id\n"
            "    )\n"
            "  )"
        )

    sql = f"""WITH {_subs_cte(bq.project_id)},
  {period('current_period', date_from, date_to)},
  {period('previous_period', previous_from, previous_to)},
  {ltv('ltv_current', date_from, date_to)},
  {ltv('ltv_prev', previous_from, previous_to)}
SELECT
  cp.total_sales AS current_total_sales,
  cp.order_count AS current_order_count,
  cp.avg_order_value AS current_avg_order_value,
  cp.unique_customers AS current_unique_customers,
  cp.returning_customers AS current_returning_customers,
  lc.avg_ltv AS current_ltv,
  pp.total_sales AS prev_total_sales,
  pp.order_count AS prev_order_count,
  pp.avg_order_value AS prev_avg_order_value,
  pp.unique_customers AS prev_unique_customers,
  pp.returning_customers AS prev_returning_customers,
  lp.avg_ltv AS prev_ltv
FROM current_period cp
CROSS JOIN previous_period pp
CROSS JOIN ltv_current lc
CROSS JOIN ltv_prev lp"""

    rows = await _rows(bq, sql, max_rows=1)
    row = rows[0] if rows else {}

    current_returning = _num(row.get("current_returning_customers"))
    current_unique = _num(row.get("current_unique_customers"))
    current_recurrence = (current_returning / current_unique) * 100 if current_unique > 0 else 0

    prev_returning = _num(row.get("prev_returning_customers"))
    prev_unique = _num(row.get("prev_unique_customers"))
    prev_recurrence = (prev_returning / prev_unique) * 100 if prev_unique > 0 else 0

    return {
        "totalSales": _num(row.get("current_total_sales")),
        "orderCount": _num(row.get("current_order_count")),
        "averageOrderValue": _num(row.get("current_avg_order_value")),
        "newCustomers": max(0, current_unique - current_returning),
        "recurringCustomers": current_returning,
        "recurrenceRate": current_recurrence,
        "customerLtv": _num(row.get("current_ltv")),
        "previousPeriod": {
            "totalSales": _num(row.get("prev_total_sales")),
            "orderCount": _num(row.get("prev_order_count")),
            "averageOrderValue": _num(row.get("prev_avg_order_value")),
            "newCustomers": max(0, prev_unique - prev_returning),
            "recurringCustomers": prev_returning,
            "recurrenceRate": prev_recurrence,
            "customerLtv": _num(row.get("prev_ltv")),
        },
    }


# ---------------------------------------------------------------------------
# POST /api/kpis/trends
# ---------------------------------------------------------------------------


async def trends(bq: BigQueryService, date_from: str, date_to: str) -> dict:
    _check_date(date_from, "dateFrom")
    _check_date(date_to, "dateTo")
    bucket = _bucket_expr(date_from, date_to, "subscription_created_at")
    subs = _subs_cte(bq.project_id)

    sales_sql = f"""WITH {subs}
SELECT
  {bucket} AS period_date,
  COALESCE(SUM(subscription_amount), 0) AS total_sales,
  COUNT(*) AS order_count
FROM subs
WHERE DATE(subscription_created_at) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
GROUP BY period_date
ORDER BY period_date"""

    customer_sql = f"""WITH {subs},
  first_subscription AS (
    SELECT client_id, MIN(DATE(subscription_created_at)) AS first_date FROM subs GROUP BY client_id
  )
SELECT
  {bucket} AS period_date,
  COUNT(DISTINCT IF(fs.first_date >= DATE('{date_from}'), s.client_id, NULL)) AS new_customers,
  COUNT(DISTINCT IF(fs.first_date < DATE('{date_from}'), s.client_id, NULL)) AS returning_customers
FROM subs s
JOIN first_subscription fs USING (client_id)
WHERE DATE(s.subscription_created_at) BETWEEN DATE('{date_from}') AND DATE('{date_to}')
GROUP BY period_date
ORDER BY period_date"""

    sales_rows, customer_rows = await asyncio.gather(_rows(bq, sales_sql), _rows(bq, customer_sql))

    return {
        "salesTrend": [
            {
                "date": str(row.get("period_date")),
                "sales": _num(row.get("total_sales")),
                "orders": _num(row.get("order_count")),
            }
            for row in sales_rows
        ],
        "customerTrend": [
            {
                "date": str(row.get("period_date")),
                "newCustomers": _num(row.get("new_customers")),
                "returningCustomers": _num(row.get("returning_customers")),
            }
            for row in customer_rows
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/kpis/product-analytics
# ---------------------------------------------------------------------------


async def product_analytics(bq: BigQueryService, date_from: str, date_to: str) -> dict:
    _check_date(date_from, "dateFrom")
    _check_date(date_to, "dateTo")
    bucket = _bucket_expr(date_from, date_to, "subscription_created_at")
    subs = _subs_cte(bq.project_id)
    in_period = (
        f"WHERE DATE(subscription_created_at) BETWEEN DATE('{date_from}') AND DATE('{date_to}')"
    )

    top_products_sql = f"""WITH {subs}
SELECT
  COALESCE(tier_name, 'Unknown') AS plan_name,
  COALESCE(product_id, 'N/A') AS product_id,
  COALESCE(SUM(subscription_amount), 0) AS revenue,
  COUNT(*) AS subscription_count,
  COALESCE(AVG(subscription_amount), 0) AS avg_amount
FROM subs
{in_period}
GROUP BY plan_name, product_id
ORDER BY revenue DESC
LIMIT 20"""

    status_sql = f"""WITH {subs}
SELECT
  COALESCE(subscription_status, 'unknown') AS status,
  COUNT(*) AS count,
  COALESCE(SUM(subscription_amount), 0) AS revenue
FROM subs
{in_period}
GROUP BY status
ORDER BY count DESC"""

    interval_sql = f"""WITH {subs}
SELECT
  COALESCE(subscription_interval, 'unknown') AS sub_interval,
  COUNT(*) AS count,
  COALESCE(SUM(subscription_amount), 0) AS revenue
FROM subs
{in_period}
GROUP BY sub_interval
ORDER BY revenue DESC"""

    product_trend_sql = f"""WITH {subs}
SELECT
  {bucket} AS period_date,
  COALESCE(tier_name, 'Unknown') AS plan_name,
  COALESCE(SUM(subscription_amount), 0) AS revenue,
  COUNT(*) AS count
FROM subs
{in_period}
GROUP BY period_date, plan_name
ORDER BY period_date, revenue DESC"""

    top_rows, status_rows, interval_rows, trend_rows = await asyncio.gather(
        _rows(bq, top_products_sql),
        _rows(bq, status_sql),
        _rows(bq, interval_sql),
        _rows(bq, product_trend_sql),
    )

    return {
        "topProducts": [
            {
                "planName": str(row.get("plan_name") or "Unknown"),
                "productId": str(row.get("product_id") or "N/A"),
                "revenue": _num(row.get("revenue")),
                "subscriptions": _num(row.get("subscription_count")),
                "avgAmount": _num(row.get("avg_amount")),
            }
            for row in top_rows
        ],
        "statusBreakdown": [
            {
                "status": str(row.get("status") or "unknown"),
                "count": _num(row.get("count")),
                "revenue": _num(row.get("revenue")),
            }
            for row in status_rows
        ],
        "intervalBreakdown": [
            {
                "interval": str(row.get("sub_interval") or "unknown"),
                "count": _num(row.get("count")),
                "revenue": _num(row.get("revenue")),
            }
            for row in interval_rows
        ],
        "productTrend": [
            {
                "date": str(row.get("period_date")),
                "planName": str(row.get("plan_name") or "Unknown"),
                "revenue": _num(row.get("revenue")),
                "count": _num(row.get("count")),
            }
            for row in trend_rows
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/kpis/churn-analytics
# ---------------------------------------------------------------------------


async def churn_analytics(bq: BigQueryService, date_from: str, date_to: str) -> dict:
    _check_date(date_from, "dateFrom")
    _check_date(date_to, "dateTo")
    span = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days
    previous_from = (date.fromisoformat(date_from) - timedelta(days=span)).isoformat()
    previous_to = date_from
    subs = _subs_cte(bq.project_id)

    def cohort(start: str) -> str:
        """Subscriptions that were live entering `start` — the denominator for churn."""
        return (
            "  active_at_start AS (\n"
            "    SELECT * FROM subs\n"
            f"    WHERE DATE(subscription_created_at) < DATE('{start}')\n"
            f"      AND (canceled_at IS NULL OR DATE(canceled_at) >= DATE('{start}'))\n"
            "  )"
        )

    def canceled_in(start: str, end: str) -> str:
        return f"canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('{start}') AND DATE('{end}')"

    summary_sql = f"""WITH {subs},
{cohort(date_from)}
SELECT
  COUNT(*) AS total,
  COUNTIF({canceled_in(date_from, date_to)}) AS canceled,
  COALESCE(SUM(IF({canceled_in(date_from, date_to)}, subscription_amount, 0)), 0) AS canceled_revenue
FROM active_at_start"""

    # CROSS JOIN over a month spine instead of correlated subqueries: same numbers, one pass.
    monthly_trend_sql = f"""WITH {subs},
  months AS (
    SELECT month_start, DATE_ADD(month_start, INTERVAL 1 MONTH) AS month_end
    FROM UNNEST(GENERATE_DATE_ARRAY(
      DATE_TRUNC(DATE('{date_from}'), MONTH), DATE('{date_to}'), INTERVAL 1 MONTH
    )) AS month_start
  ),
  monthly AS (
    SELECT
      m.month_start,
      COUNTIF(DATE(s.subscription_created_at) < m.month_start
              AND (s.canceled_at IS NULL OR DATE(s.canceled_at) >= m.month_start)) AS active_at_start,
      COUNTIF(DATE(s.subscription_created_at) < m.month_start
              AND s.canceled_at IS NOT NULL
              AND DATE(s.canceled_at) >= m.month_start
              AND DATE(s.canceled_at) < m.month_end) AS canceled_during
    FROM months m
    CROSS JOIN subs s
    GROUP BY m.month_start
  )
SELECT
  month_start,
  active_at_start AS total_in_month,
  canceled_during AS canceled_in_month,
  IF(active_at_start > 0, ROUND(canceled_during * 100.0 / active_at_start, 2), 0) AS churn_rate
FROM monthly
WHERE active_at_start > 0
ORDER BY month_start"""

    by_product_sql = f"""WITH {subs},
{cohort(date_from)}
SELECT
  COALESCE(tier_name, 'Unknown') AS plan_name,
  COALESCE(product_id, 'N/A') AS product_id,
  COUNT(*) AS total,
  COUNTIF({canceled_in(date_from, date_to)}) AS canceled,
  IF(COUNT(*) > 0, ROUND(COUNTIF({canceled_in(date_from, date_to)}) * 100.0 / COUNT(*), 2), 0) AS churn_rate,
  COALESCE(SUM(IF({canceled_in(date_from, date_to)}, subscription_amount, 0)), 0) AS canceled_revenue
FROM active_at_start
GROUP BY plan_name, product_id
ORDER BY canceled DESC"""

    previous_sql = f"""WITH {subs},
{cohort(previous_from)}
SELECT
  COUNT(*) AS total,
  COUNTIF({canceled_in(previous_from, previous_to)}) AS canceled
FROM active_at_start"""

    summary_rows, monthly_rows, product_rows, previous_rows = await asyncio.gather(
        _rows(bq, summary_sql, max_rows=1),
        _rows(bq, monthly_trend_sql),
        _rows(bq, by_product_sql),
        _rows(bq, previous_sql, max_rows=1),
    )

    summary_row = summary_rows[0] if summary_rows else {}
    total_start = _num(summary_row.get("total"))
    total_canceled = _num(summary_row.get("canceled"))
    churn_rate = round(total_canceled * 10000 / total_start) / 100 if total_start > 0 else 0

    monthly_trend = []
    for row in monthly_rows:
        month_start = str(row.get("month_start"))
        parts = month_start.split("-")
        year = parts[0]
        month_index = int(parts[1]) - 1 if len(parts) > 1 else 0
        month_number = parts[1] if len(parts) > 1 else "01"
        monthly_trend.append(
            {
                "month": f"{year}-{month_number}-15",
                "monthLabel": f"{_MONTH_NAMES_ES[month_index]} {year}",
                "monthShortLabel": f"{_MONTH_NAMES_ES[month_index]} {year[-2:]}",
                "activeStart": _num(row.get("total_in_month")),
                "canceled": _num(row.get("canceled_in_month")),
                "churnRate": _num(row.get("churn_rate")),
            }
        )

    previous_row = previous_rows[0] if previous_rows else {}
    previous_total = _num(previous_row.get("total"))
    previous_canceled = _num(previous_row.get("canceled"))
    previous_rate = round(previous_canceled * 10000 / previous_total) / 100 if previous_total > 0 else 0

    return {
        "summary": {
            "totalStart": total_start,
            "totalCanceled": total_canceled,
            "churnRate": churn_rate,
            "canceledRevenue": _num(summary_row.get("canceled_revenue")),
        },
        "monthlyTrend": monthly_trend,
        "churnByProduct": [
            {
                "planName": str(row.get("plan_name") or "Unknown"),
                "productId": str(row.get("product_id") or "N/A"),
                "total": _num(row.get("total")),
                "canceled": _num(row.get("canceled")),
                "churnRate": _num(row.get("churn_rate")),
                "canceledRevenue": _num(row.get("canceled_revenue")),
            }
            for row in product_rows
        ],
        "periodComparison": {
            "currentRate": churn_rate,
            "previousRate": previous_rate,
            "change": round((churn_rate - previous_rate) * 100) / 100,
        },
    }
