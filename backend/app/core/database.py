"""Async SQLAlchemy 2.0 engine, session factory, and declarative ``Base``.

The engine is driven by ``settings.database_url``. The default (SQLite +
aiosqlite) means the app boots with no external services; switching to
``postgresql+asyncpg://...`` makes Postgres the system-of-record without any
code change.
"""

from __future__ import annotations

import ssl
import uuid
from collections.abc import AsyncGenerator
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import settings

# The tenant for the current request. Set by auth.get_current_tenant; read by the
# after_begin listener so every transaction (incl. those opened after a
# mid-request commit) re-pins the Postgres GUC that RLS policies isolate on.
current_tenant_var: ContextVar[str | None] = ContextVar("current_tenant", default=None)


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


@event.listens_for(Session, "after_begin")
def _pin_tenant_for_rls(session: Session, transaction, connection) -> None:  # type: ignore[no-untyped-def]
    """At the start of every transaction, set `app.current_tenant` so Postgres
    RLS scopes the transaction to the request's tenant. Postgres-only; a UUID is
    validated before it's inlined (SET LOCAL takes no bind params)."""
    if connection.dialect.name != "postgresql":
        return
    raw = current_tenant_var.get()
    if not raw:
        return
    try:
        tid = str(uuid.UUID(raw))  # validate — never inline untrusted text
    except (ValueError, TypeError):
        return
    # Drop from the (possibly BYPASSRLS) connection role to the app role so RLS
    # actually applies, then pin the tenant. Both are transaction-local.
    role = settings.db_app_role
    if role and role.replace("_", "").isalnum():  # trusted config; keep it identifier-safe
        connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
    connection.exec_driver_sql(f"SET LOCAL app.current_tenant = '{tid}'")


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