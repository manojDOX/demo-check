import { BigQuery } from "@google-cloud/bigquery";

export interface BigQueryConfig {
  projectId: string;
  credentials: object;
  datasetId?: string;
}

export interface SchemaColumn {
  datasetName: string;
  tableName: string;
  columnName: string;
  dataType: string;
  isNullable: boolean;
  description?: string;
}

export interface QueryResult {
  rows: any[];
  totalRows: number;
  schema: { name: string; type: string }[];
  executionTimeMs: number;
}

export class BigQueryService {
  private client: BigQuery;
  private projectId: string;
  private datasetId?: string;

  constructor(config: BigQueryConfig) {
    // Trim whitespace from projectId and datasetId to prevent errors
    this.projectId = config.projectId?.trim() || "";
    this.datasetId = config.datasetId?.trim();
    
    if (!this.projectId) {
      throw new Error("ProjectId is required and cannot be empty");
    }
    
    this.client = new BigQuery({
      projectId: this.projectId,
      credentials: config.credentials,
    });
  }

  static fromCredentialsJson(projectId: string, credentialsJson: string, datasetId?: string): BigQueryService {
    try {
      const credentials = JSON.parse(credentialsJson);
      return new BigQueryService({ 
        projectId: projectId?.trim() || "", 
        credentials, 
        datasetId: datasetId?.trim() 
      });
    } catch (error) {
      throw new Error("Invalid service account JSON credentials");
    }
  }

  async testConnection(): Promise<{ success: boolean; message: string }> {
    try {
      const [datasets] = await this.client.getDatasets({ maxResults: 1 });
      return {
        success: true,
        message: `Connected successfully. Found ${datasets.length > 0 ? "datasets" : "no datasets"} in project.`,
      };
    } catch (error: any) {
      const message = error.message || "Unknown error";
      if (message.includes("Permission denied") || message.includes("403")) {
        return {
          success: false,
          message: "Permission denied. Ensure service account has BigQuery Data Viewer role.",
        };
      }
      if (message.includes("Invalid JWT") || message.includes("invalid_grant")) {
        return {
          success: false,
          message: "Invalid credentials. Check your service account JSON.",
        };
      }
      return { success: false, message };
    }
  }

  async discoverSchema(datasetId?: string): Promise<SchemaColumn[]> {
    const schemas: SchemaColumn[] = [];
    const targetDataset = datasetId || this.datasetId;

    try {
      if (targetDataset) {
        const dataset = this.client.dataset(targetDataset);
        const [tables] = await dataset.getTables();
        
        for (const table of tables) {
          const [metadata] = await table.getMetadata();
          const tableSchema = metadata.schema?.fields || [];
          
          for (const field of tableSchema) {
            schemas.push({
              datasetName: targetDataset,
              tableName: table.id || "",
              columnName: field.name || "",
              dataType: field.type || "STRING",
              isNullable: field.mode !== "REQUIRED",
              description: field.description,
            });
          }
        }
      } else {
        const [datasets] = await this.client.getDatasets();
        
        for (const dataset of datasets) {
          const datasetName = dataset.id || "";
          const [tables] = await dataset.getTables();
          
          for (const table of tables) {
            const [metadata] = await table.getMetadata();
            const tableSchema = metadata.schema?.fields || [];
            
            for (const field of tableSchema) {
              schemas.push({
                datasetName,
                tableName: table.id || "",
                columnName: field.name || "",
                dataType: field.type || "STRING",
                isNullable: field.mode !== "REQUIRED",
                description: field.description,
              });
            }
          }
        }
      }
    } catch (error: any) {
      console.error("Schema discovery error:", error.message);
      throw new Error(`Failed to discover schema: ${error.message}`);
    }

    return schemas;
  }

  private validateQuerySafety(sql: string): void {
    const normalizedSql = sql.replace(/\s+/g, " ").trim().toUpperCase();
    
    // Reject queries with semicolons (multi-statement prevention)
    if (sql.includes(";")) {
      throw new Error("Multi-statement queries are not allowed.");
    }
    
    // DDL/DML keywords that should never appear anywhere in the query
    const forbiddenKeywords = [
      "DROP", "DELETE", "TRUNCATE", "INSERT", "UPDATE", "CREATE", 
      "ALTER", "GRANT", "REVOKE", "MERGE", "CALL", "EXECUTE"
    ];
    
    // Check for forbidden keywords as standalone words anywhere in query
    for (const keyword of forbiddenKeywords) {
      const regex = new RegExp(`\\b${keyword}\\b`, "i");
      if (regex.test(normalizedSql)) {
        throw new Error(`Query contains forbidden keyword '${keyword}'. Only SELECT queries are permitted.`);
      }
    }
    
    // Verify query starts with SELECT or WITH (for CTEs)
    if (!normalizedSql.startsWith("SELECT") && !normalizedSql.startsWith("WITH")) {
      throw new Error("Query must start with SELECT or WITH. Only SELECT queries are permitted.");
    }
  }

