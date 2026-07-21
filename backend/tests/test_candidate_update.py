"""Manual recruiter edit: a PATCH commits each field through the gate.

Verifies the non-negotiable invariant for the new write path — a human edit is
not a raw column write: it leaves append-only receipts + provenance and keeps
the hash chain intact.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates import service
from app.domain.candidates.schemas import CandidateCreate, CandidateUpdate
from app.domain.common.enums import ConfidenceSource, ReceiptAction, WorkPermitStatus
from app.domain.verification import service as verification
from app.domain.verification.models import EnrichmentRecord, Receipt


async def _new_candidate(session) -> uuid.UUID:
    candidate = await service.create_candidate(
        session,
        data=CandidateCreate(
            tenant_id=settings.default_tenant_id,
            full_name="Test Person",
            email="old@example.com",
        ),
    )
    return candidate.id


async def test_update_writes_fields_and_leaves_receipts() -> None:
    await create_all()
    tenant = settings.default_tenant_id
    async with SessionLocal() as session:
        cid = await _new_candidate(session)

        updated = await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(
                date_of_birth="12.03.1985",
                current_salary=85000,
                city="Berlin",
                work_permit=WorkPermitStatus.CITIZEN,
                skills=["Python", "FastAPI"],
            ),
        )

    assert updated is not None
    # The columns actually changed.
    assert updated.date_of_birth == "12.03.1985"
    assert updated.current_salary == 85000
    assert updated.city == "Berlin"
    assert updated.work_permit == WorkPermitStatus.CITIZEN.value
    assert updated.skills == ["Python", "FastAPI"]

    async with SessionLocal() as session:
        # A WRITE receipt exists for each of the five changed fields.
        writes = (
            await session.execute(
                select(Receipt).where(
                    Receipt.subject_id == str(cid),
                    Receipt.action == ReceiptAction.WRITE.value,
                )
            )
        ).scalars().all()
        assert len(writes) == 5
        assert all(r.agent == "recruiter_manual_edit" and r.verified for r in writes)

        # Provenance: every change recorded as human-verified and committed.
        records = (
            await session.execute(
                select(EnrichmentRecord).where(EnrichmentRecord.entity_id == cid)
            )
        ).scalars().all()
        assert len(records) == 5
        assert all(
            r.source == ConfidenceSource.HUMAN_VERIFIED.value and r.committed
            for r in records
        )

        # The tamper-evident chain still verifies.
        ok, msg = await verification.verify_chain(session, tenant_id=tenant)
        assert ok, msg


async def test_update_skips_unchanged_fields() -> None:
    await create_all()
    tenant = settings.default_tenant_id
    async with SessionLocal() as session:
        cid = await _new_candidate(session)
        # Same email as created + one real change → only one WRITE receipt.
        await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(email="old@example.com", city="Hamburg"),
        )

    async with SessionLocal() as session:
        writes = (
            await session.execute(
                select(Receipt).where(
                    Receipt.subject_id == str(cid),
                    Receipt.action == ReceiptAction.WRITE.value,
                )
            )
        ).scalars().all()
        assert len(writes) == 1
        assert writes[0].payload.get("field") == "city"


async def test_update_missing_candidate_returns_none() -> None:
    await create_all()
    async with SessionLocal() as session:
        result = await service.update_candidate(
            session,
            tenant_id=settings.default_tenant_id,
            candidate_id=uuid.uuid4(),
            patch=CandidateUpdate(city="Nowhere"),
        )
    assert result is None
