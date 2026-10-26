"""Two recruiters, one candidate, one open drawer each.

The workspace this was written for has two people in it, which is exactly the
number at which "last write wins" stops being theoretical: A opens a record,
B corrects a field, A saves the value A could see, and B's correction is gone
with nothing on screen to say so. The receipts prove what happened, but only
to somebody who already suspects it.

The rule these tests pin is narrower than "refuse concurrent edits", because
the patch has always been a per-field diff and two people editing *different*
fields of one candidate were never in conflict. What is refused is a write to
a field somebody else has committed since the editor was opened.

**One second of slack on SQLite.** `enrichment_records.created_at` is
`CURRENT_TIMESTAMP` here, which has second resolution — two writes inside the
same second are indistinguishable, so the positive case sleeps past a second
boundary to make the ordering real rather than lucky. Postgres (`now()`,
microseconds) needs no such gap; the test asserts the behaviour, not the
clock.
"""

from __future__ import annotations

import asyncio
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates import service
from app.domain.candidates.models import Candidate
from app.domain.candidates.schemas import CandidateCreate, CandidateUpdate
from app.main import app

#: Long enough to cross a CURRENT_TIMESTAMP tick — see the module docstring.
SQLITE_TICK = 1.1


def _api() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _candidate(session) -> Candidate:
    return await service.create_candidate(
        session,
        data=CandidateCreate(
            tenant_id=settings.default_tenant_id,
            full_name="Hanna Demko",
            email="hanna@example.com",
            phone="+49 30 000000",
            city="Berlin",
        ),
    )


async def _phone(session, cid: uuid.UUID) -> str | None:
    return await session.scalar(select(Candidate.phone).where(Candidate.id == cid))


async def test_a_second_edit_of_the_same_field_is_refused() -> None:
    """The defect this whole PR exists for, as the two of them would hit it."""
    await create_all()
    tenant = settings.default_tenant_id
    async with SessionLocal() as session:
        candidate = await _candidate(session)
        cid = candidate.id
        # A opens the drawer. This is the version A's form was seeded from.
        a_baseline = candidate.updated_at

        await asyncio.sleep(SQLITE_TICK)

        # B corrects the number and saves.
        await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(phone="+49 30 111111"),
            editor="Thomas",
        )

        # A, still looking at the old number, types a different one.
        try:
            await service.update_candidate(
                session,
                tenant_id=tenant,
                candidate_id=cid,
                patch=CandidateUpdate(
                    phone="+49 30 222222", base_updated_at=a_baseline
                ),
                editor="Dima",
            )
        except service.ConcurrentEdit as exc:
            assert exc.fields == ["phone"], exc.fields
        else:
            raise AssertionError("A's stale write was accepted — B's edit is lost")

        # And nothing was written: B's value stands, untouched.
        assert await _phone(session, cid) == "+49 30 111111"


async def test_editing_a_different_field_is_not_a_conflict() -> None:
    """The case that must stay fast and silent, or the feature is a nuisance.

    It also covers the reason this reads `enrichment_records` instead of
    `candidates.updated_at`: B's save bumps the row timestamp — and writes
    `verification_score` through `recompute_scores` — so a row-level check
    would refuse A's unrelated edit and train both of them to click past the
    warning that matters.
    """
    await create_all()
    tenant = settings.default_tenant_id
    async with SessionLocal() as session:
        candidate = await _candidate(session)
        cid = candidate.id
        a_baseline = candidate.updated_at

        await asyncio.sleep(SQLITE_TICK)

        await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(phone="+49 30 111111"),
            editor="Thomas",
        )
        updated = await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(city="Hamburg", base_updated_at=a_baseline),
            editor="Dima",
        )

        assert updated is not None
        assert updated.city == "Hamburg"
        assert await _phone(session, cid) == "+49 30 111111"  # B's edit survives


async def test_agreeing_with_the_other_edit_is_not_a_conflict() -> None:
    """A types the value B already saved. Nothing changes, so nothing clashes.

    Without the no-op filter running *before* the conflict query, the two of
    them typing the same correction would produce a 409 about a disagreement
    that does not exist.
    """
    await create_all()
    tenant = settings.default_tenant_id
    async with SessionLocal() as session:
        candidate = await _candidate(session)
        cid = candidate.id
        a_baseline = candidate.updated_at

        await asyncio.sleep(SQLITE_TICK)

        await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(phone="+49 30 111111"),
            editor="Thomas",
        )
        updated = await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(
                phone="+49 30 111111", base_updated_at=a_baseline
            ),
            editor="Dima",
        )

        assert updated is not None
        assert await _phone(session, cid) == "+49 30 111111"


async def test_without_a_baseline_the_write_still_goes_through() -> None:
    """Every caller that is not the cockpit — importers, seed, scripts, the
    existing API — sends no baseline and must keep working unchanged. This is
    also the "save anyway" path the UI offers once it has shown the warning."""
    await create_all()
    tenant = settings.default_tenant_id
    async with SessionLocal() as session:
        candidate = await _candidate(session)
        cid = candidate.id

        await asyncio.sleep(SQLITE_TICK)

        await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(phone="+49 30 111111"),
            editor="Thomas",
        )
        updated = await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(phone="+49 30 222222"),  # no baseline
            editor="Dima",
        )

        assert updated is not None
        assert await _phone(session, cid) == "+49 30 222222"


async def test_the_baseline_is_not_a_writable_field() -> None:
    """`base_updated_at` rides in the PATCH body, so prove it stays control.

    If it ever reached the field loop it would be looked up with
    `getattr(candidate, "base_updated_at")` — which returns nothing, compares
    unequal, and would try to write a column that does not exist.
    """
    await create_all()
    tenant = settings.default_tenant_id
    async with SessionLocal() as session:
        candidate = await _candidate(session)
        cid = candidate.id

        assert not hasattr(candidate, "base_updated_at")

        await service.update_candidate(
            session,
            tenant_id=tenant,
            candidate_id=cid,
            patch=CandidateUpdate(
                city="Hamburg", base_updated_at=candidate.updated_at
            ),
            editor="Dima",
        )

        from app.domain.verification.models import EnrichmentRecord

        fields = (
            await session.execute(
                select(EnrichmentRecord.field).where(
                    EnrichmentRecord.entity_id == cid
                )
            )
        ).scalars().all()
        assert "base_updated_at" not in fields
        assert "city" in fields


async def test_the_api_answers_409_and_names_the_fields() -> None:
    """Over HTTP, because the status code is the contract the cockpit reads."""
    await create_all()
    async with _api() as client:
        created = await client.post(
            "/api/v1/candidates",
            json={"full_name": "Hanna Demko", "phone": "+49 30 000000"},
        )
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        a_baseline = created.json()["updated_at"]

        await asyncio.sleep(SQLITE_TICK)

        first = await client.patch(
            f"/api/v1/candidates/{cid}", json={"phone": "+49 30 111111"}
        )
        assert first.status_code == 200, first.text

        clash = await client.patch(
            f"/api/v1/candidates/{cid}",
            json={"phone": "+49 30 222222", "base_updated_at": a_baseline},
        )
        assert clash.status_code == 409, clash.text
        detail = clash.json()["detail"]
        assert detail["code"] == "concurrent_edit"
        assert detail["fields"] == ["phone"]

        # The refused write left the record exactly as the first writer left it.
        current = await client.get(f"/api/v1/candidates/{cid}")
        assert current.json()["phone"] == "+49 30 111111"