  async executeQuery(sql: string, options?: { maxRows?: number; timeoutMs?: number }): Promise<QueryResult> {
    const maxRows = options?.maxRows || 2000;
    const timeoutMs = options?.timeoutMs || 30000;

    // Comprehensive SQL safety validation
    this.validateQuerySafety(sql);

    const startTime = Date.now();

    try {
      const [job] = await this.client.createQueryJob({
        query: sql,
        // Don't specify location - let BigQuery auto-detect from dataset
        maximumBytesBilled: "1000000000",
      });

      const [rows] = await job.getQueryResults({
        maxResults: maxRows,
        timeoutMs,
      });

      const [metadata] = await job.getMetadata();
      const schema = metadata.statistics?.query?.schema?.fields?.map((f: any) => ({
        name: f.name,
        type: f.type,
      })) || [];

      // For SELECT queries, use outputRows from query statistics (not numDmlAffectedRows)
      const queryStats = metadata.statistics?.query || {};
      const totalRows = parseInt(
        queryStats.outputRows || 
        metadata.statistics?.numChildJobs || 
        rows.length.toString(), 
        10
      );

      return {
        rows,
        totalRows,
        schema,
        executionTimeMs: Date.now() - startTime,
      };
    } catch (error: any) {
      throw new Error(`Query execution failed: ${error.message}`);
    }
  }

  // Discover schema via SQL query to INFORMATION_SCHEMA (more reliable than API)
  async discoverSchemaViaSql(datasetId?: string): Promise<SchemaColumn[]> {
    const targetDataset = datasetId || this.datasetId;

    // If a specific dataset is requested, query just that one
    if (targetDataset) {
      const schemas: SchemaColumn[] = [];
      try {
        const sql = `
          SELECT 
            table_catalog as project_id,
            table_schema as dataset_name,
            table_name,
            column_name,
            data_type,
            is_nullable
          FROM \`${this.projectId}.${targetDataset}.INFORMATION_SCHEMA.COLUMNS\`
          ORDER BY table_name, ordinal_position
        `;
        const result = await this.executeQuery(sql, { maxRows: 5000 });
        for (const row of result.rows) {
          schemas.push({
            datasetName: row.dataset_name || targetDataset,
            tableName: row.table_name,
            columnName: row.column_name,
            dataType: row.data_type,
            isNullable: row.is_nullable === 'YES',
            description: undefined,
          });
        }
        return schemas;
      } catch (error: any) {
        console.error("SQL schema discovery error:", error.message);
        throw new Error(`Failed to discover schema via SQL: ${error.message}`);
      }
    }

    // No specific dataset — iterate ALL datasets in the project
    const allSchemas: SchemaColumn[] = [];
    try {
      const [datasets] = await this.client.getDatasets();
      for (const dataset of datasets) {
        const dsId = dataset.id;
        if (!dsId) continue;
        try {
          const dsSchemas = await this.discoverSchemaViaSql(dsId);
          allSchemas.push(...dsSchemas);
        } catch (dsError: any) {
          console.log(`SQL schema discovery skipped for dataset "${dsId}": ${dsError.message}`);
        }
      }
    } catch (error: any) {
      console.error("Failed to list datasets for SQL schema discovery:", error.message);
      throw new Error(`Failed to discover schema via SQL: ${error.message}`);
    }
    return allSchemas;
  }

