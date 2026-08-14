from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int | None] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    criteria: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    contact_count: Mapped[int | None] = mapped_column("contact_count", Integer, default=0)
    is_ai_generated: Mapped[bool | None] = mapped_column("is_ai_generated", Boolean, default=False)
    status: Mapped[str | None] = mapped_column(Text, default="active")
    generated_sql: Mapped[str | None] = mapped_column("generated_sql", Text)
    member_data: Mapped[dict | None] = mapped_column("member_data", JSON)
    last_synced_at: Mapped[datetime | None] = mapped_column("last_synced_at", DateTime)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
