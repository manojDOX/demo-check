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
