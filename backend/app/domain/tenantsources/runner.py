"""Performing what a workspace asked for — the machine half.

Runs in the scheduled job, never in a user request. One function, so the CLI
(`scripts/tenant_imports.py`) and the operator endpoint cannot drift apart.

Everything here is cross-tenant by nature: the runner serves whichever
workspaces have a request outstanding, so it opens the OWNER connection and
pins each import to its own tenant explicitly.
"""

from __future__ import annotations

import uuid

import httpx

from app.core.database import AdminSessionLocal, current_tenant_var
from app.core.logging import get_logger
from app.domain.atsimport import factory
from app.domain.atsimport import service as importer
from app.domain.atsimport.connectors.base import AtsExport, Credentials
from app.domain.tenantsources import service
from app.domain.tenantsources.models import TenantSource

logger = get_logger(__name__)

#: One run holds a login and a few hundred detail calls; a long queue is
#: better served by several runs than by one that times out halfway.
DEFAULT_LIMIT = 3


async def import_into(
    *, tenant_id: uuid.UUID, export: AtsExport, source: str
) -> dict:
    """Write a fetched book into one workspace."""
    current_tenant_var.set(str(tenant_id))
    async with AdminSessionLocal() as session:
        return await importer.import_export(
            session, tenant_id=tenant_id, export=export, source=source
        )


async def run_one(row: TenantSource, *, with_details: bool = True) -> dict:
    """Fetch and import one source, recording the outcome either way.

    A failure is data, not an exception: the workspace needs to see "Login
    abgelehnt" in its own settings, and the runner needs to carry on to the
    next tenant's request.
    """
    source_id, tenant_id, kind = row.id, row.tenant_id, row.kind
    try:
        username, password = service.credentials(row)
    except Exception as exc:
        async with AdminSessionLocal() as session:
            await service.record_result(
                session, source_id=source_id, ok=False, error=str(exc)
            )
        return {"source": str(source_id), "ok": False, "error": str(exc)}

    try:
        # Dispatch on the configured source, never on a name written here:
        # the runner is the scheduler's half and must not know which systems
        # exist, only that the workspace chose one the registry has.
        connector = factory.get_connector(kind)
        export = await connector.fetch(
            Credentials(username=username, secret=password),
            with_details=with_details,
        )
        summary = await import_into(
            tenant_id=tenant_id, export=export, source=connector.key
        )
    except Exception as exc:
        reason = _human_reason(exc)
        logger.warning("import failed for %s/%s: %s", tenant_id, kind, exc)
        async with AdminSessionLocal() as session:
            await service.record_result(
                session, source_id=source_id, ok=False, error=reason
            )
        return {"source": str(source_id), "ok": False, "error": reason}

    async with AdminSessionLocal() as session:
        await service.record_result(
            session, source_id=source_id, ok=True, summary=summary
        )
    return {"source": str(source_id), "ok": True, "summary": summary}


def _human_reason(exc: Exception) -> str:
    """An error a recruiter can act on, not a stack trace.

    A connector's login path raises a plain `RuntimeError` carrying its own
    wording ("… login did not return an authorization code"), because a
    connector deliberately never echoes the response body — a failed login
    form re-renders with the username in it. Matching on that text is the
    price of not logging credentials, and a test pins it so a reworded
    connector cannot silently degrade this to the generic message.
    """
    text = str(exc)
    if "login" in text.lower():
        return "Login abgelehnt — bitte Benutzername und Passwort prüfen."
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (
        400,
        401,
        403,
    ):
        return "Login abgelehnt — bitte Benutzername und Passwort prüfen."
    if isinstance(exc, httpx.TimeoutException):
        return "Zeitüberschreitung bei der Quelle — später erneut versuchen."
    if isinstance(exc, httpx.HTTPError):
        return f"Quelle nicht erreichbar ({type(exc).__name__})."
    return f"Import fehlgeschlagen ({type(exc).__name__})."


async def run_pending(*, limit: int = DEFAULT_LIMIT, with_details: bool = True) -> dict:
    """Serve the outstanding requests, oldest first."""
    async with AdminSessionLocal() as session:
        pending = await service.pending_imports(session, limit=limit)
        # Detach what the run needs; the session closes before the slow part.
        rows = [
            TenantSource(
                id=row.id,
                tenant_id=row.tenant_id,
                kind=row.kind,
                username=row.username,
                secret_encrypted=row.secret_encrypted,
            )
            for row in pending
        ]

    results = [await run_one(row, with_details=with_details) for row in rows]
    return {
        "attempted": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
    }
