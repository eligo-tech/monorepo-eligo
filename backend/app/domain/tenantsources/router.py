"""Sources API — a workspace configures its own, and asks for an import."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets
from app.core.auth import Actor, get_current_tenant, get_ingest_tenant, require_admin
from app.core.database import get_db
from app.domain.atsimport import factory
from app.domain.tenantsources import runner, service
from app.domain.tenantsources.schemas import (
    ImportRequestRead,
    TenantSourceRead,
    TenantSourceWrite,
)

router = APIRouter(prefix="/tenant-sources", tags=["tenant-sources"])


@router.get("", response_model=list[TenantSourceRead])
async def list_sources(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[TenantSourceRead]:
    """This workspace's sources. Never includes a stored secret."""
    return [
        TenantSourceRead.model_validate(service.as_read(row))
        for row in await service.list_sources(db, tenant_id=tenant_id)
    ]


@router.get("/capabilities")
async def capabilities(
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
) -> dict:
    """What the server can offer — so the UI can say WHY a form is closed.

    Without `ELIGO_SECRET_KEY` no credential can be stored, and a form that
    accepts a password and then refuses it is worse than one that explains
    itself up front.
    """
    return {
        "kinds": list(service.kinds()),
        # What each one needs, so the form asks for exactly that and the UI
        # does not have to know any system by name.
        "sources": factory.describe(),
        "secrets_configured": secrets.configured(),
    }


@router.put("/{kind}", response_model=TenantSourceRead)
async def upsert_source(
    kind: str,
    payload: TenantSourceWrite,
    actor: Actor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TenantSourceRead:
    """Connect a source, or change its login. The password is write-only."""
    try:
        row = await service.upsert_source(
            db, tenant_id=actor.tenant_id, kind=kind, data=payload
        )
    except service.UnknownSource as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.NotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return TenantSourceRead.model_validate(service.as_read(row))


@router.delete("/{kind}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    kind: str,
    actor: Actor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not await service.delete_source(db, tenant_id=actor.tenant_id, kind=kind):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not configured")


@router.post("/{kind}/import", response_model=ImportRequestRead)
async def request_import(
    kind: str,
    actor: Actor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ImportRequestRead:
    """Ask for an import.

    Writes a request; it does not import. The scheduled runner performs it —
    hundreds of outbound calls do not belong inside a user's request, and
    collection stays a logged, scheduled activity (see `service.py`).
    """
    try:
        await service.request_import(db, tenant_id=actor.tenant_id, kind=kind)
    except service.UnknownSource as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.NotConfigured as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ImportRequestRead(
        queued=True,
        detail="Import angefordert — der nächste Datenlauf holt die Daten ab.",
    )


@router.post("/run-imports")
async def run_imports(
    limit: int = Query(default=runner.DEFAULT_LIMIT, ge=1, le=20),
    with_details: bool = Query(
        default=True,
        description="Fetch per-candidate and per-manager detail (slow, but it "
        "is where skills, phone numbers and notes come from).",
    ),
    _: uuid.UUID = Depends(get_ingest_tenant),
) -> dict:
    """Perform the imports workspaces have asked for. MACHINE ONLY.

    Declared in `tests/test_operator_endpoints.py`, which attacks it with a
    valid user session and requires a 401. The reason is narrower than RULE 1
    — this reads a tenant's own ATS, not a public source — but the credential
    handling alone settles it: a password is decrypted in this call, and no
    path a recruiter can reach should ever do that.
    """
    return await runner.run_pending(limit=limit, with_details=with_details)
