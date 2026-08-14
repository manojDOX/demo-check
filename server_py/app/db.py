from collections.abc import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


# libpq/psycopg2-style query params (e.g. Replit's managed Postgres DATABASE_URL includes
# `sslmode=require`) aren't understood by asyncpg's connect() — asyncpg takes a plain `ssl`
# connect_args kwarg instead. Strip them from the URL and translate into connect_args.
_SSLMODE_REQUIRES_TLS = {"require", "verify-ca", "verify-full", "prefer", "allow"}


def _to_asyncpg_url(url: str) -> tuple[str, dict]:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parsed = make_url(url)
    query = dict(parsed.query)
    connect_args: dict = {}

    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)  # psycopg2-only, asyncpg doesn't accept it either
    if sslmode in _SSLMODE_REQUIRES_TLS:
        connect_args["ssl"] = True
    elif sslmode == "disable":
        connect_args["ssl"] = False

    return parsed.set(query=query).render_as_string(hide_password=False), connect_args


settings = get_settings()
_db_url, _connect_args = _to_asyncpg_url(settings.DATABASE_URL)
engine = create_async_engine(_db_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
