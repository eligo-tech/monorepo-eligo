"""The Contact List's "Kontakte" tab (ELI-23): every contact in the workspace,
newest first, with the company, when they were added, where they came from,
and how the last call went — filterable and countable by company.
"""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.database import SessionLocal
from app.domain.companies.models import Company
from app.domain.hub import call_list
from app.domain.managers.models import Manager, ManagerInteraction

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = dt.datetime(2026, 11, 11, 9, 0, tzinfo=dt.UTC)


async def _seed() -> dict:
    async with SessionLocal() as s:
        stw = Company(tenant_id=TENANT, name="STW GmbH")
        berg = Company(tenant_id=TENANT, name="Bergfreunde GmbH")
        foreign = Company(tenant_id=OTHER, name="Fremd GmbH")
        s.add_all([stw, berg, foreign])
        await s.flush()
        old = Manager(tenant_id=TENANT, company_id=berg.id, stage="bus_dev", full_name="Petra Vogel", role_title="CTO",
                      created_at=NOW - dt.timedelta(days=30))
        ozcan = Manager(tenant_id=TENANT, company_id=stw.id, stage="bus_dev", full_name="Nazlican Özcan", role_title="Personal",
                        phone="+49 731 1234567", source="public_web",
                        source_detail="https://example.invalid/ad", created_at=NOW - dt.timedelta(hours=1))
        lauchner = Manager(tenant_id=TENANT, company_id=stw.id, stage="bus_dev", full_name="Nicole Lauchner",
                           created_at=NOW - dt.timedelta(days=2))
        stranger = Manager(tenant_id=OTHER, company_id=foreign.id, stage="bus_dev", full_name="Fremde Person")
        s.add_all([old, ozcan, lauchner, stranger])
        await s.flush()
        s.add(ManagerInteraction(tenant_id=TENANT, manager_id=lauchner.id, interaction_type="business_call",
                                 occurred_at=NOW - dt.timedelta(days=1), outcome="call_back",
                                 next_action_at=NOW - dt.timedelta(hours=2), actor_name="Dima"))
        await s.commit()
        return {"stw": stw.id, "berg": berg.id, "ozcan": ozcan.id}


async def test_newest_first_with_company_source_and_last_call() -> None:
    await _seed()
    async with SessionLocal() as s:
        page = await call_list.contacts(s, tenant_id=TENANT, now=NOW)
    rows = page["rows"]
    assert [r["full_name"] for r in rows] == ["Nazlican Özcan", "Nicole Lauchner", "Petra Vogel"]
    ozcan = rows[0]
    assert (ozcan["company_name"], ozcan["phone"], ozcan["source"]) == ("STW GmbH", "+49 731 1234567", "public_web")
    assert ozcan["source_detail"] == "https://example.invalid/ad" and ozcan["added_at"] is not None
    assert ozcan["art14_outstanding"] is True and ozcan["last_outcome"] is None
    lauchner = rows[1]
    assert (lauchner["last_outcome"], lauchner["due"], lauchner["last_call_by"]) == ("call_back", True, "Dima")
    # The company facet: who we know where, most contacts first.
    assert [(c["name"], c["contacts"]) for c in page["companies"]] == [("STW GmbH", 2), ("Bergfreunde GmbH", 1)]
    assert page["total"] == 3


async def test_filter_by_company_and_search() -> None:
    ids = await _seed()
    async with SessionLocal() as s:
        by_company = await call_list.contacts(s, tenant_id=TENANT, company_id=ids["stw"], now=NOW)
        searched = await call_list.contacts(s, tenant_id=TENANT, q="berg", now=NOW)
    assert [r["full_name"] for r in by_company["rows"]] == ["Nazlican Özcan", "Nicole Lauchner"]
    assert [r["full_name"] for r in searched["rows"]] == ["Petra Vogel"]
    # The facet always lists every company, so the filter can be changed.
    assert len(by_company["companies"]) == 2


async def test_only_this_workspace() -> None:
    await _seed()
    async with SessionLocal() as s:
        rows = (await call_list.contacts(s, tenant_id=OTHER, now=NOW))["rows"]
    assert [r["full_name"] for r in rows] == ["Fremde Person"]


async def test_the_route() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.auth import get_current_tenant
    from app.core.config import settings
    from app.main import app

    ids = await _seed()
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"{settings.api_v1_prefix}/hub/call-list/contacts?company_id={ids['stw']}")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    assert [r["full_name"] for r in resp.json()["rows"]] == ["Nazlican Özcan", "Nicole Lauchner"]


async def test_a_search_for_wildcard_characters_matches_them_literally() -> None:
    await _seed()
    async with SessionLocal() as s:
        assert (await call_list.contacts(s, tenant_id=TENANT, q="_", now=NOW))["rows"] == []
        assert (await call_list.contacts(s, tenant_id=TENANT, q="%", now=NOW))["rows"] == []


async def test_every_way_to_reach_a_contact_is_returned() -> None:
    """A contact without a phone is reached through a network: stored profile
    links travel with the row (ELI-23)."""
    async with SessionLocal() as s:
        c = Company(tenant_id=TENANT, name="STW GmbH")
        s.add(c)
        await s.flush()
        s.add(Manager(tenant_id=TENANT, company_id=c.id, full_name="Nicole Lauchner", stage="bus_dev",
                      linkedin_url="https://www.linkedin.com/in/nicole-lauchner",
                      xing_url="https://www.xing.com/profile/Nicole_Lauchner"))
        await s.commit()
    async with SessionLocal() as s:
        (row,) = (await call_list.contacts(s, tenant_id=TENANT, now=NOW))["rows"]
    assert row["linkedin_url"] == "https://www.linkedin.com/in/nicole-lauchner"
    assert row["xing_url"] == "https://www.xing.com/profile/Nicole_Lauchner"


async def test_a_company_carries_its_impressum_switchboard() -> None:
    # ELI-30: the employer's own Impressum, as the Unternehmen view and a lead
    # without a direct number show it. Reached through THIS workspace's link.
    from app.domain.hub.employer_sites import group_key
    from app.domain.hub.models import EMPLOYER, HubCompany, HubCompanyLink, HubSiteCheck

    ids = await _seed()
    async with SessionLocal() as s:
        hub = HubCompany(
            name="STW GmbH", normalized_name="stw", dedupe_key=f"k-{uuid.uuid4()}", resolution_basis="name_place",
            city="Ulm", source="bundesagentur", kind=EMPLOYER, first_seen_at=NOW, last_seen_at=NOW,
        )
        s.add(hub)
        await s.flush()
        s.add(HubCompanyLink(tenant_id=TENANT, hub_company_id=hub.id, company_id=ids["stw"]))
        s.add(HubSiteCheck(
            domain="stw.de", group_key=group_key(hub.id), hub_company_id=hub.id, status="verified",
            impressum_url="https://stw.de/impressum", facts={"phone": "0731 100-0", "vat_id": "DE123456789"},
            checked_at=NOW,
        ))
        await s.commit()
        page = await call_list.contacts(s, tenant_id=TENANT, now=NOW)
        other = await call_list.contacts(s, tenant_id=OTHER, now=NOW)
    by_name = {c["name"]: c for c in page["companies"]}
    assert by_name["STW GmbH"]["switchboard"]["phone"] == "0731 100-0"
    assert by_name["STW GmbH"]["switchboard"]["impressum_url"] == "https://stw.de/impressum"
    assert by_name["Bergfreunde GmbH"]["switchboard"] is None
    assert all(c["switchboard"] is None for c in other["companies"])
