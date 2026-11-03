"""Async SQLAlchemy 2.0 engine, session factory, and declarative ``Base``.

The engine is driven by ``settings.database_url``. The default (SQLite +
aiosqlite) means the app boots with no external services; switching to
``postgresql+asyncpg://...`` makes Postgres the system-of-record without any
code change.
"""

from __future__ import annotations

import ssl
import uuid
from collections.abc import AsyncGenerator, Sequence
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


class TenantIsolationNotEnforced(RuntimeError):
    """The database cannot keep one workspace's rows away from another's."""


#: Which tables must be policed, read from the DATABASE rather than from the
#: models on purpose: `create_all` will happily add a table no migration ever
#: saw, and that table — the one nobody remembered to write a policy for — is
#: precisely what this check exists to catch. Asking the model registry would
#: only ever confirm what the code already believes.
#:
#: Three properties, because any two without the third are worthless: the
#: policy exists, RLS is enabled, and it is FORCEd (without FORCE the table
#: owner silently bypasses every policy on it).
#: Who the runtime role is, and whether RLS applies to it at all. A SUPERUSER
#: skips every policy whatever `rolbypassrls` says, so both count as bypass —
#: checking `rolbypassrls` alone passed a superuser as "NOBYPASSRLS"
#: (found 2026-11-01 by running the CI gate as the owner).
_ROLE_BYPASS_QUERY = (
    "SELECT current_user, "
    "(SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user)"
)

_TENANT_TABLE_AUDIT = """
SELECT c.relname,
       c.relrowsecurity,
       c.relforcerowsecurity,
       EXISTS (SELECT 1 FROM pg_policies p
                WHERE p.schemaname = n.nspname
                  AND p.tablename = c.relname
                  AND p.policyname = 'tenant_isolation')
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public'
   AND c.relkind = 'r'
   AND EXISTS (SELECT 1 FROM information_schema.columns ic
                WHERE ic.table_schema = n.nspname
                  AND ic.table_name = c.relname
                  AND ic.column_name = 'tenant_id')
 ORDER BY c.relname
"""


def isolation_problems(
    user: str,
    bypasses: bool,
    tables: Sequence[tuple[str, bool, bool, bool]],
) -> list[str]:
    """Everything wrong with this database's tenant isolation, in words.

    Pure, and separated from the probe for the usual reason: the part that can
    be wrong in a way anyone notices is the judgement, not the two SELECTs, and
    a judgement that needs a live Postgres to exercise is a judgement nobody
    tests. Returns an empty list when isolation is sound.

    Each `tables` row is `(name, rls_enabled, rls_forced, has_policy)`.
    """
    problems: list[str] = []
    if bypasses:
        problems.append(
            f"runtime DB role {user!r} has BYPASSRLS or is a superuser, so no policy applies to it"
        )
    for name, enabled, forced, has_policy in tables:
        missing = [
            label
            for label, ok in (
                ("a tenant_isolation policy", has_policy),
                ("ROW LEVEL SECURITY", enabled),
                ("FORCE ROW LEVEL SECURITY", forced),
            )
            if not ok
        ]
        if missing:
            problems.append(f"{name} is missing {' and '.join(missing)}")
    return problems


#: Startup probe: attempts, and the pause between them. A database still
#: waking up at boot gets a few seconds; one that never answers does not get
#: the benefit of the doubt.
_PROBE_ATTEMPTS = 3
_PROBE_RETRY_SECONDS = 2.0


async def assert_runtime_rls_enforced() -> None:
    """Refuse to start when the database cannot enforce tenant isolation.

    Fail-closed isolation needs two things, and both are checked here because
    either one alone buys nothing:

    * the app connects as a **NOBYPASSRLS** role, so an un-pinned query returns
      zero rows instead of every tenant's;
    * every table carrying a `tenant_id` actually has the `tenant_isolation`
      policy, with RLS enabled **and** FORCEd.

    This used to log an error and carry on serving, which was the wrong stance.
    The failure is invisible from outside: nothing errors, the app simply hands
    one workspace another's data, so the only moment anyone would notice is
    after the fact. `assert_auth_configured` already refuses to boot for the
    neighbouring fail-open; this is the same argument.

    A no-op off Postgres or with auth disabled — the SQLite demo and the test
    suite are single-tenant. A probe that cannot RUN is retried
    (`_PROBE_ATTEMPTS`) and then refuses too: it used to be a warning, so
    "I could not check" was served past as if it were "I checked" (review
    2026-10-31 #5). A database that is merely waking up gets the retries.
    """
    if not settings.is_postgres or not settings.auth_enabled:
        return
    from sqlalchemy import text

    from app.core.logging import get_logger

    log = get_logger(__name__)

    import asyncio

    # "I could not check" used to be logged and served past. In production
    # that is the one answer this guard must never accept: retry briefly (a
    # database waking up at boot), then refuse like any other failed check.
    # If the database cannot be reached the app cannot serve anyway; what
    # this prevents is serving after a probe that failed for any other
    # reason — a revoked catalog grant, a wrong role — unexamined.
    last: Exception | None = None
    for attempt in range(_PROBE_ATTEMPTS):
        try:
            async with engine.connect() as conn:
                user, bypasses = (await conn.execute(text(_ROLE_BYPASS_QUERY))).one()
                tables = (await conn.execute(text(_TENANT_TABLE_AUDIT))).all()
            break
        except Exception as exc:  # noqa: BLE001 — any failure to check is a failed check
            last = exc
            log.warning(
                "could not verify RLS enforcement (attempt %d/%d): %s",
                attempt + 1, _PROBE_ATTEMPTS, exc,
            )
            if attempt + 1 < _PROBE_ATTEMPTS:
                await asyncio.sleep(_PROBE_RETRY_SECONDS)
    else:
        detail = f"could not verify isolation after {_PROBE_ATTEMPTS} attempts: {last}"
        if settings.allow_insecure_rls:
            log.error("SECURITY: serving with tenant isolation UNVERIFIED — %s. "
                      "Allowed only by ELIGO_ALLOW_INSECURE_RLS.", detail)
            return
        raise TenantIsolationNotEnforced(f"refusing to start: {detail}")

    problems = isolation_problems(user, bypasses, tables)

    if not problems:
        log.info(
            "RLS enforced: runtime role %r is NOBYPASSRLS and all %d tenant "
            "tables are policed (fail-closed).",
            user,
            len(tables),
        )
        return

    detail = "; ".join(problems)
    if settings.allow_insecure_rls:
        log.error(
            "SECURITY: serving with tenant isolation NOT enforced — %s. "
            "Allowed only by ELIGO_ALLOW_INSECURE_RLS.",
            detail,
        )
        return

    raise TenantIsolationNotEnforced(
        "refusing to start: the database cannot enforce tenant isolation — "
        f"{detail}. Point ELIGO_DATABASE_URL at the NOBYPASSRLS app role and "
        "ELIGO_ADMIN_DATABASE_URL at the owner, and give every tenant-scoped "
        "table a tenant_isolation policy (migrations 0003 and 0005 show the "
        "shape; DEPLOY.md covers the roles). ELIGO_ALLOW_INSECURE_RLS=true "
        "overrides this and must never be set in production."
    )