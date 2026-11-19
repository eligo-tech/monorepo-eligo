"""Erasure endpoints. Thin: the work is in service.py.

Admins only — an erasure removes CVs, processes and notes for the whole
workspace and cannot be undone. REST refuses OAuth tokens (#189), so an AI
client can never reach these.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_admin_to_delete
from app.core.database import get_db
from app.domain.erasure import do_not_contact, service
from app.domain.erasure.models import ErasureRequest, TenantSuppression
from app.domain.erasure.schemas import (
    ConfirmationSent,
    DoNotContactRead,
    EraseRequest,
    ErasureRequestRead,
)
from app.domain.notices.delivery.base import EmailNotConfigured, EmailRejected

router = APIRouter(prefix="/erasure", tags=["erasure"])
#: ELI-32: "Nicht mehr kontaktieren" — any recruiter, not admins only: it
#: removes nothing, and the person on the phone is the one asking.
contact_router = APIRouter(tags=["erasure"])


def _refuse(exc: Exception) -> HTTPException:
    if isinstance(exc, service.NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": "Nicht gefunden."})
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        {"code": "name_mismatch", "message": "Der eingegebene Name stimmt nicht mit dem Datensatz überein."},
    )


async def _run(erase, db: AsyncSession, actor: Actor, body: EraseRequest, subject: str, **ids) -> ErasureRequestRead:  # noqa: ANN001
    # ELI-32: the address for the confirmation is read BEFORE the erasure
    # removes it, kept in this request's memory only, and mailed AFTER the
    # erasure is committed — a mail saying "deleted" must never precede a
    # deletion that could still roll back.
    email = name = None
    if body.send_confirmation:
        person = await do_not_contact.get_person(
            db, tenant_id=actor.tenant_id, subject=subject, person_id=next(iter(ids.values())),
        )
        if person is not None:
            email, name = person.email, person.full_name
    try:
        row = await erase(
            db, tenant_id=actor.tenant_id, confirm_name=body.confirm_name, reason=body.reason,
            requested_on=body.requested_on, actor_user_id=actor.user_id, actor_name=actor.name, **ids,
        )
    except (service.NotFound, service.NameMismatch) as exc:
        raise _refuse(exc) from exc
    await db.commit()
    read = ErasureRequestRead.model_validate(row)
    if body.send_confirmation:
        read.confirmation = await do_not_contact.send_erasure_confirmation(
            db, tenant_id=actor.tenant_id, request_id=row.id, email=email, name=name,
        )
    return read


@router.post("/candidates/{candidate_id}", response_model=ErasureRequestRead,
             status_code=status.HTTP_201_CREATED)
async def erase_candidate(
    candidate_id: uuid.UUID, body: EraseRequest,
    actor: Actor = Depends(require_admin_to_delete), db: AsyncSession = Depends(get_db),
) -> ErasureRequestRead:
    return await _run(service.erase_candidate, db, actor, body, "candidate", candidate_id=candidate_id)


@router.post("/managers/{manager_id}", response_model=ErasureRequestRead,
             status_code=status.HTTP_201_CREATED)
async def erase_manager(
    manager_id: uuid.UUID, body: EraseRequest,
    actor: Actor = Depends(require_admin_to_delete), db: AsyncSession = Depends(get_db),
) -> ErasureRequestRead:
    return await _run(service.erase_manager, db, actor, body, "manager", manager_id=manager_id)


@router.get("/requests", response_model=list[ErasureRequestRead])
async def list_requests(
    actor: Actor = Depends(require_admin_to_delete), db: AsyncSession = Depends(get_db),
) -> list[ErasureRequestRead]:
    requests = (
        await db.execute(
            select(ErasureRequest)
            .where(ErasureRequest.tenant_id == actor.tenant_id)
            .order_by(ErasureRequest.created_at.desc())
        )
    ).scalars().all()
    lifts = (
        await db.execute(
            select(TenantSuppression.request_id, TenantSuppression.lifted_at,
                   TenantSuppression.lifted_by_name)
            .where(TenantSuppression.tenant_id == actor.tenant_id,
                   TenantSuppression.lifted_at.is_not(None))
            .order_by(TenantSuppression.lifted_at)
        )
    ).all()
    by_request: dict[uuid.UUID, list] = {}
    for request_id, at, by in lifts:
        by_request.setdefault(request_id, []).append((at, by))
    out = []
    for r in requests:
        row = ErasureRequestRead.model_validate(r)
        done = by_request.get(r.id, [])
        if done:
            row.lifted = len(done)
            row.last_lifted_at, row.last_lifted_by = done[-1]
        out.append(row)
    return out


# --- "Nicht mehr kontaktieren" (ELI-32) -------------------------------------
#
# Marking happens with the note (`do_not_contact` on the interaction), so the
# request and its words are one row. Undoing it and confirming it to the
# person are the two acts left, each a click by a named person.

_KINDS = {"managers": "manager", "candidates": "candidate"}


async def _person(db: AsyncSession, actor: Actor, kind: str, person_id: uuid.UUID):  # noqa: ANN202
    subject = _KINDS.get(kind)
    person = None if subject is None else await do_not_contact.get_person(
        db, tenant_id=actor.tenant_id, subject=subject, person_id=person_id,
    )
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return subject, person


@contact_router.delete("/{kind}/{person_id}/do-not-contact", response_model=DoNotContactRead)
async def lift_do_not_contact(
    kind: str, person_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor), db: AsyncSession = Depends(get_db),
) -> DoNotContactRead:
    """"Wieder kontaktierbar"."""
    subject, person = await _person(db, actor, kind, person_id)
    await do_not_contact.lift(db, tenant_id=actor.tenant_id, subject=subject, person=person)
    await db.commit()
    return DoNotContactRead(subject_type=subject, id=person.id, do_not_contact_at=None, do_not_contact_reason=None)


@contact_router.post("/{kind}/{person_id}/do-not-contact/confirmation", response_model=ConfirmationSent)
async def confirm_do_not_contact(
    kind: str, person_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor), db: AsyncSession = Depends(get_db),
) -> ConfirmationSent:
    """"Bestätigung senden": one mail to the marked person, on this click."""
    subject, person = await _person(db, actor, kind, person_id)
    try:
        await do_not_contact.send_do_not_contact_confirmation(
            db, tenant_id=actor.tenant_id, subject=subject, person=person,
        )
    except do_not_contact.NotMarked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "not_marked", "message": "Nicht als „Nicht mehr kontaktieren“ markiert."}) from exc
    except do_not_contact.NoAddress as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "no_email", "message": "Keine E-Mail-Adresse hinterlegt."}) from exc
    except EmailNotConfigured as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, {"code": "email_not_configured", "message": "E-Mail-Versand ist nicht eingerichtet."}) from exc
    except EmailRejected as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, {"code": "email_rejected", "message": "Der E-Mail-Dienst hat die Nachricht abgelehnt."}) from exc
    return ConfirmationSent()
