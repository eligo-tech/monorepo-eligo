"""Ads from Markt into Jobs as leads, on Postgres, as the runtime role, under
RLS (ELI-26).

"Als Lead übernehmen" failed in production for an employer the workspace did
not hold yet. SQLite has no RLS, so only this file can show it. Skipped
unless Postgres.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, admin_engine, current_tenant_var, engine
from app.domain.hub.models import EMPLOYER, HubCompany, HubJobPosting
from app.domain.hub.resolution import normalize_company_name
from app.domain.jobs.models import Job
from app.domain.tenants.models import Tenant

pytestmark = pytest.mark.skipif(not settings.is_postgres, reason="Postgres only")
NOW = dt.datetime(2026, 11, 11, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Overrides conftest: the app role may not drop tables; rows are unique per run."""
    yield
    await engine.dispose()
    await admin_engine.dispose()


@contextlib.contextmanager
def _as(tenant: uuid.UUID | None):
    token = current_tenant_var.set(str(tenant) if tenant else None)
    try:
        yield
    finally:
        current_tenant_var.reset(token)


async def _grimme_ad(tenant: uuid.UUID) -> uuid.UUID:
    """A GRIMME-like employer at one site, one ad — nothing in the workspace yet."""
    name = f"GRIMME Landmaschinenfabrik SE & Co. KG {uuid.uuid4().hex[:6]}"
    with _as(tenant):
        async with SessionLocal() as s:
            company = HubCompany(
                name=name, normalized_name=normalize_company_name(name), dedupe_key=f"k-{uuid.uuid4()}",
                resolution_basis="name_place", city="Osnabrück", source="bundesagentur", kind=EMPLOYER,
                first_seen_at=NOW, last_seen_at=NOW,
            )
            s.add(company)
            await s.flush()
            posting = HubJobPosting(
                hub_company_id=company.id, title="Embedded Software Engineer (m/w/d)", source="bundesagentur",
                external_id=f"x-{uuid.uuid4()}", content_hash="h", first_seen_at=NOW, last_seen_at=NOW,
                is_active=True, city="Osnabrück",
            )
            s.add(posting)
            await s.commit()
            return posting.id


async def _workspace() -> uuid.UUID:
    tenant = uuid.uuid4()
    with _as(None):
        async with SessionLocal() as s:
            s.add(Tenant(id=tenant, clerk_org_id=f"org_{tenant.hex}", name="HR test"))
            await s.commit()
    return tenant


async def _post(tenant: uuid.UUID, posting_ids: list[uuid.UUID]):
    from app.core.auth import get_current_tenant
    from app.main import app

    async def pinned() -> uuid.UUID:
        current_tenant_var.set(str(tenant))
        return tenant

    app.dependency_overrides[get_current_tenant] = pinned
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return await c.post(
                f"{settings.api_v1_prefix}/hub/postings/adopt",
                json={"posting_ids": [str(p) for p in posting_ids]},
            )
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)


async def test_an_ad_of_an_employer_not_yet_in_the_workspace_lands_as_a_lead() -> None:
    tenant = await _workspace()
    posting = await _grimme_ad(tenant)

    resp = await _post(tenant, [posting])

    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1
    with _as(tenant):
        async with SessionLocal() as s:
            jobs = (await s.scalars(select(Job).where(Job.tenant_id == tenant))).all()
    assert [(j.title, j.status) for j in jobs] == [("Embedded Software Engineer (m/w/d)", "lead")]


async def test_asking_again_after_a_lost_answer_reports_the_lead_not_a_second_one() -> None:
    """Production, 2026-11-11: the company and the lead were written, and the
    answer never reached the browser. The screen now asks once more; that
    retry must find the lead the first attempt made — no second job."""
    tenant = await _workspace()
    posting = await _grimme_ad(tenant)

    first = await _post(tenant, [posting])
    again = await _post(tenant, [posting])

    assert first.status_code == again.status_code == 200, (first.text, again.text)
    assert (again.json()["created"], again.json()["existing"]) == (0, 1)
    assert again.json()["results"][0]["job_id"] == first.json()["results"][0]["job_id"]
    with _as(tenant):
        async with SessionLocal() as s:
            jobs = (await s.scalars(select(Job).where(Job.tenant_id == tenant))).all()
    assert len(jobs) == 1
