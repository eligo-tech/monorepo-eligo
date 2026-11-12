"""Confirming the unclear Markt matches (ELI-33, step 2b).

Exact name + town is linked automatically. The same name in another or
unknown town (measured: ~41 companies per workspace) is shown on the company
page for a person to confirm per site — or to dismiss ("Keiner davon"), so it
is not suggested again. A wrong link can be undone; the daily job must not
put it back.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.companies import market, service
from app.domain.companies.models import Company
from app.domain.hub.models import EMPLOYER, HubCompany, HubCompanyLink, HubJobPosting, HubPostingPayload
from app.domain.hub.resolution import normalize_company_name
from app.domain.verification.models import Receipt

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.UTC)


def _hub(name: str, city: str | None) -> HubCompany:
    return HubCompany(
        name=name, normalized_name=normalize_company_name(name), dedupe_key=f"k-{uuid.uuid4()}",
        resolution_basis="name_place", city=city, source="bundesagentur", kind=EMPLOYER,
        first_seen_at=NOW, last_seen_at=NOW,
    )


async def _add(*rows) -> None:
    async with SessionLocal() as s:
        s.add_all(rows)
        await s.commit()


async def _ads(hub: HubCompany, *titles: str) -> None:
    rows = []
    for i, title in enumerate(titles):
        p = HubJobPosting(
            hub_company_id=hub.id, title=title, source="bundesagentur", external_id=f"x-{uuid.uuid4().hex[:8]}",
            posted_at=NOW - dt.timedelta(days=i), first_seen_at=NOW, last_seen_at=NOW, is_active=True,
            content_hash=uuid.uuid4().hex, segment=EMPLOYER,
        )
        p.payload = HubPostingPayload(raw={}, description="…")
        rows.append(p)
    await _add(*rows)


async def _company(name: str, tenant: uuid.UUID = TENANT) -> uuid.UUID:
    async with SessionLocal() as s:
        c = Company(tenant_id=tenant, name=name, source="aifind")
        s.add(c)
        await s.commit()
        return c.id


async def _seed() -> dict:
    """Marc Cain GmbH: no town on record; Markt has it in two towns."""
    bodelshausen, berlin = _hub("Marc Cain GmbH", "Bodelshausen"), _hub("Marc Cain GmbH", "Berlin")
    await _add(bodelshausen, berlin)
    await _ads(bodelshausen, "Schnittdirectrice (m/w/d)", "Modellmacher (m/w/d)", "Lagerist (m/w/d)")
    await _ads(berlin, "Verkäufer (m/w/d)")
    return {"company": await _company("Marc Cain GmbH"), "bodelshausen": bodelshausen.id, "berlin": berlin.id}


async def _page(company_id: uuid.UUID) -> dict:
    async with SessionLocal() as s:
        return await service.company_page(s, tenant_id=TENANT, company_id=company_id)


async def test_an_unlinked_company_shows_its_same_name_sites_most_ads_first() -> None:
    ids = await _seed()
    page = await _page(ids["company"])
    sites = page["suggestions"]
    assert [s["hub_company_id"] for s in sites] == [ids["bodelshausen"], ids["berlin"]]
    assert sites[0]["city"] == "Bodelshausen" and sites[0]["open_ads"] == 3
    assert sites[0]["sample_titles"] == ["Schnittdirectrice (m/w/d)", "Modellmacher (m/w/d)"]


async def test_the_overview_counts_the_companies_to_review() -> None:
    ids = await _seed()
    await _company("Ohne Treffer GmbH")
    async with SessionLocal() as s:
        rows = {r["name"]: r for r in await service.overview(s, tenant_id=TENANT)}
    assert rows["Marc Cain GmbH"]["to_review"] == 2
    assert rows["Ohne Treffer GmbH"]["to_review"] == 0
    assert ids  # seeded


async def test_confirming_one_site_links_it_with_the_persons_receipt() -> None:
    ids = await _seed()
    async with SessionLocal() as s:
        await market.confirm(s, tenant_id=TENANT, company_id=ids["company"], hub_company_ids=[ids["bodelshausen"]],
                             actor="Thomas B.")
    page = await _page(ids["company"])
    assert page["market"]["linked"] is True and page["suggestions"] == []
    async with SessionLocal() as s:
        receipt = await s.scalar(select(Receipt).where(Receipt.agent == "recruiter_market_link", Receipt.action == "write"))
    assert receipt is not None and receipt.payload.get("actor") == "Thomas B."


async def test_a_site_another_company_holds_cannot_be_confirmed() -> None:
    ids = await _seed()
    other = await _company("Marc Cain GmbH")  # a duplicate row of the same name
    async with SessionLocal() as s:
        await market.confirm(s, tenant_id=TENANT, company_id=other, hub_company_ids=[ids["bodelshausen"]], actor="A")
    async with SessionLocal() as s:
        with pytest.raises(market.SiteTaken):
            await market.confirm(s, tenant_id=TENANT, company_id=ids["company"], hub_company_ids=[ids["bodelshausen"]],
                                 actor="A")
    # …and it is no longer suggested to the other company.
    assert [x["hub_company_id"] for x in (await _page(ids["company"]))["suggestions"]] == [ids["berlin"]]


async def test_a_site_of_another_name_cannot_be_confirmed() -> None:
    ids = await _seed()
    stranger = _hub("Fremde Firma GmbH", "Bodelshausen")
    await _add(stranger)
    async with SessionLocal() as s:
        with pytest.raises(market.NotACandidate):
            await market.confirm(s, tenant_id=TENANT, company_id=ids["company"], hub_company_ids=[stranger.id], actor="A")


async def test_none_of_these_is_not_suggested_again_nor_auto_linked() -> None:
    ids = await _seed()
    async with SessionLocal() as s:
        await market.dismiss(s, tenant_id=TENANT, company_id=ids["company"],
                             hub_company_ids=[ids["bodelshausen"], ids["berlin"]])
    assert (await _page(ids["company"]))["suggestions"] == []
    # Even once a town is on record that would match exactly, the daily job leaves it.
    async with SessionLocal() as s:
        (await s.get(Company, ids["company"])).location = "Bodelshausen"
        await s.commit()
    async with SessionLocal() as s:
        assert await market.auto_link(s, tenant_id=TENANT) == {"linked": 0}


async def test_a_wrong_link_is_undone_and_stays_undone() -> None:
    ids = await _seed()
    async with SessionLocal() as s:
        await market.confirm(s, tenant_id=TENANT, company_id=ids["company"], hub_company_ids=[ids["berlin"]], actor="A")
    async with SessionLocal() as s:
        await market.unlink(s, tenant_id=TENANT, company_id=ids["company"], actor="A")
    page = await _page(ids["company"])
    assert page["market"]["linked"] is False
    # Berlin is out; Bodelshausen is still a candidate.
    assert [x["hub_company_id"] for x in page["suggestions"]] == [ids["bodelshausen"]]
    async with SessionLocal() as s:
        (await s.get(Company, ids["company"])).location = "Berlin"
        await s.commit()
    async with SessionLocal() as s:
        assert await market.auto_link(s, tenant_id=TENANT) == {"linked": 0}
        receipt = await s.scalar(select(Receipt).where(Receipt.agent == "recruiter_market_unlink", Receipt.action == "write"))
    assert receipt is not None


async def test_another_workspaces_dismissal_changes_nothing_here() -> None:
    ids = await _seed()
    theirs = await _company("Marc Cain GmbH", tenant=OTHER)
    async with SessionLocal() as s:
        await market.dismiss(s, tenant_id=OTHER, company_id=theirs, hub_company_ids=[ids["bodelshausen"]])
    assert len((await _page(ids["company"]))["suggestions"]) == 2


async def test_the_routes() -> None:
    from app.main import app

    from app.core.config import settings

    ids = await _seed()
    # Without auth every request is the default workspace.
    ids["company"] = await _company("Marc Cain GmbH", tenant=uuid.UUID(str(settings.default_tenant_id)))
    cid = str(ids["company"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        page = (await client.get(f"/api/v1/companies/{cid}/page")).json()
        assert len(page["suggestions"]) == 2
        r = await client.post(f"/api/v1/companies/{cid}/market-links", json={"hub_company_ids": [str(ids["berlin"])]})
        assert r.status_code == 200 and r.json()["market"]["linked"] is True
        again = await client.post(f"/api/v1/companies/{cid}/market-links",
                                  json={"hub_company_ids": [str(uuid.uuid4())]})
        assert again.status_code == 422
        r = await client.delete(f"/api/v1/companies/{cid}/market-links")
        assert r.status_code == 200 and r.json()["market"]["linked"] is False
        r = await client.post(f"/api/v1/companies/{cid}/market-dismissals",
                              json={"hub_company_ids": [str(ids["bodelshausen"])]})
        assert r.status_code == 200 and r.json()["suggestions"] == []
        missing = await client.post(f"/api/v1/companies/{uuid.uuid4()}/market-links",
                                    json={"hub_company_ids": [str(ids["berlin"])]})
        assert missing.status_code == 404
    async with SessionLocal() as s:
        rows = (await s.scalars(select(HubCompanyLink).where(HubCompanyLink.company_id == ids["company"]))).all()
    assert rows == []


async def test_picking_one_site_rules_out_the_others_shown_and_their_jobs() -> None:
    # Found clicking through: confirming Bodelshausen still listed Berlin's
    # job, because open jobs counted every site of the name. A same-name firm
    # elsewhere is not ours once a person picked another site.
    ids = await _seed()
    async with SessionLocal() as s:
        await market.confirm(s, tenant_id=TENANT, company_id=ids["company"], hub_company_ids=[ids["bodelshausen"]],
                             actor="A", dismiss_ids=[ids["berlin"]])
    page = await _page(ids["company"])
    assert page["market"]["total"] == 3
    assert "Verkäufer (m/w/d)" not in [j["title"] for j in page["market"]["jobs"]]


async def test_all_sites_of_a_chain_can_be_confirmed_at_once() -> None:
    ids = await _seed()
    async with SessionLocal() as s:
        await market.confirm(s, tenant_id=TENANT, company_id=ids["company"],
                             hub_company_ids=[ids["bodelshausen"], ids["berlin"]], actor="A")
    assert (await _page(ids["company"]))["market"]["total"] == 4
