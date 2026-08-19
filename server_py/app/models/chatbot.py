from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import EncryptedString
from app.db import Base


class ChatbotToken(Base):
    """BYO LLM provider key. Simplified from the CHATBOT_ARCHITECTURE.md reference —
    no agency/sharing rows; XIOMARA's existing team/share-token model already handles
    collaborator access (resolve by the client's owning user_id)."""

    __tablename__ = "chatbot_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, server_default=text("gen_random_uuid()"))
    owner_user_id: Mapped[str] = mapped_column(
        "owner_user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    llm_api_token: Mapped[str] = mapped_column("llm_api_token", EncryptedString(4000), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    available_models: Mapped[str | None] = mapped_column("available_models", Text)
    display_name: Mapped[str | None] = mapped_column("display_name", String)
    is_active: Mapped[bool] = mapped_column("is_active", Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())


class ChatbotUsage(Base):
    __tablename__ = "chatbot_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    successful_calls: Mapped[int] = mapped_column("successful_calls", Integer, default=0)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_sessions_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[str] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int | None] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE")
    )
    connection_id: Mapped[int | None] = mapped_column(
        "connection_id", Integer, ForeignKey("bigquery_connections.id", ondelete="SET NULL")
    )
    token_id: Mapped[str | None] = mapped_column(
        "token_id", String, ForeignKey("chatbot_tokens.id", ondelete="SET NULL")
    )
    name: Mapped[str | None] = mapped_column(String)
    # Set by the "Clear history" action (POST .../clear-history) to the moment it was
    # clicked. service.py's history loader only threads messages created AFTER this
    # timestamp into the LLM's conversation context — earlier turns stay visible in the
    # UI (nothing is deleted) but stop being sent to the model. NULL means "never cleared,
    # use full history" (bounded by the existing 5-turn window either way).
    history_cleared_at: Mapped[datetime | None] = mapped_column("history_cleared_at", DateTime)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updated_at", DateTime, server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_created", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[str] = mapped_column(
        "session_id", String, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    tables_used: Mapped[list | None] = mapped_column("tables_used", JSON)
    rows: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updated_at", DateTime, server_default=func.now())