  async calculateKPIs(
    datasetId: string,
    dateFrom: string,
    dateTo: string,
    dateColumn: string = "created",
    salesTable: string = "subscriptions",
    salesColumn: string = "amount",
    customerIdColumn: string = "customer_id"
  ): Promise<{
    totalSales: number;
    orderCount: number;
    averageOrderValue: number;
    newCustomers: number;
    recurringCustomers: number;
    recurrenceRate: number;
    customerLtv: number;
    previousPeriod: {
      totalSales: number;
      orderCount: number;
      averageOrderValue: number;
      newCustomers: number;
      recurringCustomers: number;
      recurrenceRate: number;
      customerLtv: number;
    };
  }> {
    const targetDataset = datasetId || this.datasetId;
    if (!targetDataset) {
      throw new Error("Dataset ID is required for KPI calculation");
    }

    const fullyQualifiedTable = `\`${this.projectId}.${targetDataset}.${salesTable}\``;

    const sql = `
      WITH date_params AS (
        SELECT
          DATE('${dateFrom}') as current_start,
          DATE('${dateTo}') as current_end,
          DATE_DIFF(DATE('${dateTo}'), DATE('${dateFrom}'), DAY) as period_days
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
          COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as total_sales,
          COUNT(*) as order_count,
          COALESCE(AVG(CAST(${salesColumn} AS FLOAT64)), 0) as avg_order_value,
          COUNT(DISTINCT ${customerIdColumn}) as unique_customers
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) BETWEEN (SELECT current_start FROM previous_params) AND (SELECT current_end FROM previous_params)
      ),
      previous_period AS (
        SELECT
          COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as total_sales,
          COUNT(*) as order_count,
          COALESCE(AVG(CAST(${salesColumn} AS FLOAT64)), 0) as avg_order_value,
          COUNT(DISTINCT ${customerIdColumn}) as unique_customers
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) BETWEEN (SELECT prev_start FROM previous_params) AND (SELECT prev_end FROM previous_params)
      ),
      returning_customers_current AS (
        SELECT COUNT(DISTINCT c.${customerIdColumn}) as returning_count
        FROM ${fullyQualifiedTable} c
        WHERE DATE(c.${dateColumn}) BETWEEN (SELECT current_start FROM previous_params) AND (SELECT current_end FROM previous_params)
        AND c.${customerIdColumn} IN (
          SELECT DISTINCT ${customerIdColumn}
          FROM ${fullyQualifiedTable}
          WHERE DATE(${dateColumn}) < (SELECT current_start FROM previous_params)
        )
      ),
      returning_customers_prev AS (
        SELECT COUNT(DISTINCT c.${customerIdColumn}) as returning_count
        FROM ${fullyQualifiedTable} c
        WHERE DATE(c.${dateColumn}) BETWEEN (SELECT prev_start FROM previous_params) AND (SELECT prev_end FROM previous_params)
        AND c.${customerIdColumn} IN (
          SELECT DISTINCT ${customerIdColumn}
          FROM ${fullyQualifiedTable}
          WHERE DATE(${dateColumn}) < (SELECT prev_start FROM previous_params)
        )
      ),
      ltv_current AS (
        SELECT COALESCE(AVG(customer_total), 0) as avg_ltv
        FROM (
          SELECT ${customerIdColumn}, SUM(CAST(${salesColumn} AS FLOAT64)) as customer_total
          FROM ${fullyQualifiedTable}
          WHERE ${customerIdColumn} IN (
            SELECT DISTINCT ${customerIdColumn}
            FROM ${fullyQualifiedTable}
            WHERE DATE(${dateColumn}) BETWEEN (SELECT current_start FROM previous_params) AND (SELECT current_end FROM previous_params)
          )
          GROUP BY ${customerIdColumn}
        )
      ),
      ltv_prev AS (
        SELECT COALESCE(AVG(customer_total), 0) as avg_ltv
        FROM (
          SELECT ${customerIdColumn}, SUM(CAST(${salesColumn} AS FLOAT64)) as customer_total
          FROM ${fullyQualifiedTable}
          WHERE ${customerIdColumn} IN (
            SELECT DISTINCT ${customerIdColumn}
            FROM ${fullyQualifiedTable}
            WHERE DATE(${dateColumn}) BETWEEN (SELECT prev_start FROM previous_params) AND (SELECT prev_end FROM previous_params)
          )
          GROUP BY ${customerIdColumn}
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
    `;

    try {
      const result = await this.executeQuery(sql, { maxRows: 1 });
      const row = result.rows[0] || {};

      const currentReturning = Number(row.current_returning_customers) || 0;
      const currentUnique = Number(row.current_unique_customers) || 0;
      const currentNew = currentUnique - currentReturning;
      const currentRecurrenceRate = currentUnique > 0 ? (currentReturning / currentUnique) * 100 : 0;

      const prevReturning = Number(row.prev_returning_customers) || 0;
      const prevUnique = Number(row.prev_unique_customers) || 0;
      const prevNew = prevUnique - prevReturning;
      const prevRecurrenceRate = prevUnique > 0 ? (prevReturning / prevUnique) * 100 : 0;

      return {
        totalSales: Number(row.current_total_sales) || 0,
        orderCount: Number(row.current_order_count) || 0,
        averageOrderValue: Number(row.current_avg_order_value) || 0,
        newCustomers: Math.max(0, currentNew),
        recurringCustomers: currentReturning,
        recurrenceRate: currentRecurrenceRate,
        customerLtv: Number(row.current_ltv) || 0,
        previousPeriod: {
          totalSales: Number(row.prev_total_sales) || 0,
          orderCount: Number(row.prev_order_count) || 0,
          averageOrderValue: Number(row.prev_avg_order_value) || 0,
          newCustomers: Math.max(0, prevNew),
          recurringCustomers: prevReturning,
          recurrenceRate: prevRecurrenceRate,
          customerLtv: Number(row.prev_ltv) || 0,
        },
      };
    } catch (error: any) {
      throw new Error(`KPI calculation failed: ${error.message}`);
    }
  }

