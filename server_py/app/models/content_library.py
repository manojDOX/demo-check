from datetime import datetime

from sqlalchemy import ARRAY, JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ContentLibrary(Base):
    __tablename__ = "content_library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int | None] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE")
    )
    content_type: Mapped[str] = mapped_column("content_type", Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    segment_tags: Mapped[list[str] | None] = mapped_column("segment_tags", ARRAY(Text))
    is_active: Mapped[bool | None] = mapped_column("is_active", Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
