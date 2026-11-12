"""Unternehmen (ELI-33): every company of the workspace — clients and lead
companies — with a filter, and one page per company with its managers, leads
and mandates.

Measured before (prod, 2026-11-12): ~330 companies per workspace, ~290 with
managers, but only 1–4 showed in "Unternehmen", which listed lead companies
only. A client could not be found there, so no manager could be added to it.
"""

from __future__ import annotations

import datetime as dt
import uuid

from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.companies import service
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.UTC)


async def _seed() -> dict:
    async with SessionLocal() as s:
        kurtz = Company(tenant_id=TENANT, name="Kurtz Holding GmbH & Co. Beteiligungs KG", source="aifind")
        grimme = Company(tenant_id=TENANT, name="Grimme Landmaschinenfabrik GmbH & Co. KG", source="hub:bundesagentur")
        both = Company(tenant_id=TENANT, name="Bergfreunde GmbH", location="Kusterdingen")
        empty = Company(tenant_id=TENANT, name="Altkunde AG")
        foreign = Company(tenant_id=OTHER, name="Fremd GmbH")
        s.add_all([kurtz, grimme, both, empty, foreign])
        await s.flush()
        laura = Manager(tenant_id=TENANT, company_id=kurtz.id, stage="manager", full_name="Laura Schnaus",
                        role_title="HR Business Partner", email="laura@example.invalid", phone="+49 9342 807-322")
        s.add_all([
            laura,
            Manager(tenant_id=TENANT, company_id=kurtz.id, stage="manager", full_name="Eliza Kurtz"),
            Manager(tenant_id=TENANT, company_id=grimme.id, stage="bus_dev", full_name="Janet Jürgens",
                    role_title="Personalreferentin"),
            Manager(tenant_id=TENANT, company_id=both.id, stage="manager", full_name="Petra Vogel"),
            Manager(tenant_id=TENANT, company_id=both.id, stage="bus_dev", full_name="Nicole Lauchner"),
            Manager(tenant_id=OTHER, company_id=foreign.id, stage="manager", full_name="Fremde Person"),
        ])
        s.add(Job(tenant_id=TENANT, client_company_id=kurtz.id, title="Leiter Konstruktion (m/w/d)"))
        await s.flush()
        s.add(ManagerInteraction(tenant_id=TENANT, manager_id=laura.id, interaction_type="client_call",
                                 occurred_at=NOW, outcome="reached"))
        await s.commit()
        return {"kurtz": kurtz.id, "grimme": grimme.id, "both": both.id, "empty": empty.id,
                "foreign": foreign.id, "laura": laura.id}


async def _overview(**kw) -> list[dict]:
    async with SessionLocal() as s:
        return await service.overview(s, tenant_id=TENANT, **kw)


async def test_every_company_of_the_workspace_is_listed_with_its_counts() -> None:
    ids = await _seed()
    rows = {r["name"]: r for r in await _overview()}
    # A client from the ATS import is there, not only lead companies.
    assert set(rows) == {
        "Kurtz Holding GmbH & Co. Beteiligungs KG", "Grimme Landmaschinenfabrik GmbH & Co. KG",
        "Bergfreunde GmbH", "Altkunde AG",
    }
    kurtz = rows["Kurtz Holding GmbH & Co. Beteiligungs KG"]
    assert (kurtz["id"], kurtz["managers"], kurtz["leads"], kurtz["mandates"]) == (ids["kurtz"], 2, 0, 1)
    assert kurtz["last_contact_at"] is not None
    assert (rows["Bergfreunde GmbH"]["managers"], rows["Bergfreunde GmbH"]["leads"]) == (1, 1)
    assert rows["Bergfreunde GmbH"]["location"] == "Kusterdingen"


async def test_the_filter_clients_and_leads() -> None:
    await _seed()
    clients = {r["name"] for r in await _overview(kind="clients")}
    leads = {r["name"] for r in await _overview(kind="leads")}
    # Kunde: at least one manager. Lead: at least one new contact from Markt.
    # A client with new contacts is both.
    assert clients == {"Kurtz Holding GmbH & Co. Beteiligungs KG", "Bergfreunde GmbH"}
    assert leads == {"Grimme Landmaschinenfabrik GmbH & Co. KG", "Bergfreunde GmbH"}


async def test_search_by_name() -> None:
    await _seed()
    assert [r["name"] for r in await _overview(q="kurtz")] == ["Kurtz Holding GmbH & Co. Beteiligungs KG"]


async def test_the_company_page_has_its_people_and_mandates() -> None:
    ids = await _seed()
    async with SessionLocal() as s:
        page = await service.company_page(s, tenant_id=TENANT, company_id=ids["both"])
        kurtz = await service.company_page(s, tenant_id=TENANT, company_id=ids["kurtz"])
    assert page["company"]["name"] == "Bergfreunde GmbH"
    assert [m["full_name"] for m in page["managers"]] == ["Petra Vogel"]
    assert [m["full_name"] for m in page["leads"]] == ["Nicole Lauchner"]
    laura = next(m for m in kurtz["managers"] if m["full_name"] == "Laura Schnaus")
    assert (laura["id"], laura["role_title"], laura["phone"]) == (ids["laura"], "HR Business Partner", "+49 9342 807-322")
    assert laura["last_contact_at"] is not None
    assert [j["title"] for j in kurtz["mandates"]] == ["Leiter Konstruktion (m/w/d)"]
    assert kurtz["switchboard"] is None


async def test_another_workspaces_company_is_not_found() -> None:
    ids = await _seed()
    async with SessionLocal() as s:
        assert await service.company_page(s, tenant_id=TENANT, company_id=ids["foreign"]) is None
    assert "Fremd GmbH" not in {r["name"] for r in await _overview()}


async def test_the_routes() -> None:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        company = (await client.post("/api/v1/companies", json={"name": "Routen GmbH"})).json()
        listed = await client.get("/api/v1/companies/overview", params={"kind": "all", "q": "routen"})
        assert listed.status_code == 200 and [r["name"] for r in listed.json()] == ["Routen GmbH"]
        page = await client.get(f"/api/v1/companies/{company['id']}/page")
        assert page.status_code == 200 and page.json()["company"]["name"] == "Routen GmbH"
        assert (await client.get(f"/api/v1/companies/{uuid.uuid4()}/page")).status_code == 404
        assert (await client.get("/api/v1/companies/overview", params={"kind": "nonsense"})).status_code == 422
