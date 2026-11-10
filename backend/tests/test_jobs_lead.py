"""Ads from Markt into the workspace as LEADS (ELI-22).

A public job ad is a business-development opportunity, not a mandate: nobody
has signed anything. It lands in Jobs as `lead` — visible, workable, linked to
its ad — and is not counted as live business until a recruiter turns it into
an active mandate.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.common.enums import JobStatus
from app.domain.companies.models import Company
from app.domain.hub import service
from app.domain.hub.models import HubCompany, HubJobPosting
from app.domain.jobs import service as jobs
from app.domain.jobs.models import Job
from app.domain.jobs.schemas import JobUpdate
from app.domain.reporting import service as reporting
from app.domain.verification.models import Receipt

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()


async def _company(s, name: str, *, normalized: str, kind: str = "employer", city: str = "Spaichingen") -> HubCompany:
    now = dt.datetime.now(dt.UTC)
    company = HubCompany(
        name=name, normalized_name=normalized, dedupe_key=f"k-{uuid.uuid4()}", resolution_basis="name_place",
        city=city, source="bundesagentur", first_seen_at=now, last_seen_at=now, kind=kind,
    )
    s.add(company)
    await s.flush()
    return company


async def _posting(s, company: HubCompany, title: str, **extra) -> HubJobPosting:
    now = dt.datetime.now(dt.UTC)
    posting = HubJobPosting(
        hub_company_id=company.id, title=title, source="bundesagentur", external_id=f"x-{uuid.uuid4()}",
        content_hash="h", first_seen_at=now, last_seen_at=now, is_active=True, city=company.city, **extra,
    )
    s.add(posting)
    await s.flush()
    return posting


@pytest.fixture
async def forschner() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """One employer at two sites; two ads at the first, one at the second."""
    async with SessionLocal() as s:
        site_a = await _company(s, "Eugen Forschner GmbH", normalized="eugen forschner")
        site_b = await _company(s, "Eugen Forschner GmbH", normalized="eugen forschner", city="Tuttlingen")
        a1 = await _posting(s, site_a, "Entwicklungsingenieur Embedded Hardware (m/w/d)", salary_min=60000)
        a2 = await _posting(s, site_a, "Konstrukteur (m/w/d)")
        b1 = await _posting(s, site_b, "Elektroingenieur (m/w/d)")
        await s.commit()
        return a1.id, a2.id, b1.id


async def _adopt(*posting_ids: uuid.UUID, tenant: uuid.UUID = TENANT) -> list[dict]:
    async with SessionLocal() as s:
        return await service.adopt_postings(s, tenant_id=tenant, posting_ids=list(posting_ids))


async def _jobs(tenant: uuid.UUID = TENANT) -> list[Job]:
    async with SessionLocal() as s:
        return list((await s.scalars(select(Job).where(Job.tenant_id == tenant).order_by(Job.title))).all())


async def test_selected_ads_land_as_lead_jobs_of_one_adopted_company(forschner) -> None:
    a1, a2, _ = forschner
    result = await _adopt(a1, a2)

    assert [r["created"] for r in result] == [True, True]
    engineer, konstrukteur = await _jobs()  # ordered by title
    assert {konstrukteur.status, engineer.status} == {JobStatus.LEAD.value}
    assert engineer.title == "Entwicklungsingenieur Embedded Hardware (m/w/d)"
    assert engineer.location == "Spaichingen"
    # Linked to its ad, so the same ad never lands twice.
    assert (engineer.external_source, engineer.external_id) == ("hub", str(a1))
    async with SessionLocal() as s:
        companies = (await s.scalars(select(Company).where(Company.tenant_id == TENANT))).all()
        writes = (await s.scalars(
            select(Receipt.summary).where(Receipt.tenant_id == TENANT, Receipt.action == "write")
        )).all()
    assert [c.name for c in companies] == ["Eugen Forschner GmbH"]
    assert engineer.client_company_id == konstrukteur.client_company_id == companies[0].id
    # The company crossing is receipted, once — not once per ad.
    assert writes == ["write hub_company_id"]


async def test_the_same_ad_twice_is_one_lead(forschner) -> None:
    a1, _, _ = forschner
    await _adopt(a1)
    again = await _adopt(a1)
    assert [r["created"] for r in again] == [False]
    assert len(await _jobs()) == 1


async def test_another_site_of_an_adopted_employer_reuses_the_company(forschner) -> None:
    a1, _, b1 = forschner
    await _adopt(a1)
    await _adopt(b1)
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count(Company.id)).where(Company.tenant_id == TENANT)) == 1


async def test_an_agency_ad_is_not_a_lead() -> None:
    """A private recruiter's ad names no client: adopting the agency would put
    a competitor into Companies as if it were the hiring employer."""
    async with SessionLocal() as s:
        agency = await _company(s, "Brunel GmbH", normalized="brunel", kind="private_recruiter")
        ad = await _posting(s, agency, "Embedded Software Entwickler (w/m/d)")
        await s.commit()
    result = await _adopt(ad.id)
    assert result == [{"posting_id": ad.id, "created": False, "job_id": None, "company_id": None, "skipped": "agency"}]
    assert await _jobs() == []


async def test_an_unknown_ad_is_reported_not_raised() -> None:
    missing = uuid.uuid4()
    assert (await _adopt(missing))[0]["skipped"] == "not_found"


async def test_leads_are_per_workspace(forschner) -> None:
    a1, _, _ = forschner
    await _adopt(a1)
    await _adopt(a1, tenant=OTHER)
    assert len(await _jobs()) == 1 and len(await _jobs(OTHER)) == 1


async def test_a_lead_is_not_counted_as_live_business(forschner) -> None:
    a1, _, _ = forschner
    await _adopt(a1)
    async with SessionLocal() as s:
        assert (await reporting.summary(s, tenant_id=TENANT)).open_jobs == 0


async def _set_status(job_id: uuid.UUID, status: str) -> Job:
    async with SessionLocal() as s:
        return await jobs.update_job(s, tenant_id=TENANT, job_id=job_id, patch=JobUpdate(status=status))


async def test_a_lead_becomes_a_mandate_or_is_dropped(forschner) -> None:
    a1, a2, _ = forschner
    await _adopt(a1, a2)
    engineer, konstrukteur = await _jobs()  # ordered by title
    assert (await _set_status(engineer.id, "active")).status == "active"
    assert (await _set_status(konstrukteur.id, "inactive")).status == "inactive"
    async with SessionLocal() as s:
        assert (await reporting.summary(s, tenant_id=TENANT)).open_jobs == 1


async def test_a_mandate_does_not_go_back_to_lead(forschner) -> None:
    a1, _, _ = forschner
    await _adopt(a1)
    (engineer,) = await _jobs()
    await _set_status(engineer.id, "active")
    with pytest.raises(jobs.ReopeningRefused):
        await _set_status(engineer.id, "lead")


async def test_the_route_adopts_for_the_signed_in_workspace(forschner) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.auth import get_current_tenant
    from app.core.config import settings
    from app.main import app

    a1, a2, _ = forschner
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"{settings.api_v1_prefix}/hub/postings/adopt", json={"posting_ids": [str(a1), str(a2)]}
            )
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 2 and body["existing"] == 0 and len(body["results"]) == 2


# --- review of #236 ------------------------------------------------------------


async def test_a_failure_on_one_employer_keeps_the_leads_of_the_others(forschner, monkeypatch) -> None:
    """Employer X adopted and its lead created, then employer Y fails: X must
    not be left adopted without its lead."""
    a1, _, _ = forschner
    async with SessionLocal() as s:
        other = await _company(s, "Gasthaus Linde GmbH", normalized="gasthaus linde")
        y = await _posting(s, other, "Koch (m/w/d)")
        await s.commit()
    real = service.adopt_company

    async def flaky(session, *, hub_company_id, **kw):
        if hub_company_id == other.id:
            raise RuntimeError("database went away")
        return await real(session, hub_company_id=hub_company_id, **kw)

    monkeypatch.setattr(service, "adopt_company", flaky)
    with pytest.raises(RuntimeError):
        await _adopt(a1, y.id)
    assert [j.title for j in await _jobs()] == ["Entwicklungsingenieur Embedded Hardware (m/w/d)"]


async def test_an_employer_adopted_meanwhile_is_reused_not_a_500(forschner, monkeypatch) -> None:
    """Another request adopted the employer between our lookup and our adopt."""
    a1, _, _ = forschner
    real = service.adopt_company

    async def racing(session, *, tenant_id, hub_company_id, **kw):
        async with SessionLocal() as other:
            await real(other, tenant_id=tenant_id, hub_company_id=hub_company_id)
        return await real(session, tenant_id=tenant_id, hub_company_id=hub_company_id, **kw)

    monkeypatch.setattr(service, "adopt_company", racing)
    (result,) = await _adopt(a1)
    assert result["created"] is True
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count(Company.id)).where(Company.tenant_id == TENANT)) == 1


async def test_the_same_ad_in_two_requests_at_once_is_one_lead_not_an_error(forschner) -> None:
    import asyncio

    a1, _, _ = forschner
    results = await asyncio.gather(_adopt(a1), _adopt(a1), return_exceptions=True)
    assert not [r for r in results if isinstance(r, Exception)]
    assert len(await _jobs()) == 1


async def test_adopting_another_site_of_an_adopted_employer_is_refused(forschner) -> None:
    """Leads adopt the ad's site; the card adopts its first site. Both are one
    employer — the second must not create a second company."""
    a1, _, b1 = forschner
    await _adopt(a1)
    async with SessionLocal() as s:
        site_b = (await s.get(HubJobPosting, b1)).hub_company_id
        with pytest.raises(service.AlreadyAdopted):
            await service.adopt_company(s, tenant_id=TENANT, hub_company_id=site_b)


async def test_a_lead_makes_the_employer_a_prospect_not_a_client(forschner) -> None:
    from app.domain.hub.models import HubCompanyLink

    a1, _, _ = forschner
    await _adopt(a1)
    async with SessionLocal() as s:
        company = (await s.scalars(select(Company).where(Company.tenant_id == TENANT))).one()
        link = (await s.scalars(select(HubCompanyLink).where(HubCompanyLink.tenant_id == TENANT))).one()
    assert (company.is_client, link.relationship) == (False, "prospect")


async def test_an_ads_salary_is_not_taken_as_the_mandates_band(forschner) -> None:
    """The ad's figure has no period (hourly? monthly? yearly?) and the band is
    a hard matching filter: leave it for the recruiter."""
    a1, _, _ = forschner
    await _adopt(a1)
    (job,) = await _jobs()
    assert (job.salary_min, job.salary_max) == (None, None)


async def test_a_lead_is_not_copied_into_a_mandate(forschner) -> None:
    a1, _, _ = forschner
    await _adopt(a1)
    (lead,) = await _jobs()
    async with SessionLocal() as s:
        with pytest.raises(jobs.ReopeningRefused):
            await jobs.copy_job(s, tenant_id=TENANT, job_id=lead.id)


async def test_a_job_is_not_created_as_a_lead_by_hand() -> None:
    from app.domain.jobs.schemas import JobCreate

    async with SessionLocal() as s:
        with pytest.raises(jobs.ReopeningRefused):
            await jobs.create_job(s, data=JobCreate(tenant_id=TENANT, title="X", status="lead"))


async def test_claude_lists_mandates_not_leads(forschner) -> None:
    from app.actions.jobs import ListArgs, list_jobs

    a1, a2, _ = forschner
    await _adopt(a1, a2)
    konstrukteur = (await _jobs())[1]
    await _set_status(konstrukteur.id, "active")

    class Ctx:
        def __init__(self, session):
            self.session = session
            self.actor = type("A", (), {"tenant_id": TENANT})()

    async with SessionLocal() as s:
        listed = await list_jobs(Ctx(s), ListArgs())
        leads = await list_jobs(Ctx(s), ListArgs(status="lead"))
    assert [j.status for j in listed.jobs] == ["active"]
    assert [j.status for j in leads.jobs] == ["lead"]
