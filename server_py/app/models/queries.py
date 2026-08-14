from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Query(Base):
    """Legacy chat/query history table. Kept as-is — still backs
    /api/segments/from-query and the recommendation-intent flow.
    The rebuilt chatbot no longer writes to this table (see chat_sessions/chat_messages).
    """

    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int | None] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="SET NULL")
    )
    natural_language: Mapped[str] = mapped_column("natural_language", Text, nullable=False)
    generated_sql: Mapped[str | None] = mapped_column("generated_sql", Text)
    result_summary: Mapped[str | None] = mapped_column("result_summary", Text)
    result_data: Mapped[list | None] = mapped_column("result_data", JSON)
    visualization_type: Mapped[str | None] = mapped_column("visualization_type", Text)
    is_saved: Mapped[bool | None] = mapped_column("is_saved", Boolean, default=False)
    is_recommendation: Mapped[bool | None] = mapped_column("is_recommendation", Boolean, default=False)
    recommendation_text: Mapped[str | None] = mapped_column("recommendation_text", Text)
    execution_time_ms: Mapped[int | None] = mapped_column("execution_time_ms", Integer)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