  async calculateTrends(
    datasetId: string,
    dateFrom: string,
    dateTo: string,
    dateColumn: string = "created",
    salesTable: string = "subscriptions",
    salesColumn: string = "amount",
    customerIdColumn: string = "customer_id"
  ): Promise<{
    salesTrend: { date: string; sales: number; orders: number }[];
    customerTrend: { date: string; newCustomers: number; returningCustomers: number }[];
  }> {
    const targetDataset = datasetId || this.datasetId;
    if (!targetDataset) {
      throw new Error("Dataset ID is required for trend calculation");
    }

    const fullyQualifiedTable = `\`${this.projectId}.${targetDataset}.${salesTable}\``;

    const daysDiff = Math.ceil((new Date(dateTo).getTime() - new Date(dateFrom).getTime()) / (1000 * 60 * 60 * 24));
    const groupBy = daysDiff > 90 ? "MONTH" : daysDiff > 31 ? "ISOWEEK" : "DAY";
    const truncExpr = groupBy === "DAY"
      ? `DATE(${dateColumn})`
      : groupBy === "ISOWEEK"
        ? `DATE_TRUNC(DATE(${dateColumn}), ISOWEEK)`
        : `DATE_TRUNC(DATE(${dateColumn}), MONTH)`;

    const salesSql = `
      SELECT
        ${truncExpr} as period_date,
        COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as total_sales,
        COUNT(*) as order_count
      FROM ${fullyQualifiedTable}
      WHERE DATE(${dateColumn}) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')
      GROUP BY period_date
      ORDER BY period_date
    `;

    const customerSql = `
      WITH first_purchase AS (
        SELECT ${customerIdColumn}, MIN(DATE(${dateColumn})) as first_date
        FROM ${fullyQualifiedTable}
        GROUP BY ${customerIdColumn}
      ),
      period_customers AS (
        SELECT
          ${truncExpr} as period_date,
          t.${customerIdColumn},
          fp.first_date
        FROM ${fullyQualifiedTable} t
        JOIN first_purchase fp ON t.${customerIdColumn} = fp.${customerIdColumn}
        WHERE DATE(t.${dateColumn}) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')
      )
      SELECT
        period_date,
        COUNT(DISTINCT CASE WHEN first_date >= DATE('${dateFrom}') THEN ${customerIdColumn} END) as new_customers,
        COUNT(DISTINCT CASE WHEN first_date < DATE('${dateFrom}') THEN ${customerIdColumn} END) as returning_customers
      FROM period_customers
      GROUP BY period_date
      ORDER BY period_date
    `;

    const [salesResult, customerResult] = await Promise.all([
      this.client.query({ query: salesSql }),
      this.client.query({ query: customerSql }),
    ]);

    const salesTrend = (salesResult[0] || []).map((row: any) => ({
      date: String(row.period_date?.value || row.period_date),
      sales: Number(row.total_sales) || 0,
      orders: Number(row.order_count) || 0,
    }));

    const customerTrend = (customerResult[0] || []).map((row: any) => ({
      date: String(row.period_date?.value || row.period_date),
      newCustomers: Number(row.new_customers) || 0,
      returningCustomers: Number(row.returning_customers) || 0,
    }));

    return { salesTrend, customerTrend };
  }

