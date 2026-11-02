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
