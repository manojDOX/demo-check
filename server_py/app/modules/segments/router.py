"""Port of the `/api/segments*` routes from server/routes.ts (~lines 895-1393)."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import to_camel, to_camel_list
from app.db import get_db
from app.dependencies import can_access_client, get_user_id, is_admin_user, require_authenticated_or_token
from app.modules.clients import repo as clients_repo
from app.modules.connections import repo as connections_repo
from app.modules.connections.bigquery_service import BigQueryService
from app.modules.segments import repo, service
from app.modules.segments.ai_client import AIServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["segments"], dependencies=[Depends(require_authenticated_or_token)])


@router.get("/api/segments")
async def list_segments(request: Request, clientId: int | None = None, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        segments = await repo.get_segments(db, user_id, clientId)
        return to_camel_list(segments)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching segments")
        raise HTTPException(status_code=500, detail="Failed to fetch segments")


class CreateSegmentBody(BaseModel):
    name: str | None = None
    description: str | None = None
    clientId: int | None = None
    criteria: dict[str, Any] | None = None


@router.post("/api/segments")
async def create_segment(
    body: CreateSegmentBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        user_id = get_user_id(request)
        if not await is_admin_user(request, db):
            raise HTTPException(status_code=403, detail="Admin access required")
        segment = await repo.create_segment(
            db,
            user_id=user_id,
            name=body.name,
            description=body.description,
            client_id=body.clientId,
            criteria=body.criteria or {},
            is_ai_generated=False,
            status="active",
            contact_count=0,
        )
        return to_camel(segment)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error creating segment")
        raise HTTPException(status_code=500, detail="Failed to create segment")


class CreateSegmentFromQueryBody(BaseModel):
    name: str | None = None
    description: str | None = None
    sql: str | None = None
    memberData: list[Any] | None = None
    contactCount: int | None = None
    clientId: int | None = None


@router.post("/api/segments/from-query")
async def create_segment_from_query(
    body: CreateSegmentFromQueryBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        user_id = get_user_id(request)
        name = body.name
        description = body.description
        sql = body.sql
        member_data = body.memberData
        contact_count = body.contactCount
        client_id = body.clientId

        # Validate required fields
        if not name or not isinstance(name, str) or len(name.strip()) == 0:
            raise HTTPException(status_code=400, detail="Segment name is required")

        if len(name) > 100:
            raise HTTPException(status_code=400, detail="Segment name too long (max 100 characters)")

        # Validate memberData if provided
        if member_data is not None:
            if not isinstance(member_data, list):
                raise HTTPException(status_code=400, detail="memberData must be an array")
            if len(member_data) > 10000:
                raise HTTPException(status_code=400, detail="Maximum 10,000 members allowed per segment")

        # Validate clientId access if provided
        if client_id:
            has_access = await can_access_client(request, db, client_id)
            if not has_access:
                raise HTTPException(status_code=403, detail="Invalid client ID")

        logger.info("[SEGMENT-FROM-QUERY] Creating segment from query")
        logger.info("[SEGMENT-FROM-QUERY] Name: %s", name)
        logger.info("[SEGMENT-FROM-QUERY] Members: %d", len(member_data) if member_data else 0)

        # Create the segment
        segment = await repo.create_segment(
            db,
            user_id=user_id,
            name=name.strip(),
            description=description or "Segmento creado desde consulta",
            client_id=client_id or None,
            criteria={"source": "query", "createdFrom": "natural_language_query"},
            is_ai_generated=False,
            status="active",
            contact_count=contact_count or (len(member_data) if member_data else 0),
        )

        # Update with member data and SQL
        updated_segment = await repo.update_segment(
            db,
            segment.id,
            {"generated_sql": sql or None, "member_data": member_data or None},
        )

        logger.info("[SEGMENT-FROM-QUERY] Segment created successfully: %s", segment.id)
        return to_camel(updated_segment)
    except HTTPException:
        raise
    except Exception:
        logger.exception("[SEGMENT-FROM-QUERY] Error")
        raise HTTPException(status_code=500, detail="Failed to create segment from query")


class GenerateSegmentBody(BaseModel):
    clientId: int | str | None = None


@router.post("/api/segments/generate")
async def generate_segment(
    body: GenerateSegmentBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        if not await is_admin_user(request, db):
            raise HTTPException(status_code=403, detail="Admin access required")
        client_id = int(body.clientId) if body.clientId else None

        segment = await service.generate_ai_segment(request, db, client_id)
        return to_camel(segment)
    except HTTPException:
        raise
    except AIServiceError as error:
        logger.error("[SEGMENT-GEN] ERROR: %s", error)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "El servicio de IA no está disponible temporalmente. Por favor intenta en un momento.",
                "errorType": "ai_unavailable",
            },
        )
    except Exception as error:
        logger.exception("[SEGMENT-GEN] ERROR")
        raise HTTPException(
            status_code=500,
            detail={"error": str(error) or "Failed to generate segment", "errorType": "unknown"},
        )


@router.get("/api/segments/{id}")
async def get_segment(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        segment = await repo.get_segment(db, id)

        if segment is None:
            raise HTTPException(status_code=404, detail="Segment not found")

        if segment.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        return to_camel(segment)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching segment")
        raise HTTPException(status_code=500, detail="Failed to fetch segment")


@router.get("/api/segments/{id}/members")
async def get_segment_members(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        segment = await repo.get_segment(db, id)

        if segment is None:
            raise HTTPException(status_code=404, detail="Segment not found")

        if segment.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # If we have cached member data, return it
        if segment.member_data:
            return {
                "members": segment.member_data,
                "count": segment.contact_count or len(segment.member_data),
                "cached": True,
            }

        # If we have generated SQL, try to re-execute it for fresh data
        if segment.generated_sql:
            connection = None

            if segment.client_id:
                client = await clients_repo.get_client(db, segment.client_id)
                if client and client.connection_id:
                    connection = await connections_repo.get_connection(db, client.connection_id)

            if not connection:
                connections = await connections_repo.get_connections(db, user_id)
                if connections:
                    connection = connections[0]

            if connection:
                try:
                    bq_service = BigQueryService.from_credentials_json(
                        connection.project_id, connection.credentials, connection.dataset_id or ""
                    )

                    result = await bq_service.execute_query(segment.generated_sql, max_rows=10000)

                    await repo.update_segment(
                        db, id, {"member_data": result.rows, "contact_count": result.total_rows}
                    )

                    return {"members": result.rows, "count": result.total_rows, "cached": False}
                except Exception as error:
                    logger.error("Error re-executing segment SQL: %s", error)

        # No member data available
        return {
            "members": [],
            "count": segment.contact_count or 0,
            "cached": False,
            "message": "No member data available for this segment",
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching segment members")
        raise HTTPException(status_code=500, detail="Failed to fetch segment members")


@router.delete("/api/segments/{id}")
async def delete_segment(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        logger.info("[SEGMENT-DELETE] Attempting to delete segment: %s by user: %s", id, user_id)

        segment = await repo.get_segment(db, id)

        if segment is None:
            logger.info("[SEGMENT-DELETE] Segment not found: %s", id)
            raise HTTPException(status_code=404, detail="Segment not found")

        logger.info(
            "[SEGMENT-DELETE] Found segment: %s %s owner: %s", segment.id, segment.name, segment.user_id
        )

        if segment.user_id != user_id:
            logger.info(
                "[SEGMENT-DELETE] Access denied - segment owner: %s requester: %s", segment.user_id, user_id
            )
            raise HTTPException(status_code=403, detail="Access denied")

        await repo.delete_segment(db, id)
        logger.info("[SEGMENT-DELETE] Successfully deleted segment: %s", id)
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("[SEGMENT-DELETE] Error deleting segment")
        raise HTTPException(status_code=500, detail="Failed to delete segment")
