"""Data-access helpers for BigQuery connections / connection schemas.

Mirrors the relevant bits of server/storage.ts (DatabaseStorage class):
getConnections, getConnection, createConnection, updateConnection, deleteConnection,
getConnectionSchemas, createConnectionSchema, deleteConnectionSchemas.
"""

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connections import BigQueryConnection, ConnectionSchema


async def get_connections(db: AsyncSession, user_id: str) -> list[BigQueryConnection]:
    result = await db.execute(
        select(BigQueryConnection)
        .where(BigQueryConnection.user_id == user_id)
        .order_by(desc(BigQueryConnection.created_at))
    )
    return list(result.scalars().all())


async def get_connection(db: AsyncSession, connection_id: int) -> BigQueryConnection | None:
    result = await db.execute(select(BigQueryConnection).where(BigQueryConnection.id == connection_id))
    return result.scalar_one_or_none()


async def create_connection(
    db: AsyncSession,
    *,
    user_id: str,
    name: str,
    project_id: str,
    dataset_id: str | None,
    credentials: str,
    is_active: bool = True,
) -> BigQueryConnection:
    connection = BigQueryConnection(
        user_id=user_id,
        name=name,
        project_id=project_id,
        dataset_id=dataset_id,
        credentials=credentials,
        is_active=is_active,
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return connection


async def update_connection(db: AsyncSession, connection_id: int, data: dict) -> BigQueryConnection | None:
    connection = await get_connection(db, connection_id)
    if connection is None:
        return None
    for key, value in data.items():
        setattr(connection, key, value)
    await db.commit()
    await db.refresh(connection)
    return connection


async def delete_connection(db: AsyncSession, connection_id: int) -> None:
    await db.execute(delete(BigQueryConnection).where(BigQueryConnection.id == connection_id))
    await db.commit()


async def get_connection_schemas(db: AsyncSession, connection_id: int) -> list[ConnectionSchema]:
    result = await db.execute(
        select(ConnectionSchema).where(ConnectionSchema.connection_id == connection_id)
    )
    return list(result.scalars().all())


async def create_connection_schema(
    db: AsyncSession,
    *,
    connection_id: int,
    dataset_name: str,
    table_name: str,
    column_name: str,
    data_type: str,
    is_nullable: bool,
    description: str | None = None,
) -> ConnectionSchema:
    schema = ConnectionSchema(
        connection_id=connection_id,
        dataset_name=dataset_name,
        table_name=table_name,
        column_name=column_name,
        data_type=data_type,
        is_nullable=is_nullable,
        description=description,
    )
    db.add(schema)
    await db.commit()
    await db.refresh(schema)
    return schema


async def delete_connection_schemas(db: AsyncSession, connection_id: int) -> None:
    await db.execute(delete(ConnectionSchema).where(ConnectionSchema.connection_id == connection_id))
    await db.commit()
