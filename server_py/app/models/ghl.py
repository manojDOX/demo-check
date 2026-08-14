from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GhlExport(Base):
    __tablename__ = "ghl_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[int | None] = mapped_column(
        "segment_id", Integer, ForeignKey("segments.id", ondelete="SET NULL")
    )
    contact_count: Mapped[int] = mapped_column("contact_count", Integer, nullable=False)
    status: Mapped[str | None] = mapped_column(Text, default="pending")
    ghl_location_id: Mapped[str | None] = mapped_column("ghl_location_id", Text)
    ghl_tags: Mapped[list[str] | None] = mapped_column("ghl_tags", ARRAY(Text))
    error_message: Mapped[str | None] = mapped_column("error_message", Text)
    completed_at: Mapped[datetime | None] = mapped_column("completed_at", DateTime)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
