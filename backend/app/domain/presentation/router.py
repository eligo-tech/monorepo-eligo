"""Cover sheet + workspace branding API (ELI-20) — thin.

Clerk-authenticated, tenant-scoped; not an operator route. Reading the
branding and downloading a cover sheet is everyone's work; changing the
workspace's CI is an admin's.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_admin, require_admin_to_delete
from app.core.database import get_db
from app.domain.presentation import service
from app.domain.presentation.schemas import (
    BrandingRead,
    BrandingUpdate,
    CoverSheetPreview,
    CoverSheetVariant,
)

router = APIRouter(tags=["presentation"])

_USER_ID = re.compile(r"^user_[A-Za-z0-9]+$")


# ── Branding ──────────────────────────────────────────────────────────────


@router.get("/branding", response_model=BrandingRead)
async def get_branding(
    actor: Actor = Depends(get_current_actor), db: AsyncSession = Depends(get_db)
) -> BrandingRead:
    return service.branding_read(await service.get_branding(db, tenant_id=actor.tenant_id))


@router.put("/branding", response_model=BrandingRead)
async def save_branding(
    payload: BrandingUpdate,
    actor: Actor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BrandingRead:
    row = await service.save_branding(db, tenant_id=actor.tenant_id, data=payload, editor=actor.name)
    return service.branding_read(row)


@router.get("/branding/logo")
async def get_logo(
    actor: Actor = Depends(get_current_actor), db: AsyncSession = Depends(get_db)
) -> Response:
    row = await service.get_branding(db, tenant_id=actor.tenant_id)
    if row is None or row.logo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no logo")
    return Response(content=row.logo, media_type=row.logo_content_type or "image/png")


@router.put("/branding/logo", response_model=BrandingRead)
async def upload_logo(
    file: UploadFile = File(...),
    actor: Actor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BrandingRead:
    content = await file.read(service.LOGO_MAX_BYTES + 1)
    try:
        row = await service.set_logo(
            db,
            tenant_id=actor.tenant_id,
            content=content,
            content_type=file.content_type,
            editor=actor.name,
        )
    except service.InvalidLogo as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return service.branding_read(row)


@router.delete("/branding/logo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_logo(
    actor: Actor = Depends(require_admin_to_delete),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await service.clear_logo(db, tenant_id=actor.tenant_id, editor=actor.name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Cover sheet ───────────────────────────────────────────────────────────


def _contact_name(given: str | None, actor: Actor) -> str | None:
    """The browser knows the signed-in person's name from Clerk; the token
    usually does not. A bare Clerk id is never printed for a client."""
    if given and given.strip():
        return given.strip()
    return None if _USER_ID.match(actor.name) else actor.name


async def _compose(
    db: AsyncSession,
    actor: Actor,
    candidate_id: uuid.UUID,
    variant: CoverSheetVariant,
    application_id: uuid.UUID | None,
    position: str | None,
    contact_name: str | None,
    contact_email: str | None,
    contact_phone: str | None,
) -> service.Composition:
    try:
        return await service.compose(
            db,
            tenant_id=actor.tenant_id,
            candidate_id=candidate_id,
            variant=variant,
            application_id=application_id,
            position=position,
            contact_name=_contact_name(contact_name, actor),
            contact_email=contact_email,
            contact_phone=contact_phone,
        )
    except service.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def _ascii_filename(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", folded).strip("_") or "Kandidatenprofil"


@router.get("/candidates/{candidate_id}/cover-sheet/preview", response_model=CoverSheetPreview)
async def preview_cover_sheet(
    candidate_id: uuid.UUID,
    variant: CoverSheetVariant = Query(default=CoverSheetVariant.COVER),
    application_id: uuid.UUID | None = Query(default=None),
    position: str | None = Query(default=None, max_length=200),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> CoverSheetPreview:
    """What the PDF will hold: empty sections, files left out, unset CI."""
    composition = await _compose(
        db, actor, candidate_id, variant, application_id, position, None, None, None
    )
    return composition.preview


@router.get("/candidates/{candidate_id}/cover-sheet")
async def download_cover_sheet(
    candidate_id: uuid.UUID,
    variant: CoverSheetVariant = Query(default=CoverSheetVariant.COVER),
    application_id: uuid.UUID | None = Query(default=None),
    position: str | None = Query(default=None, max_length=200),
    contact_name: str | None = Query(default=None, max_length=200),
    contact_email: str | None = Query(default=None, max_length=320),
    contact_phone: str | None = Query(default=None, max_length=50),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The Kandidatenprofil as PDF, with the files the variant asks for.

    Leaves a READ receipt on the candidate: this is the moment their data
    goes to a client.
    """
    composition = await _compose(
        db, actor, candidate_id, variant, application_id, position,
        contact_name, contact_email, contact_phone,
    )
    pdf = service.assemble(composition)
    await service.record_disclosure(
        db,
        tenant_id=actor.tenant_id,
        candidate_id=candidate_id,
        variant=variant,
        application_id=application_id,
        document_ids=[d.id for d in composition.documents],
    )
    title = composition.sheet.title
    disposition = (
        f'attachment; filename="{_ascii_filename(title)}.pdf"; '
        f"filename*=UTF-8''{quote(title + '.pdf')}"
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition, "Cache-Control": "no-store"},
    )
