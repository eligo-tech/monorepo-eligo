"""Manual recruiter edit: a PATCH commits each field through the gate.

Verifies the non-negotiable invariant for the new write path — a human edit is
not a raw column write: it leaves append-only receipts + provenance and keeps
the hash chain intact.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates import service
from app.domain.candidates.schemas import CandidateCreate, CandidateUpdate
from app.domain.common.enums import ConfidenceSource, ReceiptAction, WorkPermitStatus
from app.domain.verification import service as verification
from app.domain.verification.models import EnrichmentRecord, Receipt
from app.main import app


def _api() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create_via_api(c: AsyncClient) -> str:
    r = await c.post(
        "/api/v1/candidates",
        json={"full_name": "Api Person", "email": "api@old.com"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


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


# --- #1: the append-only ledger names *who* edited ------------------------


async def test_update_records_editor_identity() -> None:
    await create_all()
    tenant = settings.default_tenant_id
    async with SessionLocal() as session:
        cid = await _new_candidate(session)
        await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(city="München"),
            editor="clerk_user_42",
        )

    async with SessionLocal() as session:
        write = (
            await session.execute(
                select(Receipt).where(
                    Receipt.subject_id == str(cid),
                    Receipt.action == ReceiptAction.WRITE.value,
                )
            )
        ).scalar_one()
        # The tamper-evident receipt itself carries the actor.
        assert write.payload.get("actor") == "clerk_user_42"

        record = (
            await session.execute(
                select(EnrichmentRecord).where(EnrichmentRecord.entity_id == cid)
            )
        ).scalar_one()
        assert "clerk_user_42" in (record.source_detail or "")

        # Enriched payload must not break the recomputed hash chain.
        ok, msg = await verification.verify_chain(session, tenant_id=tenant)
        assert ok, msg


# --- #2: server-side validation returns a real 422 ------------------------


async def test_patch_rejects_invalid_email() -> None:
    await create_all()
    async with _api() as c:
        cid = await _create_via_api(c)
        r = await c.patch(f"/api/v1/candidates/{cid}", json={"email": "not-an-email"})
        assert r.status_code == 422, r.text


async def test_patch_rejects_negative_salary() -> None:
    await create_all()
    async with _api() as c:
        cid = await _create_via_api(c)
        r = await c.patch(f"/api/v1/candidates/{cid}", json={"current_salary": -1})
        assert r.status_code == 422, r.text


async def test_patch_null_on_nonnullable_is_ignored_not_500() -> None:
    await create_all()
    async with _api() as c:
        cid = await _create_via_api(c)
        r = await c.patch(
            f"/api/v1/candidates/{cid}",
            json={"salary_currency": None, "city": "Bonn"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["salary_currency"] == "EUR"  # left untouched, not nulled
        assert body["city"] == "Bonn"  # the real change still applied


async def test_patch_blank_email_clears_it() -> None:
    await create_all()
    async with _api() as c:
        cid = await _create_via_api(c)
        r = await c.patch(f"/api/v1/candidates/{cid}", json={"email": "   "})
        assert r.status_code == 200, r.text
        assert r.json()["email"] is None
