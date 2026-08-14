import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Session(Base):
    """Mandatory for Replit Auth — table shape must never change (sid/sess/expire)."""

    __tablename__ = "sessions"
    __table_args__ = (Index("IDX_session_expire", "expire"),)

    sid: Mapped[str] = mapped_column(String, primary_key=True)
    sess: Mapped[dict] = mapped_column(JSON, nullable=False)
    expire: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, server_default=text("gen_random_uuid()"))
    email: Mapped[str | None] = mapped_column(String, unique=True)
    first_name: Mapped[str | None] = mapped_column("first_name", String)
    last_name: Mapped[str | None] = mapped_column("last_name", String)
    company: Mapped[str | None] = mapped_column(String)
    profile_image_url: Mapped[str | None] = mapped_column("profile_image_url", String)
    ghl_api_key: Mapped[str | None] = mapped_column("ghl_api_key", String)
    ghl_location_id: Mapped[str | None] = mapped_column("ghl_location_id", String)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updated_at", DateTime, server_default=func.now())
