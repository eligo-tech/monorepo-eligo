"""Features API — what this workspace may switch on, and the switch itself."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_tenant, require_admin
from app.core.database import get_db
from app.domain.features import service
from app.domain.features.schemas import FeatureConsentWrite, FeatureStatus

router = APIRouter(prefix="/features", tags=["features"])


@router.get("", response_model=list[FeatureStatus])
async def list_features(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[FeatureStatus]:
    return await service.list_status(db, tenant_id=tenant_id)


@router.post("/{key}/consent", response_model=FeatureStatus)
async def accept_terms(
    key: str,
    payload: FeatureConsentWrite,
    actor: Actor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FeatureStatus:
    try:
        return await service.accept(
            db,
            tenant_id=actor.tenant_id,
            key=key,
            terms_version=payload.terms_version,
            actor_name=actor.name,
            actor_user_id=actor.user_id,
        )
    except service.UnknownFeature as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown feature {exc}") from exc
    except service.FeatureDisabled as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except service.TermsMismatch as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.delete("/{key}/consent", response_model=FeatureStatus)
async def revoke_terms(
    key: str,
    actor: Actor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FeatureStatus:
    try:
        return await service.revoke(
            db, tenant_id=actor.tenant_id, key=key, actor_name=actor.name
        )
    except service.UnknownFeature as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown feature {exc}") from exc
