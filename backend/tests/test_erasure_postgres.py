"""A whole erasure on Postgres, as the runtime role, under RLS.

SQLite does not enforce foreign keys and has no RLS or grants, so the order
the erasure deletes in, and whether `eligo_app` may do each step, are only
proved here. Skipped unless the database is Postgres.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal, admin_engine, current_tenant_var, engine
from app.domain.candidates.models import Candidate
from app.domain.erasure import service as erasure
from app.domain.verification import service as verification
from app.domain.verification.models import BLACKOUT_SUMMARY, Receipt
from test_erasure import EMAIL, _person  # same fixture world as the SQLite suite

pytestmark = pytest.mark.skipif(not settings.is_postgres, reason="Postgres only")


@pytest.fixture(autouse=True)
async def _fresh_db(monkeypatch):
    monkeypatch.setattr(settings, "suppression_key", "k" * 40)
    yield
    await engine.dispose()
    await admin_engine.dispose()


@contextlib.contextmanager
def _as(tenant: uuid.UUID):
    token = current_tenant_var.set(str(tenant))
    try:
        yield
    finally:
        current_tenant_var.reset(token)


async def test_an_erasure_runs_end_to_end_as_the_app_role() -> None:
    tenant, other = uuid.uuid4(), uuid.uuid4()
    with _as(tenant):
        async with SessionLocal() as s:
            erika = await _person(s, tenant, "Erika Muster", EMAIL, "ext-1")
            await s.commit()
    with _as(other):
        async with SessionLocal() as s:
            twin = await _person(s, other, "Erika Muster", EMAIL, "ext-1")
            await s.commit()
    with _as(tenant):
        async with SessionLocal() as s:
            req = await erasure.erase_candidate(
                s, tenant_id=tenant, candidate_id=erika["candidate"], confirm_name="Erika Muster",
                reason="erasure", requested_on=dt.date(2026, 11, 1), actor_user_id="u", actor_name="A",
            )
            await s.commit()
        async with SessionLocal() as s:
            gone = await s.get(Candidate, erika["candidate"]) is None
            ok, why = await verification.verify_chain(s, tenant_id=tenant)
            blacked = (await s.execute(select(func.count()).select_from(Receipt).where(
                Receipt.summary == BLACKOUT_SUMMARY))).scalar_one()
    with _as(other):
        async with SessionLocal() as s:
            twin_kept = await s.get(Candidate, twin["candidate"]) is not None
            ok_other, _ = await verification.verify_chain(s, tenant_id=other)
    assert gone and twin_kept
    assert ok, why
    assert ok_other
    assert blacked == req.counts["receipts_blacked_out"] >= 3


async def _erased(tenant: uuid.UUID) -> None:
    with _as(tenant):
        async with SessionLocal() as s:
            p = await _person(s, tenant, "Erika Muster", EMAIL, f"ext-{uuid.uuid4()}")
            await s.commit()
        async with SessionLocal() as s:
            await erasure.erase_candidate(
                s, tenant_id=tenant, candidate_id=p["candidate"], confirm_name="Erika Muster",
                reason="erasure", requested_on=dt.date(2026, 11, 1), actor_user_id="u", actor_name="A",
            )
            await s.commit()


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM tenant_suppressions",
        "DELETE FROM erasure_requests",
        "UPDATE erasure_requests SET counts = '{}'",
        "UPDATE tenant_suppressions SET digest = 'x'",
    ],
)
async def test_the_app_role_cannot_undo_or_rewrite_an_erasure(statement) -> None:
    """Deleting a suppression would silently let the person back in; rewriting
    the log would hide that an erasure happened. Insert-only for the app role."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    tenant = uuid.uuid4()
    await _erased(tenant)
    with _as(tenant):
        async with SessionLocal() as s:
            with pytest.raises(DBAPIError, match="permission denied"):
                await s.execute(text(statement))


async def test_the_app_role_can_lift_a_suppression() -> None:
    """The one change allowed: a person who came back of their own accord."""
    tenant = uuid.uuid4()
    await _erased(tenant)
    with _as(tenant):
        async with SessionLocal() as s:
            lifted = await erasure.guard_readd(s, tenant_id=tenant, email=EMAIL, override=True)
            await s.commit()
    assert lifted


async def test_a_contact_erasure_runs_end_to_end_as_the_app_role() -> None:
    from app.domain.companies.models import Company
    from app.domain.jobs.models import Job
    from app.domain.managers.models import Manager, ManagerInteraction

    tenant = uuid.uuid4()
    with _as(tenant):
        async with SessionLocal() as s:
            company = Company(tenant_id=tenant, name="Kunde")
            s.add(company)
            await s.flush()
            boss = Manager(tenant_id=tenant, company_id=company.id, full_name="Hans Chef",
                           email="hans@kunde.de", external_source="aifind", external_id="m-1")
            s.add(boss)
            await s.flush()
            job = Job(tenant_id=tenant, title="CTO", client_company_id=company.id, manager_id=boss.id)
            s.add_all([job, ManagerInteraction(tenant_id=tenant, manager_id=boss.id, interaction_type="note",
                                               occurred_at=dt.datetime.now(dt.UTC), summary="Budget")])
            await s.commit()
            ids = (boss.id, job.id)
        async with SessionLocal() as s:
            await erasure.erase_manager(
                s, tenant_id=tenant, manager_id=ids[0], confirm_name="Hans Chef", reason="objection",
                requested_on=dt.date(2026, 11, 2), actor_user_id="u", actor_name="A",
            )
            await s.commit()
        async with SessionLocal() as s:
            assert await s.get(Manager, ids[0]) is None
            assert (await s.get(Job, ids[1])).manager_id is None
            ok, why = await verification.verify_chain(s, tenant_id=tenant)
    assert ok, why
