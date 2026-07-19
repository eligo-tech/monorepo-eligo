"""Candidates API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.candidates import service
from app.domain.candidates.schemas import CandidateCreate, CandidateRead
from app.domain.documents import service as documents_service

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("", response_model=list[CandidateRead])
async def list_candidates(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[CandidateRead]:
    rows = await service.list_candidates(db, tenant_id=tenant_id, limit=limit)
    return [CandidateRead.model_validate(r) for r in rows]


@router.get("/{candidate_id}", response_model=CandidateRead)
async def get_candidate(
    candidate_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CandidateRead:
    row = await service.get_candidate(
        db, tenant_id=tenant_id, candidate_id=candidate_id
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")
    return CandidateRead.model_validate(row)


@router.get("/{candidate_id}/cv")
async def get_candidate_cv(
    candidate_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Stream the original uploaded CV (the evidence behind the parsed record)."""
    doc = await documents_service.get_latest_document(
        db, tenant_id=tenant_id, candidate_id=candidate_id
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no original CV on file")
    return Response(
        content=doc.content,
        media_type=doc.content_type,
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


@router.post("", response_model=CandidateRead, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    payload: CandidateCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CandidateRead:
    payload.tenant_id = tenant_id  # force the authenticated tenant
    row = await service.create_candidate(db, data=payload)
    return CandidateRead.model_validate(row)