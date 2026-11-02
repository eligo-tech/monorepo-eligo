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

from app.core.auth import Actor, get_current_actor
from app.core.database import get_db
from app.domain.erasure import service
from app.domain.erasure.models import ErasureRequest
from app.domain.erasure.schemas import EraseRequest, ErasureRequestRead

router = APIRouter(prefix="/erasure", tags=["erasure"])


async def _admin(actor: Actor = Depends(get_current_actor)) -> Actor:
    if not actor.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Nur Administratoren dürfen Personen löschen."
            + ("" if actor.role_known else " (Das Token enthält keine Rolle.)"),
        )
    return actor


def _refuse(exc: Exception) -> HTTPException:
    if isinstance(exc, service.NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": "Nicht gefunden."})
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        {"code": "name_mismatch", "message": "Der eingegebene Name stimmt nicht mit dem Datensatz überein."},
    )


async def _run(erase, db: AsyncSession, actor: Actor, body: EraseRequest, **ids) -> ErasureRequestRead:  # noqa: ANN001
    try:
        row = await erase(
            db, tenant_id=actor.tenant_id, confirm_name=body.confirm_name, reason=body.reason,
            requested_on=body.requested_on, actor_user_id=actor.user_id, actor_name=actor.name, **ids,
        )
    except (service.NotFound, service.NameMismatch) as exc:
        raise _refuse(exc) from exc
    await db.commit()
    return ErasureRequestRead.model_validate(row)


@router.post("/candidates/{candidate_id}", response_model=ErasureRequestRead,
             status_code=status.HTTP_201_CREATED)
async def erase_candidate(
    candidate_id: uuid.UUID, body: EraseRequest,
    actor: Actor = Depends(_admin), db: AsyncSession = Depends(get_db),
) -> ErasureRequestRead:
    return await _run(service.erase_candidate, db, actor, body, candidate_id=candidate_id)


@router.post("/managers/{manager_id}", response_model=ErasureRequestRead,
             status_code=status.HTTP_201_CREATED)
async def erase_manager(
    manager_id: uuid.UUID, body: EraseRequest,
    actor: Actor = Depends(_admin), db: AsyncSession = Depends(get_db),
) -> ErasureRequestRead:
    return await _run(service.erase_manager, db, actor, body, manager_id=manager_id)


@router.get("/requests", response_model=list[ErasureRequestRead])
async def list_requests(
    actor: Actor = Depends(_admin), db: AsyncSession = Depends(get_db),
) -> list[ErasureRequestRead]:
    rows = await db.execute(
        select(ErasureRequest)
        .where(ErasureRequest.tenant_id == actor.tenant_id)
        .order_by(ErasureRequest.created_at.desc())
    )
    return [ErasureRequestRead.model_validate(r) for r in rows.scalars()]
