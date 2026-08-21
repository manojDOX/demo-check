from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import EncryptedString
from app.db import Base


class BigQueryConnection(Base):
    __tablename__ = "bigquery_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column("project_id", Text, nullable=False)
    dataset_id: Mapped[str | None] = mapped_column("dataset_id", Text)
    credentials: Mapped[str] = mapped_column(EncryptedString(8000), nullable=False)
    is_active: Mapped[bool | None] = mapped_column("is_active", Boolean, default=True)
    last_tested_at: Mapped[datetime | None] = mapped_column("last_tested_at", DateTime)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
    # Computed once (chat_bot.data_availability.get_min_dates) and cached here permanently — the
    # earliest date actually present in the raw autocare_ss.data/autocare_ss.stripe_customers
    # tables, which (unlike stripe_ss.*) cannot be backfilled further into the past. NULL until
    # first computed for this connection.
    min_session_date: Mapped[datetime | None] = mapped_column("min_session_date", DateTime)
    min_customer_created_date: Mapped[datetime | None] = mapped_column("min_customer_created_date", DateTime)


class ConnectionSchema(Base):
    __tablename__ = "connection_schemas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        "connection_id", Integer, ForeignKey("bigquery_connections.id", ondelete="CASCADE"), nullable=False
    )
    dataset_name: Mapped[str] = mapped_column("dataset_name", Text, nullable=False)
    table_name: Mapped[str] = mapped_column("table_name", Text, nullable=False)
    column_name: Mapped[str] = mapped_column("column_name", Text, nullable=False)
    data_type: Mapped[str] = mapped_column("data_type", Text, nullable=False)
    is_nullable: Mapped[bool | None] = mapped_column("is_nullable", Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updated_at", DateTime, server_default=func.now())
