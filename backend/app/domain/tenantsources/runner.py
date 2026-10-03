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
from app.domain.atsimport import service as importer
from app.domain.tenantsources import service
from app.domain.tenantsources.models import TenantSource
from app.integrations import aifind

logger = get_logger(__name__)

#: One run holds a login and a few hundred detail calls; a long queue is
#: better served by several runs than by one that times out halfway.
DEFAULT_LIMIT = 3


async def fetch_aifind(
    *, username: str, password: str, with_details: bool = True
) -> dict[str, list]:
    """Everything the source has for this account.

    The detail passes are what make the import worth running — the list calls
    carry no skills, no phone numbers and no notes — but they are also the
    slow part, so a caller can skip them.
    """
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await aifind.fetch_access_token(
            client, username=username, password=password
        )
        fetched: dict[str, list] = {}
        for entity in ("companies", "managers", "jobs", "candidates"):
            fetched[entity] = await aifind.fetch_all(
                client, token=token, operation=entity
            )

        if not with_details:
            return fetched

        detailed_managers = await aifind.fetch_manager_details(
            client, token=token, external_ids=[m.external_id for m in fetched["managers"]]
        )
        # Keep the list record for anyone the detail call lost, so a partial
        # detail pass never shrinks the import.
        by_manager = {m.external_id: m for m in fetched["managers"]}
        by_manager.update({m.external_id: m for m in detailed_managers})
        fetched["managers"] = list(by_manager.values())

        detailed_candidates = await aifind.fetch_candidate_details(
            client, token=token, external_ids=[c.external_id for c in fetched["candidates"]]
        )
        by_candidate = {c.external_id: c for c in fetched["candidates"]}
        by_candidate.update({c.external_id: c for c in detailed_candidates})
        fetched["candidates"] = list(by_candidate.values())
    return fetched


async def import_into(
    *, tenant_id: uuid.UUID, fetched: dict[str, list]
) -> dict:
    """Write a fetched book into one workspace."""
    current_tenant_var.set(str(tenant_id))
    async with AdminSessionLocal() as session:
        return await importer.import_aifind(
            session,
            tenant_id=tenant_id,
            companies=fetched["companies"],
            managers=fetched["managers"],
            jobs=fetched["jobs"],
            candidates=fetched["candidates"],
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
        fetched = await fetch_aifind(
            username=username, password=password, with_details=with_details
        )
        summary = await import_into(tenant_id=tenant_id, fetched=fetched)
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

    The login path raises a plain `RuntimeError` carrying the source's own
    wording ("aiFind login did not return an authorization code"), because the
    integration deliberately never echoes the response body — a failed
    Keycloak login re-renders the form with the username in it. Matching on
    that text is the price of not logging credentials, and it is checked by a
    test so a reworded integration cannot silently degrade this to the generic
    message.
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
