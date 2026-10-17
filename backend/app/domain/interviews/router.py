"""Interviews API — thin: auth, the call, and status codes.

The feature gate and the candidate-consent gate live in the service.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor
from app.core.database import get_db
from app.domain.interviews import service
from app.domain.interviews.models import Interview
from app.domain.interviews.schemas import (
    AnswerWrite,
    CandidateConsentWrite,
    InterviewRead,
    InterviewStart,
)
from app.domain.interviews.script import CANDIDATE_NOTICE, CANDIDATE_NOTICE_VERSION

router = APIRouter(prefix="/interviews", tags=["interviews"])


def _read(interview: Interview) -> InterviewRead:
    out = InterviewRead.model_validate(interview)
    if interview.status == "awaiting_consent":
        out.notice = CANDIDATE_NOTICE
        out.notice_version = CANDIDATE_NOTICE_VERSION
    out.next_question = service.next_question(interview)
    return out


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.FeatureDisabled):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, service.NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


_ERRORS = (service.FeatureDisabled, service.NotFound, service.InvalidState)


@router.post("", response_model=InterviewRead, status_code=status.HTTP_201_CREATED)
async def start_interview(
    payload: InterviewStart,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> InterviewRead:
    try:
        row = await service.start(
            db, tenant_id=actor.tenant_id, candidate_id=payload.candidate_id,
            started_by=actor.name,
        )
    except _ERRORS as exc:
        raise _http(exc) from exc
    return _read(row)


@router.get("", response_model=list[InterviewRead])
async def list_interviews(
    candidate_id: uuid.UUID = Query(...),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[InterviewRead]:
    rows = await service.list_for_candidate(
        db, tenant_id=actor.tenant_id, candidate_id=candidate_id
    )
    return [_read(r) for r in rows]


@router.get("/{interview_id}", response_model=InterviewRead)
async def get_interview(
    interview_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> InterviewRead:
    try:
        row = await service.get_interview(
            db, tenant_id=actor.tenant_id, interview_id=interview_id
        )
    except _ERRORS as exc:
        raise _http(exc) from exc
    return _read(row)


@router.post("/{interview_id}/consent", response_model=InterviewRead)
async def record_consent(
    interview_id: uuid.UUID,
    payload: CandidateConsentWrite,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> InterviewRead:
    try:
        row = await service.record_consent(
            db, tenant_id=actor.tenant_id, interview_id=interview_id,
            notice_version=payload.notice_version, confirmed=payload.confirmed,
            recorded_by=actor.name,
        )
    except _ERRORS as exc:
        raise _http(exc) from exc
    return _read(row)


@router.post("/{interview_id}/answers", response_model=InterviewRead)
async def submit_answer(
    interview_id: uuid.UUID,
    payload: AnswerWrite,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> InterviewRead:
    try:
        row = await service.answer(
            db, tenant_id=actor.tenant_id, interview_id=interview_id, text=payload.text
        )
    except _ERRORS as exc:
        raise _http(exc) from exc
    return _read(row)


@router.post("/{interview_id}/complete", response_model=InterviewRead)
async def complete_interview(
    interview_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> InterviewRead:
    try:
        row = await service.complete(
            db, tenant_id=actor.tenant_id, interview_id=interview_id
        )
    except _ERRORS as exc:
        raise _http(exc) from exc
    return _read(row)


@router.post("/{interview_id}/withdraw", response_model=InterviewRead)
async def withdraw_consent(
    interview_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> InterviewRead:
    try:
        row = await service.withdraw(
            db, tenant_id=actor.tenant_id, interview_id=interview_id,
            recorded_by=actor.name,
        )
    except _ERRORS as exc:
        raise _http(exc) from exc
    return _read(row)