  async calculateProductAnalytics(
    datasetId: string,
    dateFrom: string,
    dateTo: string,
    dateColumn: string = "created",
    salesTable: string = "subscriptions",
    salesColumn: string = "amount",
    customerIdColumn: string = "customer_id"
  ): Promise<{
    topProducts: { planName: string; productId: string; revenue: number; subscriptions: number; avgAmount: number }[];
    statusBreakdown: { status: string; count: number; revenue: number }[];
    intervalBreakdown: { interval: string; count: number; revenue: number }[];
    productTrend: { date: string; planName: string; revenue: number; count: number }[];
  }> {
    const targetDataset = datasetId || this.datasetId;
    if (!targetDataset) {
      throw new Error("Dataset ID is required for product analytics");
    }

    const fullyQualifiedTable = `\`${this.projectId}.${targetDataset}.${salesTable}\``;

    const topProductsSql = `
      SELECT
        COALESCE(plan_name, 'Unknown') as plan_name,
        COALESCE(product_id, 'N/A') as product_id,
        COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as revenue,
        COUNT(*) as subscription_count,
        COALESCE(AVG(CAST(${salesColumn} AS FLOAT64)), 0) as avg_amount
      FROM ${fullyQualifiedTable}
      WHERE DATE(${dateColumn}) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')
      GROUP BY plan_name, product_id
      ORDER BY revenue DESC
      LIMIT 20
    `;

    const statusSql = `
      SELECT
        COALESCE(status, 'unknown') as status,
        COUNT(*) as count,
        COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as revenue
      FROM ${fullyQualifiedTable}
      WHERE DATE(${dateColumn}) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')
      GROUP BY status
      ORDER BY count DESC
    `;

    const intervalSql = `
      SELECT
        COALESCE(subscription_interval, 'unknown') as sub_interval,
        COUNT(*) as count,
        COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as revenue
      FROM ${fullyQualifiedTable}
      WHERE DATE(${dateColumn}) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')
      GROUP BY subscription_interval
      ORDER BY revenue DESC
    `;

    const daysDiff = Math.ceil((new Date(dateTo).getTime() - new Date(dateFrom).getTime()) / (1000 * 60 * 60 * 24));
    const groupBy = daysDiff > 90 ? "MONTH" : daysDiff > 31 ? "ISOWEEK" : "DAY";
    const truncExpr = groupBy === "DAY"
      ? `DATE(${dateColumn})`
      : groupBy === "ISOWEEK"
        ? `DATE_TRUNC(DATE(${dateColumn}), ISOWEEK)`
        : `DATE_TRUNC(DATE(${dateColumn}), MONTH)`;

    const productTrendSql = `
      SELECT
        ${truncExpr} as period_date,
        COALESCE(plan_name, 'Unknown') as plan_name,
        COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as revenue,
        COUNT(*) as count
      FROM ${fullyQualifiedTable}
      WHERE DATE(${dateColumn}) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')
      GROUP BY period_date, plan_name
      ORDER BY period_date, revenue DESC
    `;

    try {
      const [topProductsResult, statusResult, intervalResult, trendResult] = await Promise.all([
        this.client.query({ query: topProductsSql }),
        this.client.query({ query: statusSql }),
        this.client.query({ query: intervalSql }),
        this.client.query({ query: productTrendSql }),
      ]);

      const topProducts = (topProductsResult[0] || []).map((row: any) => ({
        planName: String(row.plan_name || "Unknown"),
        productId: String(row.product_id || "N/A"),
        revenue: Number(row.revenue) || 0,
        subscriptions: Number(row.subscription_count) || 0,
        avgAmount: Number(row.avg_amount) || 0,
      }));

      const statusBreakdown = (statusResult[0] || []).map((row: any) => ({
        status: String(row.status || "unknown"),
        count: Number(row.count) || 0,
        revenue: Number(row.revenue) || 0,
      }));

      const intervalBreakdown = (intervalResult[0] || []).map((row: any) => ({
        interval: String(row.sub_interval || "unknown"),
        count: Number(row.count) || 0,
        revenue: Number(row.revenue) || 0,
      }));

      const productTrend = (trendResult[0] || []).map((row: any) => ({
        date: String(row.period_date?.value || row.period_date),
        planName: String(row.plan_name || "Unknown"),
        revenue: Number(row.revenue) || 0,
        count: Number(row.count) || 0,
      }));

      return { topProducts, statusBreakdown, intervalBreakdown, productTrend };
    } catch (error: any) {
      console.error("Product analytics calculation failed:", error.message);
      throw new Error(`Product analytics failed: ${error.message}`);
    }
  }

