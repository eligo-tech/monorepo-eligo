"""A workspace's companies in Markt: exact links and open jobs (ELI-33).

Only a certain match is linked without a person: the same normalized name in
the same town (the company's own location, else its managers' town or
postcode). Each link goes through the verification gate and leaves a receipt.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.companies import market, service
from app.domain.companies.models import Company
from app.domain.hub.models import EMPLOYER, HubCompany, HubCompanyLink, HubJobPosting, HubPostingPayload
from app.domain.hub.resolution import normalize_company_name
from app.domain.managers.models import Manager
from app.domain.verification.models import Receipt

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.UTC)


def _hub(name: str, city: str | None, plz: str | None = None) -> HubCompany:
    return HubCompany(
        name=name, normalized_name=normalize_company_name(name), dedupe_key=f"k-{uuid.uuid4()}",
        resolution_basis="name_place", city=city, postal_code=plz, source="bundesagentur", kind=EMPLOYER,
        first_seen_at=NOW, last_seen_at=NOW,
    )


def _ad(hub: HubCompany, title: str, *, days_ago: int, active: bool = True, source: str = "bundesagentur",
        external_id: str | None = None, link: str | None = None, vacancy: str | None = None) -> HubJobPosting:
    p = HubJobPosting(
        hub_company_id=hub.id, title=title, source=source, external_id=external_id or f"10001-{uuid.uuid4().hex[:8]}-S",
        posted_at=NOW - dt.timedelta(days=days_ago), first_seen_at=NOW, last_seen_at=NOW, is_active=active,
        content_hash=uuid.uuid4().hex, segment=EMPLOYER, city=hub.city, vacancy_key=vacancy,
    )
    p.payload = HubPostingPayload(raw={"externeURL": link} if link else {}, description="…")
    return p


async def _company(tenant: uuid.UUID, name: str, *, location: str | None = None, manager_city: str | None = None,
                   manager_plz: str | None = None) -> uuid.UUID:
    async with SessionLocal() as s:
        c = Company(tenant_id=tenant, name=name, location=location, source="aifind")
        s.add(c)
        await s.flush()
        if manager_city or manager_plz:
            s.add(Manager(tenant_id=tenant, company_id=c.id, stage="manager", full_name="Max Mustermann",
                          city=manager_city, postal_code=manager_plz))
        await s.commit()
        return c.id


async def _add(*rows) -> None:
    async with SessionLocal() as s:
        s.add_all(rows)
        await s.commit()


async def _links(tenant: uuid.UUID, company_id: uuid.UUID) -> list[HubCompanyLink]:
    async with SessionLocal() as s:
        return list((await s.scalars(select(HubCompanyLink).where(
            HubCompanyLink.tenant_id == tenant, HubCompanyLink.company_id == company_id))).all())


async def _auto(tenant: uuid.UUID = TENANT) -> dict:
    async with SessionLocal() as s:
        return await market.auto_link(s, tenant_id=tenant)


def test_town_keys() -> None:
    assert market.town_key("Nürnberg, Mittelfranken") == market.town_key("Nuernberg") == "nuernberg"
    assert market.town_key("Frankfurt (Oder)") == "frankfurt"
    assert market.town_key(None) is None and market.town_key(" , ") is None


async def test_same_name_and_town_is_linked_with_a_receipt() -> None:
    hub = _hub("N-ERGIE Aktiengesellschaft", "Nürnberg, Mittelfranken")
    await _add(hub)
    cid = await _company(TENANT, "N-ERGIE Aktiengesellschaft", manager_city="Nürnberg")
    assert await _auto() == {"linked": 1}
    [row] = await _links(TENANT, cid)
    assert row.hub_company_id == hub.id and row.relationship == "client"
    async with SessionLocal() as s:
        receipts = await s.scalar(select(func.count()).select_from(Receipt).where(
            Receipt.tenant_id == TENANT, Receipt.agent == "company_market_link"))
    assert receipts >= 1


async def test_a_postcode_matches_when_the_town_is_written_differently() -> None:
    hub = _hub("Roche Diagnostics GmbH", "Penzberg", "82377")
    await _add(hub)
    cid = await _company(TENANT, "Roche Diagnostics GmbH", manager_plz="82377", manager_city="Penzberg/Obb.")
    await _auto()
    assert [r.hub_company_id for r in await _links(TENANT, cid)] == [hub.id]


async def test_the_same_name_in_another_town_is_not_linked() -> None:
    await _add(_hub("Marc Cain GmbH", "Bodelshausen"))
    cid = await _company(TENANT, "Marc Cain GmbH", manager_city="Berlin")
    unknown = await _company(TENANT, "Marc Cain GmbH")  # no town known at all
    assert await _auto() == {"linked": 0}
    assert await _links(TENANT, cid) == [] and await _links(TENANT, unknown) == []


async def test_several_sites_in_the_town_are_all_linked() -> None:
    a, b = _hub("Siemens AG", "München", "80333"), _hub("Siemens AG", "München", "81739")
    elsewhere = _hub("Siemens AG", "Erlangen")
    await _add(a, b, elsewhere)
    cid = await _company(TENANT, "Siemens AG", location="München")
    await _auto()
    assert {r.hub_company_id for r in await _links(TENANT, cid)} == {a.id, b.id}


async def test_a_linked_company_and_a_held_site_are_left_alone() -> None:
    hub = _hub("inovex GmbH", "Karlsruhe, Baden")
    await _add(hub)
    first = await _company(TENANT, "inovex GmbH", location="Karlsruhe")
    await _auto()
    duplicate = await _company(TENANT, "inovex GmbH", location="Karlsruhe")  # a second row of the same name
    assert await _auto() == {"linked": 0}
    assert len(await _links(TENANT, first)) == 1 and await _links(TENANT, duplicate) == []


async def test_only_this_workspace_is_linked() -> None:
    await _add(_hub("blackned GmbH", "Gilching"))
    mine = await _company(TENANT, "blackned GmbH", location="Gilching")
    theirs = await _company(OTHER, "blackned GmbH", location="Gilching")
    await _auto(TENANT)
    assert len(await _links(TENANT, mine)) == 1
    assert await _links(OTHER, theirs) == []


async def test_open_jobs_of_every_site_newest_first_each_role_once() -> None:
    munich, berlin = _hub("Isar Aerospace SE", "München"), _hub("Isar Aerospace SE", "Berlin")
    await _add(munich, berlin)
    await _add(
        _ad(munich, "Propulsion Engineer (m/w/d)", days_ago=2, vacancy="v1"),
        _ad(munich, "Propulsion Engineer (m/w/d)", days_ago=3, vacancy="v1", source="personio",
            external_id="isaraerospace:123"),  # the same role relayed: counted once
        _ad(berlin, "Software Engineer (m/w/d)", days_ago=1),
        _ad(munich, "Closed Role (m/w/d)", days_ago=0, active=False),
    )
    cid = await _company(TENANT, "Isar Aerospace SE", location="München")
    await _auto()
    async with SessionLocal() as s:
        jobs = await market.open_jobs(s, tenant_id=TENANT, company_id=cid)
    assert jobs["linked"] is True and jobs["total"] == 2
    assert [j["title"] for j in jobs["jobs"]] == ["Software Engineer (m/w/d)", "Propulsion Engineer (m/w/d)"]
    assert jobs["jobs"][0]["url"].startswith("https://www.arbeitsagentur.de/jobsuche/jobdetail/")
    # Its own Personio board is the careers page.
    assert jobs["careers"] == {"url": "https://isaraerospace.jobs.personio.de/", "kind": "careers"}


def test_the_careers_page_from_the_ads_links_never_a_job_board() -> None:
    page = market.careers_page([
        ("bundesagentur", "1", "https://www.stepstone.de/job/1"),
        ("bundesagentur", "2", "https://karriere.n-ergie.de/stelle/9"),
        ("bundesagentur", "3", "https://karriere.n-ergie.de/stelle/10"),
    ])
    assert page == {"url": "https://karriere.n-ergie.de/", "kind": "careers"}
    assert market.careers_page([("bundesagentur", "1", "https://www.n-ergie.de/x")]) == {
        "url": "https://www.n-ergie.de/", "kind": "website"}
    assert market.careers_page([("bundesagentur", "1", None)]) is None
    assert market.careers_page([("lever", "eu:acme:42", None)]) == {"url": "https://jobs.eu.lever.co/acme", "kind": "careers"}


async def test_an_unlinked_company_has_no_jobs_and_the_page_says_so() -> None:
    cid = await _company(TENANT, "Altkunde AG")
    async with SessionLocal() as s:
        page = await service.company_page(s, tenant_id=TENANT, company_id=cid)
    assert page["market"] == {"linked": False, "total": 0, "jobs": [], "careers": None}


async def test_the_operator_route_links_every_workspace(monkeypatch) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.config import settings
    from app.main import app

    await _add(_hub("uniVersa Versicherungen", "Nürnberg"))
    mine = await _company(TENANT, "uniVersa Versicherungen", manager_city="Nürnberg")
    theirs = await _company(OTHER, "uniVersa Versicherungen", manager_city="Nürnberg")
    token = "eli33-" + uuid.uuid4().hex * 2
    monkeypatch.setattr(settings, "ingest_token", token)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post("/api/v1/hub/company-links/auto", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["linked"] == 2
    assert len(await _links(TENANT, mine)) == 1 and len(await _links(OTHER, theirs)) == 1
