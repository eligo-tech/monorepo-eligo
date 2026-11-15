"""ELI-37: a lead shows the concrete jobs connected to the person.

A lead is a person a public ad named. The Leads list says which ad(s) — the
corpus ads at this workspace's employer (any of its sites) whose stored ad
contact is that person — and, where the workspace took an ad in as a job, or
gave the person a mandate, that job. Read in a fixed number of queries per
list, never one per lead.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import event

from app.core.database import SessionLocal, engine
from app.domain.companies.models import Company
from app.domain.hub import call_list
from app.domain.hub.contacts import person_key
from app.domain.hub.models import EMPLOYER, HubAdContact, HubCompany, HubCompanyLink, HubJobPosting
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = dt.datetime(2026, 11, 11, 9, 0, tzinfo=dt.UTC)


async def _employer(s, name: str, normalized: str, city: str) -> HubCompany:
    c = HubCompany(name=name, normalized_name=normalized, dedupe_key=f"k-{uuid.uuid4()}", resolution_basis="name_place",
                   city=city, source="bundesagentur", first_seen_at=NOW, last_seen_at=NOW, kind=EMPLOYER)
    s.add(c)
    await s.flush()
    return c


async def _ad(s, company: HubCompany, title: str, *, days_ago: int, contact: str | None) -> HubJobPosting:
    p = HubJobPosting(hub_company_id=company.id, title=title, source="bundesagentur", external_id=f"10000-{uuid.uuid4()}",
                      content_hash="h", first_seen_at=NOW, last_seen_at=NOW, is_active=True, city=company.city,
                      posted_at=NOW - dt.timedelta(days=days_ago), source_url="https://example.invalid/list")
    s.add(p)
    await s.flush()
    if contact:
        s.add(HubAdContact(hub_job_posting_id=p.id, hub_company_id=company.id, person_key=person_key(None, contact),
                           full_name=f"Frau {contact}", last_name=contact, quote=f"Ihre Ansprechpartnerin: Frau {contact}",
                           text_source="ad"))
    return p


async def _seed() -> dict:
    async with SessionLocal() as s:
        ulm = await _employer(s, "STW GmbH", "stw", "Ulm")
        berlin = await _employer(s, "STW GmbH", "stw", "Berlin")  # another site of the same employer
        other_employer = await _employer(s, "Weber AG", "weber", "Ulm")

        pflege = await _ad(s, ulm, "Pflegefachkraft (m/w/d)", days_ago=3, contact="Özcan")
        it = await _ad(s, berlin, "IT-Administrator (m/w/d)", days_ago=1, contact="Özcan")
        await _ad(s, ulm, "Koch (m/w/d)", days_ago=2, contact="Lauchner")
        await _ad(s, other_employer, "Fahrer (m/w/d)", days_ago=1, contact="Özcan")  # same surname, other firm

        stw = Company(tenant_id=TENANT, name="STW GmbH")
        foreign = Company(tenant_id=OTHER, name="STW GmbH")
        s.add_all([stw, foreign])
        await s.flush()
        s.add(HubCompanyLink(tenant_id=TENANT, hub_company_id=ulm.id, company_id=stw.id))
        s.add(HubCompanyLink(tenant_id=OTHER, hub_company_id=ulm.id, company_id=foreign.id))

        ozcan = Manager(tenant_id=TENANT, company_id=stw.id, stage="bus_dev", full_name="Nazlican Özcan",
                        first_name="Nazlican", last_name="Özcan", source="public_web", created_at=NOW)
        lauchner = Manager(tenant_id=TENANT, company_id=stw.id, stage="bus_dev", full_name="Nicole Lauchner",
                           created_at=NOW - dt.timedelta(days=1))
        nobody = Manager(tenant_id=TENANT, company_id=stw.id, stage="bus_dev", full_name="Petra Vogel",
                         created_at=NOW - dt.timedelta(days=2))
        stranger = Manager(tenant_id=OTHER, company_id=foreign.id, stage="bus_dev", full_name="Nicole Lauchner")
        s.add_all([ozcan, lauchner, nobody, stranger])
        await s.flush()

        # The IT ad was taken into Jobs (ELI-22 adopt postings).
        adopted = Job(tenant_id=TENANT, title="IT-Administrator (m/w/d)", client_company_id=stw.id,
                      status="lead", external_source="hub", external_id=str(it.id))
        # A mandate given to Lauchner by hand, no ad behind it.
        mandate = Job(tenant_id=TENANT, title="Küchenleitung", client_company_id=stw.id, manager_id=lauchner.id,
                      location="Ulm", status="active")
        # Another workspace's job for the same ad — never shown here.
        theirs = Job(tenant_id=OTHER, title="Pflege bei denen", client_company_id=foreign.id,
                     external_source="hub", external_id=str(pflege.id))
        s.add_all([adopted, mandate, theirs])
        await s.commit()
        return {"pflege": pflege.id, "it": it.id, "adopted": adopted.id, "mandate": mandate.id}


async def test_a_lead_lists_the_ads_that_name_them_and_the_jobs_taken_from_them() -> None:
    ids = await _seed()
    async with SessionLocal() as s:
        rows = {r["full_name"]: r for r in (await call_list.contacts(s, tenant_id=TENANT, now=NOW))["rows"]}

    ozcan = rows["Nazlican Özcan"]["jobs"]
    # Both sites of the employer, newest ad first; not the other firm's Özcan.
    assert [j["title"] for j in ozcan] == ["IT-Administrator (m/w/d)", "Pflegefachkraft (m/w/d)"]
    it, pflege = ozcan
    assert it["posting_id"] == ids["it"] and it["job_id"] == ids["adopted"] and it["location"] == "Berlin"
    assert it["url"].startswith("https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-")
    # The other workspace took the Pflege ad in — that is not this one's job.
    assert pflege["posting_id"] == ids["pflege"] and pflege["job_id"] is None

    lauchner = rows["Nicole Lauchner"]["jobs"]
    assert [(j["title"], j["job_id"]) for j in lauchner] == [("Koch (m/w/d)", None), ("Küchenleitung", ids["mandate"])]
    assert lauchner[1]["posting_id"] is None and lauchner[1]["url"] is None and lauchner[1]["location"] == "Ulm"

    assert rows["Petra Vogel"]["jobs"] == []


async def test_the_jobs_cost_the_same_queries_for_one_lead_as_for_many() -> None:
    await _seed()
    statements: list[str] = []

    def count(*args) -> None:
        statements.append(args[2])

    sync = engine.sync_engine
    event.listen(sync, "before_cursor_execute", count)
    try:
        async with SessionLocal() as s:
            await call_list.contacts(s, tenant_id=TENANT, now=NOW, limit=1)
        one = len(statements)
        statements.clear()
        async with SessionLocal() as s:
            await call_list.contacts(s, tenant_id=TENANT, now=NOW, limit=500)
        many = len(statements)
    finally:
        event.remove(sync, "before_cursor_execute", count)
    assert one == many


async def test_the_route_carries_the_jobs() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.auth import get_current_tenant
    from app.core.config import settings
    from app.main import app

    await _seed()
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"{settings.api_v1_prefix}/hub/call-list/contacts")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    rows = {r["full_name"]: r for r in resp.json()["rows"]}
    assert [j["title"] for j in rows["Nazlican Özcan"]["jobs"]] == ["IT-Administrator (m/w/d)", "Pflegefachkraft (m/w/d)"]


async def test_one_role_relayed_twice_is_one_job_and_keeps_the_job_taken_from_either_copy() -> None:
    async with SessionLocal() as s:
        site = await _employer(s, "Relay GmbH", "relay", "Ulm")
        await _ad(s, site, "Lagerist (m/w/d)", days_ago=1, contact="Kern")
        relayed = await _ad(s, site, "Lagerist (m/w/d)", days_ago=5, contact="Kern")
        company = Company(tenant_id=TENANT, name="Relay GmbH")
        s.add(company)
        await s.flush()
        s.add(HubCompanyLink(tenant_id=TENANT, hub_company_id=site.id, company_id=company.id))
        s.add(Manager(tenant_id=TENANT, company_id=company.id, stage="bus_dev", full_name="Jana Kern"))
        job = Job(tenant_id=TENANT, title="Lagerist", client_company_id=company.id, status="lead",
                  external_source="hub", external_id=str(relayed.id))
        s.add(job)
        await s.commit()
        job_id = job.id
    async with SessionLocal() as s:
        (row,) = (await call_list.contacts(s, tenant_id=TENANT, now=NOW))["rows"]
    assert [(j["title"], j["job_id"]) for j in row["jobs"]] == [("Lagerist (m/w/d)", job_id)]
