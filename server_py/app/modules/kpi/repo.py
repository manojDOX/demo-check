"""Data-access helper(s) for the KPI module.

Deliberately NOT added to app/modules/connections/repo.py (out of scope / that module
may still be under active iteration by another agent) — implemented here instead, as
permitted by the task instructions when a shared-repo addition isn't safe to make.

Port of server/storage.ts's `getConnectionByClientId` (~line 177):
    async getConnectionByClientId(clientId) {
      const client = await this.getClient(clientId);
      if (!client || !client.connectionId) return undefined;
      return this.getConnection(client.connectionId);
    }
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clients import Client
from app.models.connections import BigQueryConnection


async def get_connection_by_client_id(db: AsyncSession, client_id: int) -> BigQueryConnection | None:
    client_result = await db.execute(select(Client).where(Client.id == client_id))
    client = client_result.scalar_one_or_none()
    if client is None or not client.connection_id:
        return None

    conn_result = await db.execute(
        select(BigQueryConnection).where(BigQueryConnection.id == client.connection_id)
    )
    return conn_result.scalar_one_or_none()
