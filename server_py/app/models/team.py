from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_user_id: Mapped[str] = mapped_column(
        "admin_user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="viewer")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    user_id: Mapped[str | None] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="SET NULL")
    )
    share_token: Mapped[str | None] = mapped_column("share_token", String, unique=True)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())


class TeamMemberClient(Base):
    __tablename__ = "team_member_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_member_id: Mapped[int] = mapped_column(
        "team_member_id", Integer, ForeignKey("team_members.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
