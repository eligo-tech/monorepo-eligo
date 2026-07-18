"""Async SQLAlchemy 2.0 engine, session factory, and declarative ``Base``.

The engine is driven by ``settings.database_url``. The default (SQLite +
aiosqlite) means the app boots with no external services; switching to
``postgresql+asyncpg://...`` makes Postgres the system-of-record without any
code change.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base for every ORM model in the platform."""


def _connect_args() -> dict[str, object]:
    """Driver-specific connection args.

    * SQLite: allow cross-thread use with the async pool.
    * asyncpg (Supabase / managed Postgres): enable TLS when ``ELIGO_DB_SSL`` is
      set. If connecting through Supabase's transaction pooler (port 6543),
      prepared-statement caching must also be disabled — handled here.
    """
    if settings.is_sqlite:
        return {"check_same_thread": False}
    args: dict[str, object] = {}
    if settings.is_postgres:
        if settings.db_ssl:
            args["ssl"] = _ssl_context()
        # pgbouncer transaction pooler is incompatible with prepared statements.
        if ":6543" in settings.database_url:
            args["statement_cache_size"] = 0
    return args


def _ssl_context() -> ssl.SSLContext:
    """TLS context for asyncpg. Pins the Supabase CA when provided; otherwise
    falls back to an unverified context for dev (``ELIGO_DB_SSL_VERIFY=false``)."""
    if settings.db_ssl_root_cert:
        return ssl.create_default_context(cafile=settings.db_ssl_root_cert)
    ctx = ssl.create_default_context()
    if not settings.db_ssl_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    future=True,
    pool_pre_ping=settings.is_postgres,  # recycle dropped pooled connections
    connect_args=_connect_args(),
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create all tables. Scaffold convenience — replace with Alembic in prod.

    Importing the model registry here guarantees every table is registered on
    ``Base.metadata`` before ``create_all`` runs.
    """
    from app.domain import registry  # noqa: F401  (side-effect: model imports)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)