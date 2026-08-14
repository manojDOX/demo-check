"""AI-generated segment flow — port of POST /api/segments/generate from server/routes.ts
(~lines 995-1254). Kept separate from router.py to keep the route handler thin.
"""

import json
import logging
import re

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_user_id
from app.modules.clients import repo as clients_repo
from app.modules.connections import repo as connections_repo
from app.modules.connections.bigquery_service import BigQueryService
from app.modules.segments import repo as segments_repo
from app.modules.segments.ai_client import AIServiceError, call_openai_with_timeout_and_retry
from app.modules.segments.prompts import SYSTEM_PROMPT, build_user_prompt
from app.models.segments import Segment

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


async def generate_ai_segment(request: Request, db: AsyncSession, client_id: int | None) -> Segment:
    user_id = get_user_id(request)

    logger.info("[SEGMENT-GEN] Starting segment generation")
    logger.info("[SEGMENT-GEN] userId: %s", user_id)
    logger.info("[SEGMENT-GEN] clientId from request: %s", client_id)

    # Get client and its BigQuery connection
    connection = None

    if client_id:
        client = await clients_repo.get_client(db, client_id)
        logger.info(
            "[SEGMENT-GEN] Client found: %s %s connectionId: %s",
            getattr(client, "id", None), getattr(client, "name", None), getattr(client, "connection_id", None),
        )
        if client and client.connection_id:
            connection = await connections_repo.get_connection(db, client.connection_id)
            logger.info(
                "[SEGMENT-GEN] Got connection from client: %s %s",
                getattr(connection, "id", None), getattr(connection, "name", None),
            )

    # If no client or no connection, try to get any connection for this user
    if not connection:
        logger.info("[SEGMENT-GEN] No connection from client, trying user connections...")
        connections = await connections_repo.get_connections(db, user_id)
        logger.info("[SEGMENT-GEN] User connections found: %d", len(connections))
        for i, c in enumerate(connections):
            logger.info("[SEGMENT-GEN]   [%d] id:%s name:%s project:%s", i, c.id, c.name, c.project_id)
        if connections:
            connection = connections[0]
            logger.info("[SEGMENT-GEN] Using first user connection: %s %s", connection.id, connection.name)

    if not connection:
        logger.info("[SEGMENT-GEN] ERROR: No connection found for user")
        raise HTTPException(
            status_code=400,
            detail="No BigQuery connection available. Please configure a BigQuery connection first.",
        )

    project_id = connection.project_id
    dataset_id = connection.dataset_id or ""
    logger.info("[SEGMENT-GEN] Using BigQuery - project: %s dataset: %s", project_id, dataset_id)

    # Initialize BigQuery service
    logger.info("[SEGMENT-GEN] Initializing BigQuery service...")
    bq_service = BigQueryService.from_credentials_json(project_id, connection.credentials, dataset_id)

    # Discover schema to understand the data (all datasets in the project)
    logger.info("[SEGMENT-GEN] Discovering schema...")
    schemas = await bq_service.discover_schema_via_sql(None)
    unique_tables = sorted({s.table_name for s in schemas})
    logger.info("[SEGMENT-GEN] Schema discovered - columns: %d tables: %d", len(schemas), len(unique_tables))
    for t in unique_tables:
        logger.info("[SEGMENT-GEN]   Table: %s", t)
    schema_prompt = bq_service.format_schema_for_prompt(schemas, project_id)

    # Get existing segments to avoid duplicates
    existing_segments = await segments_repo.get_segments(db, user_id, client_id or None)
    existing_segment_names = [s.name for s in existing_segments]
    existing_segment_types = [
        (s.criteria or {}).get("segmentType", "unknown") for s in existing_segments if s.is_ai_generated
    ]
    logger.info("[SEGMENT-GEN] Existing segments: %d", len(existing_segment_names))
    logger.info("[SEGMENT-GEN] Existing AI segment types: %s", ", ".join(existing_segment_types))

    # Use OpenAI to analyze and recommend a segment
    logger.info("[SEGMENT-GEN] Calling OpenAI for segment recommendation...")
    try:
        ai_response = await call_openai_with_timeout_and_retry(
            {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(schema_prompt, existing_segment_names)},
                ],
                "temperature": 0.3,
                "max_tokens": 1500,
            },
            timeout_ms=12000,
            max_retries=1,
        )
    except AIServiceError:
        raise
    except Exception as error:
        # Non-AIServiceError failures (e.g. bad request) still surface as a generic 500
        # below, matching the JS catch-all branch.
        raise RuntimeError(str(error)) from error

    ai_content = ai_response.choices[0].message.content if ai_response.choices else ""
    ai_content = ai_content or ""
    logger.info("[SEGMENT-GEN] OpenAI response received, length: %d", len(ai_content))
    logger.info("[SEGMENT-GEN] AI Response preview: %s...", ai_content[:300])

    # Parse AI response
    match = _JSON_BLOCK_RE.search(ai_content)
    if not match:
        logger.error("[SEGMENT-GEN] Failed to parse AI response: %s", ai_content)
        raise RuntimeError("La IA devolvió una respuesta que no pudo procesarse. Por favor intenta de nuevo.")
    try:
        segment_data = json.loads(match.group(0))
    except Exception:
        logger.error("[SEGMENT-GEN] Failed to parse AI response: %s", ai_content)
        raise RuntimeError("La IA devolvió una respuesta que no pudo procesarse. Por favor intenta de nuevo.")

    logger.info("[SEGMENT-GEN] Parsed segment data - name: %s", segment_data.get("segmentName"))
    generated_sql_preview = segment_data.get("sql")
    logger.info(
        "[SEGMENT-GEN] Generated SQL: %s",
        (generated_sql_preview[:100] + "...") if generated_sql_preview else "none",
    )

    # Try to execute the generated SQL to get segment members
    member_data: list = []
    contact_count = 0
    generated_sql = segment_data.get("sql")
    sql_execution_error: str | None = None

    if generated_sql:
        logger.info("[SEGMENT-GEN] Executing generated SQL to get segment members...")
        logger.info("[SEGMENT-GEN] Full SQL: %s", generated_sql)
        try:
            result = await bq_service.execute_query(generated_sql, max_rows=10000)
            member_data = result.rows
            contact_count = result.total_rows
            logger.info(
                "[SEGMENT-GEN] SQL executed successfully - rows: %d total: %d", len(member_data), contact_count
            )

            if not member_data:
                logger.info("[SEGMENT-GEN] No results found, trying fallback query...")
                fallback_sql = f"SELECT customer_id, email FROM `{project_id}.{dataset_id}.customers` LIMIT 100"
                try:
                    fallback_result = await bq_service.execute_query(fallback_sql, max_rows=100)
                    if fallback_result.rows:
                        member_data = fallback_result.rows
                        contact_count = fallback_result.total_rows
                        generated_sql = fallback_sql
                        logger.info("[SEGMENT-GEN] Fallback query succeeded - rows: %d", len(member_data))
                except Exception:
                    logger.info("[SEGMENT-GEN] Fallback query also failed")
        except Exception as sql_error:
            logger.error("[SEGMENT-GEN] SQL execution error: %s", sql_error)
            logger.error("[SEGMENT-GEN] Failed SQL: %s", generated_sql)
            sql_execution_error = str(sql_error)

            logger.info("[SEGMENT-GEN] Trying fallback query due to error...")
            fallback_sql = f"SELECT customer_id, email FROM `{project_id}.{dataset_id}.customers` LIMIT 100"
            try:
                fallback_result = await bq_service.execute_query(fallback_sql, max_rows=100)
                member_data = fallback_result.rows
                contact_count = fallback_result.total_rows
                generated_sql = fallback_sql
                logger.info("[SEGMENT-GEN] Fallback query succeeded - rows: %d", len(member_data))
            except Exception as fallback_error:
                logger.error("[SEGMENT-GEN] Fallback query also failed: %s", fallback_error)
                generated_sql = None
    else:
        logger.info("[SEGMENT-GEN] No SQL generated, segment will have no member data")

    # Create the segment with real data
    logger.info("[SEGMENT-GEN] Creating segment in database...")
    segment_criteria = {
        **(segment_data.get("criteria") or {}),
        "aiGenerated": True,
        "segmentType": segment_data.get("segmentType"),
        **({"sqlError": sql_execution_error} if sql_execution_error else {}),
    }

    segment = await segments_repo.create_segment(
        db,
        user_id=user_id,
        name=segment_data.get("segmentName") or "Segmento AI",
        description=segment_data.get("description") or "Segmento generado por inteligencia artificial.",
        client_id=client_id,
        criteria=segment_criteria,
        is_ai_generated=True,
        status="active",
        contact_count=contact_count or len(member_data),
    )
    logger.info("[SEGMENT-GEN] Segment created with id: %s", segment.id)

    updated_segment = await segments_repo.update_segment(
        db,
        segment.id,
        {
            "generated_sql": generated_sql,
            "member_data": member_data if member_data else None,
        },
    )
    logger.info("[SEGMENT-GEN] Segment updated with SQL and member data. Complete!")

    return updated_segment or segment
