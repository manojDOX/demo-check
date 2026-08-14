"""Data-access helpers for segments.

Mirrors the relevant bits of server/storage.ts (DatabaseStorage class):
getSegments, getSegment, createSegment, updateSegment, deleteSegment.
"""

from sqlalchemy import and_, delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.segments import Segment


async def get_segments(db: AsyncSession, user_id: str, client_id: int | None = None) -> list[Segment]:
    stmt = select(Segment).where(Segment.user_id == user_id)
    if client_id:
        stmt = stmt.where(Segment.client_id == client_id)
    stmt = stmt.order_by(desc(Segment.created_at))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_segment(db: AsyncSession, segment_id: int) -> Segment | None:
    result = await db.execute(select(Segment).where(Segment.id == segment_id))
    return result.scalar_one_or_none()


async def create_segment(
    db: AsyncSession,
    *,
    user_id: str,
    name: str,
    description: str | None,
    client_id: int | None,
    criteria: dict,
    is_ai_generated: bool = False,
    status: str = "active",
    contact_count: int = 0,
) -> Segment:
    segment = Segment(
        user_id=user_id,
        name=name,
        description=description,
        client_id=client_id,
        criteria=criteria,
        is_ai_generated=is_ai_generated,
        status=status,
        contact_count=contact_count,
    )
    db.add(segment)
    await db.commit()
    await db.refresh(segment)
    return segment


async def update_segment(db: AsyncSession, segment_id: int, data: dict) -> Segment | None:
    segment = await get_segment(db, segment_id)
    if segment is None:
        return None
    for key, value in data.items():
        setattr(segment, key, value)
    await db.commit()
    await db.refresh(segment)
    return segment


async def delete_segment(db: AsyncSession, segment_id: int) -> None:
    await db.execute(delete(Segment).where(Segment.id == segment_id))
    await db.commit()
