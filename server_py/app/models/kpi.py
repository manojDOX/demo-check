from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KpiSnapshot(Base):
    __tablename__ = "kpi_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_sales: Mapped[str | None] = mapped_column("total_sales", Text)
    order_count: Mapped[int | None] = mapped_column("order_count", Integer)
    average_order_value: Mapped[str | None] = mapped_column("average_order_value", Text)
    recurrence_rate: Mapped[str | None] = mapped_column("recurrence_rate", Text)
    new_customers: Mapped[int | None] = mapped_column("new_customers", Integer)
    recurring_customers: Mapped[int | None] = mapped_column("recurring_customers", Integer)
    cart_abandonment_rate: Mapped[str | None] = mapped_column("cart_abandonment_rate", Text)
    customer_lifetime_value: Mapped[str | None] = mapped_column("customer_lifetime_value", Text)
    return_rate: Mapped[str | None] = mapped_column("return_rate", Text)
    inventory_turnover: Mapped[str | None] = mapped_column("inventory_turnover", Text)
    raw_data: Mapped[dict | None] = mapped_column("raw_data", JSON)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
