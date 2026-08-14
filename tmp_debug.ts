import { BigQueryService } from "./server/services/bigquery";
import { db } from "./server/db";
import { bigqueryConnections } from "./shared/schema";
import { eq } from "drizzle-orm";

async function main() {
  const connections = await db.select().from(bigqueryConnections).where(eq(bigqueryConnections.id, 3));
  const conn = connections[0];
  if (!conn) { console.log("No connection found"); return; }
  const bq = BigQueryService.fromCredentialsJson(conn.projectId, conn.credentials, conn.datasetId || undefined);
  const table = `\`${conn.projectId}.${conn.datasetId}.subscriptions\``;

  // Run exact same monthly trend SQL that the app runs for dateFrom=2025-11-23, dateTo=2026-02-23
  const q = await bq.executeQuery(`
    WITH date_range AS (
      SELECT
        DATE_TRUNC(d, MONTH) as month_start,
        DATE_ADD(DATE_TRUNC(d, MONTH), INTERVAL 1 MONTH) as month_end
      FROM UNNEST(
        GENERATE_DATE_ARRAY(
          DATE_TRUNC(DATE('2025-11-23'), MONTH),
          DATE('2026-02-23'),
          INTERVAL 1 MONTH
        )
      ) as d
    ),
    monthly AS (
      SELECT
        dr.month_start,
        dr.month_end,
        (SELECT COUNT(*) FROM ${table}
         WHERE DATE(created) < dr.month_start
           AND (canceled_at IS NULL OR DATE(canceled_at) >= dr.month_start)
        ) as active_at_start,
        (SELECT COUNT(*) FROM ${table}
         WHERE DATE(created) < dr.month_start
           AND (canceled_at IS NULL OR DATE(canceled_at) >= dr.month_start)
           AND canceled_at IS NOT NULL
           AND DATE(canceled_at) >= dr.month_start
           AND DATE(canceled_at) < dr.month_end
        ) as canceled_during
      FROM date_range dr
    )
    SELECT
      month_start,
      month_end,
      active_at_start,
      canceled_during,
      CASE WHEN active_at_start > 0 THEN ROUND(canceled_during * 100.0 / active_at_start, 2) ELSE 0 END as churn_rate
    FROM monthly
    WHERE active_at_start > 0
    ORDER BY month_start
  `, { maxRows: 10 });
  console.log("=== Monthly Trend (same query as app) ===");
  for (const row of q.rows) {
    console.log(`${row.month_start} -> ${row.month_end}: ${row.active_at_start} active, ${row.canceled_during} canceled, ${row.churn_rate}% churn`);
  }

  process.exit(0);
}
main().catch(e => { console.error(e); process.exit(1); });
