from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[int | None] = mapped_column(
        "connection_id", Integer, ForeignKey("bigquery_connections.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    industry: Mapped[str | None] = mapped_column(Text, default="retail")
    logo_url: Mapped[str | None] = mapped_column("logo_url", Text)
    primary_color: Mapped[str | None] = mapped_column("primary_color", Text, default="#3B82F6")
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())


class BusinessProfile(Base):
    __tablename__ = "business_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    target_audience: Mapped[str | None] = mapped_column("target_audience", Text)
    additional_info: Mapped[str | None] = mapped_column("additional_info", Text)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updated_at", DateTime, server_default=func.now())


class ProductCatalogItem(Base):
    __tablename__ = "product_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    benefits: Mapped[str | None] = mapped_column(Text)
    cost: Mapped[str | None] = mapped_column(Text)
    price: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
