"""Matching API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.matching import service
from app.domain.matching.schemas import MatchJobRequest, MatchResult

router = APIRouter(prefix="/matching", tags=["matching"])


@router.post("/job", response_model=list[MatchResult])
async def match_job(
    payload: MatchJobRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[MatchResult]:
    """Rank the candidate pool against one job (hard filters -> soft ranking)."""
    return await service.match_job(
        db,
        job_id=payload.job_id,
        tenant_id=tenant_id,
        include_rejected=payload.include_rejected,
        persist=payload.persist,
    )


@router.get("/pair", response_model=MatchResult)
async def match_pair(
    candidate_id: uuid.UUID,
    job_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> MatchResult:
    """Explain the match between one candidate and one job."""
    result = await service.match_pair(
        db, tenant_id=tenant_id, candidate_id=candidate_id, job_id=job_id
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate or job not found")
    return result