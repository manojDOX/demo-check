from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PageDesign(Base):
    __tablename__ = "page_designs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int | None] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    is_published: Mapped[bool | None] = mapped_column("is_published", Boolean, default=False)
    published_version_id: Mapped[int | None] = mapped_column("published_version_id", Integer)
    published_at: Mapped[datetime | None] = mapped_column("published_at", DateTime)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updated_at", DateTime, server_default=func.now())


class PageVersion(Base):
    __tablename__ = "page_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(
        "page_id", Integer, ForeignKey("page_designs.id", ondelete="CASCADE"), nullable=False
    )
    version_name: Mapped[str] = mapped_column("version_name", Text, nullable=False)
    version_number: Mapped[int] = mapped_column("version_number", Integer, nullable=False, default=1)
    is_active: Mapped[bool | None] = mapped_column("is_active", Boolean, default=False)
    html_content: Mapped[str | None] = mapped_column("html_content", Text)
    css_content: Mapped[str | None] = mapped_column("css_content", Text)
    gjs_components: Mapped[dict | None] = mapped_column("gjs_components", JSON)
    gjs_styles: Mapped[dict | None] = mapped_column("gjs_styles", JSON)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())


class PageSection(Base):
    __tablename__ = "page_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        "version_id", Integer, ForeignKey("page_versions.id", ondelete="CASCADE"), nullable=False
    )
    section_type: Mapped[str] = mapped_column("section_type", Text, nullable=False)
    section_order: Mapped[int] = mapped_column("section_order", Integer, nullable=False, default=0)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    styles: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_visible: Mapped[bool | None] = mapped_column("is_visible", Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updated_at", DateTime, server_default=func.now())


class SectionTemplate(Base):
    __tablename__ = "section_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        "user_id", String, ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    section_type: Mapped[str] = mapped_column("section_type", Text, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    styles: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    thumbnail_url: Mapped[str | None] = mapped_column("thumbnail_url", Text)
    is_system: Mapped[bool | None] = mapped_column("is_system", Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())


class PersonalizationZone(Base):
    __tablename__ = "personalization_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_design_id: Mapped[int] = mapped_column(
        "page_design_id", Integer, ForeignKey("page_designs.id", ondelete="CASCADE"), nullable=False
    )
    zone_id: Mapped[str] = mapped_column("zone_id", Text, nullable=False)
    zone_name: Mapped[str] = mapped_column("zone_name", Text, nullable=False)
    zone_type: Mapped[str | None] = mapped_column("zone_type", Text, default="static")
    segment_id: Mapped[int | None] = mapped_column(
        "segment_id", Integer, ForeignKey("segments.id", ondelete="SET NULL")
    )
    content_config: Mapped[dict | None] = mapped_column("content_config", JSON, default=dict)
    fallback_content: Mapped[dict | None] = mapped_column("fallback_content", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime, server_default=func.now())


class AnonymousVisitor(Base):
    __tablename__ = "anonymous_visitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint_id: Mapped[str] = mapped_column("fingerprint_id", Text, nullable=False, unique=True)
    client_id: Mapped[int | None] = mapped_column(
        "client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE")
    )
    first_visit_at: Mapped[datetime] = mapped_column("first_visit_at", DateTime, server_default=func.now())
    last_visit_at: Mapped[datetime] = mapped_column("last_visit_at", DateTime, server_default=func.now())
    visit_count: Mapped[int | None] = mapped_column("visit_count", Integer, default=1)
    device_info: Mapped[dict | None] = mapped_column("device_info", JSON, default=dict)
    referral_source: Mapped[str | None] = mapped_column("referral_source", Text)
    behavioral_segment_id: Mapped[int | None] = mapped_column(
        "behavioral_segment_id", Integer, ForeignKey("segments.id", ondelete="SET NULL")
    )


class NavigationEvent(Base):
    __tablename__ = "navigation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visitor_id: Mapped[int] = mapped_column(
        "visitor_id", Integer, ForeignKey("anonymous_visitors.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column("event_type", Text, nullable=False)
    page_url: Mapped[str | None] = mapped_column("page_url", Text)
    element_id: Mapped[str | None] = mapped_column("element_id", Text)
    event_data: Mapped[dict | None] = mapped_column("event_data", JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
