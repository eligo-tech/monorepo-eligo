"""Configuring a workspace's sources, and running what it asked for.

**The asking and the doing are deliberately separate.**

A recruiter pressing "Import anfordern" writes one timestamp to their own row
— a tenant-scoped database write, no outbound call. A scheduled job then picks
the request up and performs the import. Three reasons, in order of weight:

1. An ATS import is hundreds of outbound calls (one per candidate for the
   detail pass). Holding a request open across that gives no retry, no
   backpressure and a timeout that cannot be told apart from a failure — the
   same deviation ARCHITECTURE.md already names for `/hub/ingest`, and there
   is no reason to repeat it in a new path.
2. Collection stays a *scheduled, logged* activity (GDPR Art. 30 / SOC 2 CC7)
   with an answer to "when was this data taken and on whose instruction".
3. It keeps the user-facing API free of credentials in flight: the password is
   decrypted in the job process, never in a request handler.

This is NOT the RULE 1 case, and the difference matters. RULE 1 forbids a
user-triggered crawl of a PUBLIC source into the shared corpus — N tenants
hammering one free API for facts already held. Here a workspace imports its
own book from its own ATS account with its own credential, into its own
tenant. Same machinery, different reason: engineering, not policy.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets
from app.domain.atsimport import factory
from app.core.logging import get_logger
from app.domain.tenantsources.models import TenantSource
from app.domain.tenantsources.schemas import TenantSourceWrite

logger = get_logger(__name__)

#: Sources a workspace can configure for itself today.
def kinds() -> tuple[str, ...]:
    """Which sources a workspace may store a credential for.

    The PULL half of the registry: a CSV has no login, is never fetched on a
    schedule, and must not be configurable here. Deliberately a call, not a
    constant — the list IS the registry, and a second copy of it is how
    "which systems do we support" starts having two answers.
    """
    return tuple(factory.pull_sources())
STATUSES: tuple[str, ...] = ("active", "disabled")


class UnknownSource(ValueError):
    """A kind nothing can import."""


class NotConfigured(RuntimeError):
    """The source cannot run — no credential, or no key to read it with."""


def as_read(row: TenantSource) -> dict:
    """The row as the API returns it: everything except the secret."""
    return {
        "id": row.id,
        "kind": row.kind,
        "label": row.label,
        "username": row.username,
        "status": row.status,
        "has_secret": bool(row.secret_encrypted),
        "import_requested_at": row.import_requested_at,
        "last_run_at": row.last_run_at,
        "last_result": row.last_result or {},
        "last_error": row.last_error,
    }


async def list_sources(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[TenantSource]:
    rows = await session.execute(
        select(TenantSource)
        .where(TenantSource.tenant_id == tenant_id)
        .order_by(TenantSource.kind)
    )
    return list(rows.scalars())


async def get_source(
    session: AsyncSession, *, tenant_id: uuid.UUID, kind: str
) -> TenantSource | None:
    return await session.scalar(
        select(TenantSource).where(
            TenantSource.tenant_id == tenant_id, TenantSource.kind == kind
        )
    )


async def upsert_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    kind: str,
    data: TenantSourceWrite,
) -> TenantSource:
    """Store or update one source's configuration.

    The password is encrypted before it reaches the session, so a value in the
    clear never exists in a transaction, a query log or a failed-rollback.
    """
    if kind not in kinds():
        raise UnknownSource(f"unknown source {kind!r}")
    if data.status is not None and data.status not in STATUSES:
        raise UnknownSource(f"unknown status {data.status!r}")
    if data.secret is not None and not secrets.configured():
        raise NotConfigured(
            "Zugangsdaten können nicht gespeichert werden: ELIGO_SECRET_KEY "
            "ist auf dem Server nicht gesetzt."
        )

    row = await get_source(session, tenant_id=tenant_id, kind=kind)
    if row is None:
        row = TenantSource(tenant_id=tenant_id, kind=kind, username=data.username)
        session.add(row)
    row.username = data.username
    if data.label is not None:
        row.label = data.label
    if data.status is not None:
        row.status = data.status
    if data.secret:
        row.secret_encrypted = secrets.encrypt(data.secret)
    await session.commit()
    await session.refresh(row)
    return row


async def delete_source(
    session: AsyncSession, *, tenant_id: uuid.UUID, kind: str
) -> bool:
    row = await get_source(session, tenant_id=tenant_id, kind=kind)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def request_import(
    session: AsyncSession, *, tenant_id: uuid.UUID, kind: str
) -> TenantSource:
    """Queue an import. Idempotent: asking twice before the run is one import."""
    row = await get_source(session, tenant_id=tenant_id, kind=kind)
    if row is None:
        raise UnknownSource(f"{kind} ist für diesen Workspace nicht eingerichtet")
    if not row.secret_encrypted:
        raise NotConfigured("Für diese Quelle sind keine Zugangsdaten hinterlegt.")
    if row.status != "active":
        raise NotConfigured("Diese Quelle ist pausiert.")
    if row.import_requested_at is None:
        row.import_requested_at = dt.datetime.now(dt.UTC)
        await session.commit()
        await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# The machine half. These run on the OWNER connection from the scheduled job:
# they cross tenants by design and must never be reachable from a user request.
# ---------------------------------------------------------------------------


async def pending_imports(
    session: AsyncSession, *, limit: int = 5
) -> list[TenantSource]:
    """Sources whose workspace has asked for an import, oldest request first."""
    rows = await session.execute(
        select(TenantSource)
        .where(
            TenantSource.import_requested_at.is_not(None),
            TenantSource.status == "active",
            TenantSource.secret_encrypted.is_not(None),
        )
        .order_by(TenantSource.import_requested_at)
        .limit(limit)
    )
    return list(rows.scalars())


def credentials(row: TenantSource) -> tuple[str, str]:
    """The username and password for a run. Raises if the key is gone."""
    if not row.secret_encrypted:
        raise NotConfigured("no credential stored")
    try:
        return row.username, secrets.decrypt(row.secret_encrypted)
    except secrets.SecretsNotConfigured:
        raise
    except Exception as exc:
        # A key rotation invalidates every stored secret; say so plainly
        # rather than letting the import fail as "login refused".
        raise NotConfigured(
            "Zugangsdaten konnten nicht entschlüsselt werden — wurde der "
            f"Server-Schlüssel gewechselt? ({type(exc).__name__})"
        ) from exc


async def record_result(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    ok: bool,
    summary: dict | None = None,
    error: str | None = None,
) -> None:
    """Close out a run: clear the request, keep what happened.

    The request is cleared on failure too. A source that failed should not
    retry forever on its own — the workspace sees the error and decides,
    which is the same human-in-the-loop stance the rest of the system takes.
    """
    row = await session.get(TenantSource, source_id)
    if row is None:  # deleted mid-run
        return
    row.import_requested_at = None
    row.last_run_at = dt.datetime.now(dt.UTC)
    row.last_result = summary or {}
    row.last_error = None if ok else (error or "unbekannter Fehler")
    await session.commit()
    logger.info(
        "tenant source %s (%s) run: %s", row.kind, row.tenant_id, "ok" if ok else "failed"
    )
