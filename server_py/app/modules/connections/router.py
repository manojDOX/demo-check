"""Port of the `/api/connections*` routes from server/routes.ts (~lines 695-895)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import to_camel, to_camel_list
from app.db import get_db
from app.dependencies import get_user_id, is_admin_user, require_authenticated_or_token
from app.modules.connections import repo
from app.modules.connections.bigquery_service import BigQueryService

router = APIRouter(tags=["connections"], dependencies=[Depends(require_authenticated_or_token)])


def _with_masked_credentials(camel: dict) -> dict:
    camel["credentials"] = "[ENCRYPTED]"
    return camel


@router.get("/api/connections")
async def list_connections(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        connections = await repo.get_connections(db, user_id)
        return [_with_masked_credentials(to_camel(c)) for c in connections]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch connections")


class CreateConnectionBody(BaseModel):
    name: str
    projectId: str
    datasetId: str | None = None
    credentials: str


@router.post("/api/connections")
async def create_connection(
    body: CreateConnectionBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        user_id = get_user_id(request)
        if not await is_admin_user(request, db):
            raise HTTPException(status_code=403, detail="Admin access required")
        connection = await repo.create_connection(
            db,
            user_id=user_id,
            name=body.name,
            project_id=body.projectId,
            dataset_id=body.datasetId,
            credentials=body.credentials,
            is_active=True,
        )
        return _with_masked_credentials(to_camel(connection))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create connection")


async def _discover_schemas_with_fallback(bq_service: BigQueryService) -> list:
    schemas: list = []
    try:
        schemas = await bq_service.discover_schema(None)
    except Exception:
        pass

    if not schemas:
        try:
            schemas = await bq_service.discover_schema_via_sql(None)
        except Exception:
            schemas = []
    return schemas


@router.post("/api/connections/{id}/test")
async def test_connection(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)

        connection = await repo.get_connection(db, id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        if connection.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        bq_service = BigQueryService.from_credentials_json(
            connection.project_id, connection.credentials, connection.dataset_id or None
        )

        result = await bq_service.test_connection()

        updated = await repo.update_connection(
            db,
            id,
            {"last_tested_at": datetime.utcnow(), "is_active": result["success"]},  # TIMESTAMP WITHOUT TIME ZONE column
        )

        schema_count = 0
        if result["success"]:
            schemas = await _discover_schemas_with_fallback(bq_service)
            if schemas:
                await repo.delete_connection_schemas(db, id)
                for schema in schemas:
                    await repo.create_connection_schema(
                        db,
                        connection_id=id,
                        dataset_name=schema.dataset_name,
                        table_name=schema.table_name,
                        column_name=schema.column_name,
                        data_type=schema.data_type,
                        is_nullable=schema.is_nullable,
                        description=schema.description,
                    )
                schema_count = len(schemas)

        message = result["message"]
        if schema_count > 0:
            message += f" Discovered {schema_count} columns."

        return {
            "success": result["success"],
            "message": message,
            "schemaCount": schema_count,
            "connection": _with_masked_credentials(to_camel(updated)),
        }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error) or "Connection test failed")


@router.get("/api/connections/{id}/schema")
async def get_connection_schema(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)

        connection = await repo.get_connection(db, id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        if connection.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        schemas = await repo.get_connection_schemas(db, id)
        return to_camel_list(schemas)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch schema")


@router.post("/api/connections/{id}/refresh-schema")
async def refresh_connection_schema(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)

        connection = await repo.get_connection(db, id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        if connection.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        bq_service = BigQueryService.from_credentials_json(
            connection.project_id, connection.credentials, connection.dataset_id or None
        )

        schemas = []
        try:
            schemas = await bq_service.discover_schema(None)
        except Exception:
            pass

        if not schemas:
            try:
                schemas = await bq_service.discover_schema_via_sql(None)
            except Exception as sql_error:
                raise HTTPException(
                    status_code=500, detail=f"Schema discovery failed: {sql_error}"
                )

        await repo.delete_connection_schemas(db, id)
        for schema in schemas:
            await repo.create_connection_schema(
                db,
                connection_id=id,
                dataset_name=schema.dataset_name,
                table_name=schema.table_name,
                column_name=schema.column_name,
                data_type=schema.data_type,
                is_nullable=schema.is_nullable,
                description=schema.description,
            )

        return {"success": True, "count": len(schemas)}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error) or "Failed to refresh schema")


@router.delete("/api/connections/{id}")
async def delete_connection(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        get_user_id(request)
        if not await is_admin_user(request, db):
            raise HTTPException(status_code=403, detail="Admin access required")
        await repo.delete_connection(db, id)
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete connection")