  async calculateDashboardKPIs(
    datasetId: string,
    dateFrom: string,
    dateTo: string,
    dateColumn: string = "created",
    salesTable: string = "subscriptions",
    salesColumn: string = "amount"
  ): Promise<{
    totalSales: number;
    activeMemberships: number;
    netMonthlyGrowth: number;
    inactivePercent: number;
    monthlyRecurringRevenue: number;
    averagePurchaseAmount: number;
    changes: {
      totalSales: number;
      activeMemberships: number;
      netMonthlyGrowth: number;
      inactivePercent: number;
      monthlyRecurringRevenue: number;
      averagePurchaseAmount: number;
    };
  }> {
    const targetDataset = datasetId || this.datasetId;
    if (!targetDataset) {
      throw new Error("Dataset ID is required for dashboard KPI calculation");
    }

    const fullyQualifiedTable = `\`${this.projectId}.${targetDataset}.${salesTable}\``;

    const daysDiff = Math.ceil((new Date(dateTo).getTime() - new Date(dateFrom).getTime()) / (1000 * 60 * 60 * 24));
    const prevToDate = new Date(new Date(dateFrom).getTime() - 24 * 60 * 60 * 1000);
    const prevFromDate = new Date(prevToDate.getTime() - daysDiff * 24 * 60 * 60 * 1000);
    const previousFrom = prevFromDate.toISOString().split("T")[0];
    const previousTo = prevToDate.toISOString().split("T")[0];

    const sql = `
      WITH
      -- Current period: total sales and count
      current_sales AS (
        SELECT COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as total_sales,
               COUNT(*) as sales_count
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')
      ),
      prev_sales AS (
        SELECT COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as total_sales,
               COUNT(*) as sales_count
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) BETWEEN DATE('${previousFrom}') AND DATE('${previousTo}')
      ),
      -- Active memberships: subscriptions created before end date that are not canceled (or canceled after end date)
      current_active AS (
        SELECT COUNT(*) as active_count
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) <= DATE('${dateTo}')
          AND (canceled_at IS NULL OR DATE(canceled_at) > DATE('${dateTo}'))
      ),
      prev_active AS (
        SELECT COUNT(*) as active_count
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) <= DATE('${previousTo}')
          AND (canceled_at IS NULL OR DATE(canceled_at) > DATE('${previousTo}'))
      ),
      -- Inactive (canceled) subscriptions as of end date
      current_inactive AS (
        SELECT COUNT(*) as inactive_count
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) <= DATE('${dateTo}')
          AND canceled_at IS NOT NULL AND DATE(canceled_at) <= DATE('${dateTo}')
      ),
      prev_inactive AS (
        SELECT COUNT(*) as inactive_count
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) <= DATE('${previousTo}')
          AND canceled_at IS NOT NULL AND DATE(canceled_at) <= DATE('${previousTo}')
      ),
      -- Net growth: new subs created in period minus cancellations in period
      current_growth AS (
        SELECT
          (SELECT COUNT(*) FROM ${fullyQualifiedTable} WHERE DATE(${dateColumn}) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')) as new_subs,
          (SELECT COUNT(*) FROM ${fullyQualifiedTable} WHERE canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')) as canceled_subs
      ),
      prev_growth AS (
        SELECT
          (SELECT COUNT(*) FROM ${fullyQualifiedTable} WHERE DATE(${dateColumn}) BETWEEN DATE('${previousFrom}') AND DATE('${previousTo}')) as new_subs,
          (SELECT COUNT(*) FROM ${fullyQualifiedTable} WHERE canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('${previousFrom}') AND DATE('${previousTo}')) as canceled_subs
      ),
      -- Monthly Recurring Revenue: sum of amount for all active subscriptions
      current_mrr AS (
        SELECT COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as mrr
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) <= DATE('${dateTo}')
          AND (canceled_at IS NULL OR DATE(canceled_at) > DATE('${dateTo}'))
      ),
      prev_mrr AS (
        SELECT COALESCE(SUM(CAST(${salesColumn} AS FLOAT64)), 0) as mrr
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) <= DATE('${previousTo}')
          AND (canceled_at IS NULL OR DATE(canceled_at) > DATE('${previousTo}'))
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
    `;

    try {
      const result = await this.executeQuery(sql, { maxRows: 1 });
      const row = result.rows[0] || {};

      const currentTotalSales = Number(row.current_total_sales) || 0;
      const currentSalesCount = Number(row.current_sales_count) || 0;
      const prevTotalSales = Number(row.prev_total_sales) || 0;
      const prevSalesCount = Number(row.prev_sales_count) || 0;

      const currentAvgPurchase = currentSalesCount > 0 ? currentTotalSales / currentSalesCount : 0;
      const prevAvgPurchase = prevSalesCount > 0 ? prevTotalSales / prevSalesCount : 0;

      const currentActive = Number(row.current_active) || 0;
      const prevActive = Number(row.prev_active) || 0;

      const currentInactive = Number(row.current_inactive) || 0;
      const prevInactive = Number(row.prev_inactive) || 0;

      const currentNew = Number(row.current_new) || 0;
      const currentCanceled = Number(row.current_canceled) || 0;
      const prevNew = Number(row.prev_new) || 0;
      const prevCanceled = Number(row.prev_canceled) || 0;

      const currentNetGrowth = currentNew - currentCanceled;
      const prevNetGrowth = prevNew - prevCanceled;

      const currentTotal = currentActive + currentInactive;
      const prevTotal = prevActive + prevInactive;
      const currentInactivePercent = currentTotal > 0 ? Math.round(currentInactive * 10000 / currentTotal) / 100 : 0;
      const prevInactivePercent = prevTotal > 0 ? Math.round(prevInactive * 10000 / prevTotal) / 100 : 0;

      const currentMRR = Number(row.current_mrr) || 0;
      const prevMRR = Number(row.prev_mrr) || 0;

      const calcChange = (curr: number, prev: number) => {
        if (prev === 0) return curr > 0 ? 100 : curr < 0 ? -100 : 0;
        return ((curr - prev) / Math.abs(prev)) * 100;
      };

      return {
        totalSales: currentTotalSales,
        activeMemberships: currentActive,
        netMonthlyGrowth: currentNetGrowth,
        inactivePercent: currentInactivePercent,
        monthlyRecurringRevenue: currentMRR,
        averagePurchaseAmount: currentAvgPurchase,
        changes: {
          totalSales: calcChange(currentTotalSales, prevTotalSales),
          activeMemberships: calcChange(currentActive, prevActive),
          netMonthlyGrowth: calcChange(currentNetGrowth, prevNetGrowth),
          inactivePercent: calcChange(currentInactivePercent, prevInactivePercent),
          monthlyRecurringRevenue: calcChange(currentMRR, prevMRR),
          averagePurchaseAmount: calcChange(currentAvgPurchase, prevAvgPurchase),
        },
      };
    } catch (error: any) {
      console.error("Dashboard KPI calculation failed:", error.message);
      throw new Error(`Dashboard KPI calculation failed: ${error.message}`);
    }
  }

