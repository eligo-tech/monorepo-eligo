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


def _connect_args(url: str) -> dict[str, object]:
    """Driver-specific connection args for a given URL.

    * SQLite: allow cross-thread use with the async pool.
    * asyncpg (Supabase / managed Postgres): enable TLS when ``ELIGO_DB_SSL`` is
      set. If connecting through Supabase's transaction pooler (port 6543),
      prepared-statement caching must also be disabled — handled here.
    """
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    args: dict[str, object] = {}
    if "postgres" in url:
        if settings.db_ssl:
            args["ssl"] = _ssl_context()
        # pgbouncer transaction pooler is incompatible with prepared statements.
        if ":6543" in url:
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


def _make_engine(url: str):
    return create_async_engine(
        url,
        echo=settings.db_echo,
        future=True,
        pool_pre_ping="postgres" in url,  # recycle dropped pooled connections
        connect_args=_connect_args(url),
    )


# Two engines, one purpose each:
# * ``engine`` carries all request traffic. In production its URL points at the
#   NOBYPASSRLS app role, so RLS is enforced at the connection — an un-pinned
#   query returns zero rows (fail-closed), independent of any app-code mistake.
# * ``admin_engine`` is for DDL (migrations, create_all) and cross-tenant admin
#   scripts, which need an owner/superuser (BYPASSRLS). Never used for requests.
# In single-connection dev (or SQLite) both resolve to the same URL.
engine = _make_engine(settings.database_url)
admin_engine = _make_engine(settings.admin_url)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Sessions for admin/DDL/cross-tenant work — bound to the owner connection.
AdminSessionLocal = async_sessionmaker(
    bind=admin_engine,
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
    ``Base.metadata`` before ``create_all`` runs. Runs on the ADMIN connection:
    the runtime app role is not the table owner and (under FORCE RLS) could not
    create or alter tables anyway.
    """
    from app.domain import registry  # noqa: F401  (side-effect: model imports)

    async with admin_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def assert_runtime_rls_enforced() -> None:
    """Warn loudly if the RUNTIME connection can bypass Row-Level Security.

    Fail-closed tenant isolation requires the app to connect as a NOBYPASSRLS
    role: only then does an un-pinned query return zero rows instead of every
    tenant's. This is a no-op off Postgres or with auth disabled (single-tenant
    demo). It never blocks startup — a transient probe failure must not take the
    service down — but a BYPASSRLS runtime role is logged as a SECURITY error.
    """
    if not settings.is_postgres or not settings.auth_enabled:
        return
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            user, bypasses = (
                await conn.execute(
                    text(
                        "SELECT current_user, "
                        "(SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"
                    )
                )
            ).one()
    except Exception as exc:  # pragma: no cover - network/permission dependent
        from app.core.logging import get_logger

        get_logger(__name__).warning("could not verify RLS enforcement: %s", exc)
        return

    from app.core.logging import get_logger

    log = get_logger(__name__)
    if bypasses:
        log.error(
            "SECURITY: runtime DB role %r has BYPASSRLS — tenant isolation is NOT "
            "enforced at the database layer (fail-OPEN). Point ELIGO_DATABASE_URL "
            "at the NOBYPASSRLS app role and ELIGO_ADMIN_DATABASE_URL at the owner. "
            "See DEPLOY.md.",
            user,
        )
    else:
        log.info("RLS enforced: runtime role %r is NOBYPASSRLS (fail-closed).", user)