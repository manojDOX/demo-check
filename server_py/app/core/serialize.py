"""snake_case -> camelCase serialization for SQLAlchemy model instances.

The frontend's `shared/schema.ts` (Drizzle) exposes camelCase JS field names
(e.g. `projectId`, `isActive`, `createdAt`) that map 1:1 onto our SQLAlchemy
models' snake_case Python attributes (`project_id`, `is_active`, `created_at`).
Every module's route handlers should return `to_camel(instance)` (or a list of
them) instead of hand-building dicts, to guarantee the exact same JSON shape
the existing frontend already expects.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def to_camel(instance: Any) -> dict:
    """Convert a SQLAlchemy declarative model instance into a camelCase dict."""
    mapper = instance.__mapper__
    return {
        _snake_to_camel(col.key): _serialize_value(getattr(instance, col.key))
        for col in mapper.column_attrs
    }


def to_camel_list(instances: list) -> list[dict]:
    return [to_camel(i) for i in instances]