  async calculateChurnAnalytics(
    datasetId: string,
    dateFrom: string,
    dateTo: string,
    dateColumn: string = "created",
    salesTable: string = "subscriptions",
    salesColumn: string = "amount"
  ): Promise<{
    summary: { totalStart: number; totalCanceled: number; churnRate: number; canceledRevenue: number };
    monthlyTrend: { month: string; activeStart: number; canceled: number; churnRate: number }[];
    churnByProduct: { planName: string; productId: string; total: number; canceled: number; churnRate: number; canceledRevenue: number }[];
    periodComparison: { currentRate: number; previousRate: number; change: number };
  }> {
    const targetDataset = datasetId || this.datasetId;
    if (!targetDataset) {
      throw new Error("Dataset ID is required for churn analytics");
    }

    const fullyQualifiedTable = `\`${this.projectId}.${targetDataset}.${salesTable}\``;

    const daysDiff = Math.ceil((new Date(dateTo).getTime() - new Date(dateFrom).getTime()) / (1000 * 60 * 60 * 24));
    const previousFrom = new Date(new Date(dateFrom).getTime() - daysDiff * 24 * 60 * 60 * 1000).toISOString().split("T")[0];
    const previousTo = dateFrom;

    const summarySql = `
      WITH active_at_start AS (
        SELECT *
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) < DATE('${dateFrom}')
          AND (canceled_at IS NULL OR DATE(canceled_at) >= DATE('${dateFrom}'))
      )
      SELECT
        COUNT(*) as total,
        COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')) as canceled,
        COALESCE(SUM(CASE WHEN canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}') THEN CAST(${salesColumn} AS FLOAT64) ELSE 0 END), 0) as canceled_revenue
      FROM active_at_start
    `;

    const monthlyTrendSql = `
      WITH date_range AS (
        SELECT
          DATE_TRUNC(d, MONTH) as month_start,
          DATE_ADD(DATE_TRUNC(d, MONTH), INTERVAL 1 MONTH) as month_end
        FROM UNNEST(
          GENERATE_DATE_ARRAY(
            DATE_TRUNC(DATE('${dateFrom}'), MONTH),
            DATE('${dateTo}'),
            INTERVAL 1 MONTH
          )
        ) as d
      ),
      monthly AS (
        SELECT
          dr.month_start,
          (SELECT COUNT(*) FROM ${fullyQualifiedTable}
           WHERE DATE(${dateColumn}) < dr.month_start
             AND (canceled_at IS NULL OR DATE(canceled_at) >= dr.month_start)
          ) as active_at_start,
          (SELECT COUNT(*) FROM ${fullyQualifiedTable}
           WHERE DATE(${dateColumn}) < dr.month_start
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
    `;

    const churnByProductSql = `
      WITH active_at_start AS (
        SELECT *
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) < DATE('${dateFrom}')
          AND (canceled_at IS NULL OR DATE(canceled_at) >= DATE('${dateFrom}'))
      )
      SELECT
        COALESCE(plan_name, 'Unknown') as plan_name,
        COALESCE(product_id, 'N/A') as product_id,
        COUNT(*) as total,
        COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')) as canceled,
        CASE WHEN COUNT(*) > 0 THEN ROUND(
          COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')) * 100.0 / COUNT(*), 2
        ) ELSE 0 END as churn_rate,
        COALESCE(SUM(CASE WHEN canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('${dateFrom}') AND DATE('${dateTo}')
          THEN CAST(${salesColumn} AS FLOAT64) ELSE 0 END), 0) as canceled_revenue
      FROM active_at_start
      GROUP BY plan_name, product_id
      ORDER BY canceled DESC
    `;

    const previousPeriodSql = `
      WITH active_at_start AS (
        SELECT *
        FROM ${fullyQualifiedTable}
        WHERE DATE(${dateColumn}) < DATE('${previousFrom}')
          AND (canceled_at IS NULL OR DATE(canceled_at) >= DATE('${previousFrom}'))
      )
      SELECT
        COUNT(*) as total,
        COUNTIF(canceled_at IS NOT NULL AND DATE(canceled_at) BETWEEN DATE('${previousFrom}') AND DATE('${previousTo}')) as canceled
      FROM active_at_start
    `;

    try {
      const [summaryResult, monthlyResult, productResult, previousResult] = await Promise.all([
        this.client.query({ query: summarySql }),
        this.client.query({ query: monthlyTrendSql }),
        this.client.query({ query: churnByProductSql }),
        this.client.query({ query: previousPeriodSql }),
      ]);

      const summaryRow = (summaryResult[0] || [])[0] || {};
      const totalStart = Number(summaryRow.total) || 0;
      const totalCanceled = Number(summaryRow.canceled) || 0;
      const canceledRevenue = Number(summaryRow.canceled_revenue) || 0;
      const churnRate = totalStart > 0 ? Math.round(totalCanceled * 10000 / totalStart) / 100 : 0;

      const monthNames = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
      const monthlyTrend = (monthlyResult[0] || []).map((row: any) => {
        const raw = String(row.month_start?.value || row.month_start);
        const parts = raw.split("-");
        const year = parts[0] || raw;
        const monthIdx = parseInt(parts[1] || "1", 10) - 1;
        const label = `${monthNames[monthIdx]} ${year}`;
        const shortLabel = `${monthNames[monthIdx]} ${year.slice(-2)}`;
        const safeDateStr = `${year}-${parts[1] || "01"}-15`;
        return {
          month: safeDateStr,
          monthLabel: label,
          monthShortLabel: shortLabel,
          activeStart: Number(row.total_in_month) || 0,
          canceled: Number(row.canceled_in_month) || 0,
          churnRate: Number(row.churn_rate) || 0,
        };
      });

      const churnByProduct = (productResult[0] || []).map((row: any) => ({
        planName: String(row.plan_name || "Unknown"),
        productId: String(row.product_id || "N/A"),
        total: Number(row.total) || 0,
        canceled: Number(row.canceled) || 0,
        churnRate: Number(row.churn_rate) || 0,
        canceledRevenue: Number(row.canceled_revenue) || 0,
      }));

      const prevRow = (previousResult[0] || [])[0] || {};
      const prevTotal = Number(prevRow.total) || 0;
      const prevCanceled = Number(prevRow.canceled) || 0;
      const previousRate = prevTotal > 0 ? Math.round(prevCanceled * 10000 / prevTotal) / 100 : 0;

      return {
        summary: { totalStart, totalCanceled, churnRate, canceledRevenue },
        monthlyTrend,
        churnByProduct,
        periodComparison: {
          currentRate: churnRate,
          previousRate,
          change: Math.round((churnRate - previousRate) * 100) / 100,
        },
      };
    } catch (error: any) {
      console.error("Churn analytics calculation failed:", error.message);
      throw new Error(`Churn analytics failed: ${error.message}`);
    }
  }

  formatSchemaForPrompt(schemas: SchemaColumn[], projectId?: string): string {
    const tableMap: Record<string, SchemaColumn[]> = {};

    for (const col of schemas) {
      const key = `${col.datasetName}.${col.tableName}`;
      if (!tableMap[key]) {
        tableMap[key] = [];
      }
      tableMap[key].push(col);
    }

    let prompt = "Available BigQuery tables:\n\n";

    for (const tableName of Object.keys(tableMap)) {
      const columns = tableMap[tableName];
      const fullyQualifiedName = projectId ? `${projectId}.${tableName}` : tableName;
      prompt += `Table: ${fullyQualifiedName}\n`;
      prompt += `  Full reference: \`${fullyQualifiedName}\`\n`;
      prompt += "Columns:\n";
      for (const col of columns) {
        const nullableStr = col.isNullable ? "nullable" : "required";
        const descStr = col.description ? ` - ${col.description}` : "";
        prompt += `  - ${col.columnName} (${col.dataType}, ${nullableStr})${descStr}\n`;
      }
      prompt += "\n";
    }

    return prompt;
  }
}
