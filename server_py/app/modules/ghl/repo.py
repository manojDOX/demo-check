"""Data-access helpers for GoHighLevel exports.

Mirrors the relevant bits of server/storage.ts (DatabaseStorage class):
getExports, createExport, updateExport, getSegment.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ghl import GhlExport
from app.models.segments import Segment


async def get_exports(db: AsyncSession, user_id: str) -> list[GhlExport]:
    result = await db.execute(
        select(GhlExport).where(GhlExport.user_id == user_id).order_by(desc(GhlExport.created_at))
    )
    return list(result.scalars().all())


async def get_segment(db: AsyncSession, segment_id: int) -> Segment | None:
    result = await db.execute(select(Segment).where(Segment.id == segment_id))
    return result.scalar_one_or_none()


async def create_export(
    db: AsyncSession,
    *,
    user_id: str,
    segment_id: int | None,
    contact_count: int,
    status: str,
    ghl_location_id: str | None = None,
    ghl_tags: list[str] | None = None,
) -> GhlExport:
    export = GhlExport(
        user_id=user_id,
        segment_id=segment_id,
        contact_count=contact_count,
        status=status,
        ghl_location_id=ghl_location_id,
        ghl_tags=ghl_tags,
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)
    return export


async def update_export(db: AsyncSession, export_id: int, data: dict[str, Any]) -> GhlExport | None:
    result = await db.execute(select(GhlExport).where(GhlExport.id == export_id))
    export = result.scalar_one_or_none()
    if export is None:
        return None
    for key, value in data.items():
        setattr(export, key, value)
    await db.commit()
    await db.refresh(export)
    return export
