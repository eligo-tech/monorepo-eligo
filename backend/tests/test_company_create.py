"""Unternehmen hinzufügen (ELI-43).

"+ Unternehmen" on Unternehmen: Name, Ort, Website, Status Lead or Kunde. The
status is a person's decision, recorded through the verification gate, and
it is what the Kunden / Leads filters then go by — `is_client` alone is not
(the imports set it on every row). On create, a Markt employer of the same
name in the same town is linked at once; a company that already exists here
is refused with 409 so the UI can open it instead.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.companies import service
from app.domain.companies.models import Company
from app.domain.companies.schemas import CompanyCreate
from app.domain.hub.models import EMPLOYER, HubCompany, HubCompanyLink, HubJobPosting
from app.domain.hub.resolution import normalize_company_name
from app.domain.managers.models import Manager
from app.domain.verification.models import EnrichmentRecord, Receipt

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = dt.datetime(2026, 11, 19, 9, 0, tzinfo=dt.UTC)


def _hub(name: str, city: str | None) -> HubCompany:
    return HubCompany(
        name=name, normalized_name=normalize_company_name(name), dedupe_key=f"k-{uuid.uuid4()}",
        resolution_basis="name_place", city=city, source="bundesagentur", kind=EMPLOYER,
        first_seen_at=NOW, last_seen_at=NOW,
    )


async def _create(tenant: uuid.UUID = TENANT, **kw) -> Company:
    async with SessionLocal() as s:
        return await service.create_company(s, data=CompanyCreate(tenant_id=tenant, **kw), actor="Anna Recruiter")


async def _overview(kind: str, tenant: uuid.UUID = TENANT) -> set[str]:
    async with SessionLocal() as s:
        return {r["name"] for r in await service.overview(s, tenant_id=tenant, kind=kind)}


async def test_a_new_lead_with_no_contact_is_under_leads_and_a_new_kunde_under_kunden() -> None:
    lead = await _create(name="Neulead GmbH", location="Ulm", status="lead")
    kunde = await _create(name="Neukunde AG", website="https://www.neukunde.de/karriere", status="client")
    assert lead.source == kunde.source == "manual"
    assert (lead.is_client, kunde.is_client) == (False, True)
    assert kunde.domain == "neukunde.de"
    assert await _overview("leads") == {"Neulead GmbH"}
    assert await _overview("clients") == {"Neukunde AG"}
    async with SessionLocal() as s:
        rows = {r["name"]: r for r in await service.overview(s, tenant_id=TENANT)}
        page = await service.company_page(s, tenant_id=TENANT, company_id=kunde.id)
    assert (rows["Neulead GmbH"]["status"], rows["Neukunde AG"]["status"]) == ("lead", "client")
    assert page["company"]["status"] == "client"


async def test_the_status_decision_is_receipted_with_the_person() -> None:
    company = await _create(name="Beleg GmbH", status="lead")
    async with SessionLocal() as s:
        record = await s.scalar(select(EnrichmentRecord).where(
            EnrichmentRecord.entity_id == company.id, EnrichmentRecord.field == "is_client"))
        receipts = (await s.scalars(select(Receipt).where(Receipt.subject_id == str(company.id)))).all()
    assert record is not None and record.committed and record.proposed_value == "false"
    assert any(r.payload.get("actor") == "Anna Recruiter" for r in receipts)


async def test_the_status_can_be_changed_and_a_person_overrides_the_manager_rule() -> None:
    lead = await _create(name="Wechsel GmbH", status="lead")
    async with SessionLocal() as s:
        await service.set_status(s, tenant_id=TENANT, company_id=lead.id, status="client", actor="Anna")
    assert "Wechsel GmbH" in await _overview("clients")
    assert "Wechsel GmbH" not in await _overview("leads")

    # An imported company: `is_client` true by the import, a Kunde only by its
    # manager. A person saying "Lead" wins over that.
    async with SessionLocal() as s:
        imported = Company(tenant_id=TENANT, name="Import KG", source="datei-import", is_client=True)
        s.add(imported)
        await s.flush()
        s.add(Manager(tenant_id=TENANT, company_id=imported.id, stage="manager", full_name="Max Muster"))
        await s.commit()
    assert "Import KG" in await _overview("clients")
    async with SessionLocal() as s:
        await service.set_status(s, tenant_id=TENANT, company_id=imported.id, status="lead", actor="Anna")
    assert "Import KG" in await _overview("leads")
    assert "Import KG" not in await _overview("clients")


async def test_set_status_is_tenant_scoped() -> None:
    theirs = await _create(tenant=OTHER, name="Fremd GmbH", status="lead")
    async with SessionLocal() as s:
        with pytest.raises(LookupError):
            await service.set_status(s, tenant_id=TENANT, company_id=theirs.id, status="client", actor="Anna")
    assert "Fremd GmbH" in await _overview("leads", tenant=OTHER)
    assert "Fremd GmbH" not in await _overview("all")


async def test_a_duplicate_is_refused_with_the_existing_company() -> None:
    first = await _create(name="Doppel GmbH", location="Nürnberg")
    with pytest.raises(service.CompanyExists) as err:
        await _create(name="doppel gmbh", location="Nuernberg, Mittelfranken")
    assert err.value.company_id == first.id
    # Same name without an Ort: still the same company.
    with pytest.raises(service.CompanyExists):
        await _create(name="Doppel AG")
    # Same name elsewhere: another company (a same-name firm in another town).
    other_town = await _create(name="Doppel GmbH", location="Hamburg")
    assert other_town.id != first.id
    # Another workspace may have its own.
    assert (await _create(tenant=OTHER, name="Doppel GmbH", location="Nürnberg")).tenant_id == OTHER


async def test_same_name_and_town_as_a_markt_employer_links_it_at_once() -> None:
    async with SessionLocal() as s:
        here, elsewhere = _hub("Marc Cain GmbH", "Bodelshausen"), _hub("Marc Cain GmbH", "Berlin")
        s.add_all([here, elsewhere])
        await s.flush()
        s.add(HubJobPosting(
            hub_company_id=here.id, title="Schnittdirektrice (m/w/d)", source="bundesagentur",
            external_id="10001-x-S", posted_at=NOW, first_seen_at=NOW, last_seen_at=NOW, is_active=True,
            content_hash=uuid.uuid4().hex, segment=EMPLOYER, city="Bodelshausen",
        ))
        await s.commit()
        here_id, elsewhere_id = here.id, elsewhere.id
    company = await _create(name="Marc Cain", location="Bodelshausen", status="client")
    async with SessionLocal() as s:
        linked = (await s.scalars(select(HubCompanyLink.hub_company_id).where(
            HubCompanyLink.tenant_id == TENANT, HubCompanyLink.company_id == company.id))).all()
        page = await service.company_page(s, tenant_id=TENANT, company_id=company.id)
    assert linked == [here_id] and elsewhere_id not in linked
    assert page["market"]["linked"] and [j["title"] for j in page["market"]["jobs"]] == ["Schnittdirektrice (m/w/d)"]
    # The link says what the person decided: a Kunde, not a prospect.
    async with SessionLocal() as s:
        rel = await s.scalar(select(HubCompanyLink.relationship).where(HubCompanyLink.company_id == company.id))
    assert rel == "client"
    assert page["company"]["status"] == "client" and page["company"]["status_set"] is True


async def test_a_failed_link_still_saves_the_company(monkeypatch) -> None:
    """The company is saved before the link is tried; a link that fails must
    not report "nicht gespeichert" — the daily linker tries again."""
    from app.domain.companies import market

    async with SessionLocal() as s:
        s.add(_hub("Wackel GmbH", "Ulm"))
        await s.commit()

    async def _boom(*_a, **_k):
        raise RuntimeError("market link did not land")

    monkeypatch.setattr(market, "link", _boom)
    company = await _create(name="Wackel GmbH", location="Ulm", status="lead")
    async with SessionLocal() as s:
        assert (await service.get_company(s, tenant_id=TENANT, company_id=company.id)) is not None
    assert "Wackel GmbH" in await _overview("leads")


async def test_without_an_ort_nothing_is_linked() -> None:
    async with SessionLocal() as s:
        s.add(_hub("Ortlos GmbH", "Bodelshausen"))
        await s.commit()
    company = await _create(name="Ortlos GmbH")
    async with SessionLocal() as s:
        assert (await s.scalars(select(HubCompanyLink).where(HubCompanyLink.company_id == company.id))).all() == []


async def test_the_routes() -> None:
    from app.main import app

    tenant = uuid.UUID(str(settings.default_tenant_id))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        made = await c.post("/api/v1/companies", json={"name": "Route Neu GmbH", "location": "Ulm", "status": "lead"})
        assert made.status_code == 201, made.text
        cid = made.json()["id"]
        again = await c.post("/api/v1/companies", json={"name": "Route Neu AG", "location": "Ulm"})
        assert again.status_code == 409 and cid in again.text
        assert (await c.post("/api/v1/companies", json={"name": "  "})).status_code == 422
        changed = await c.put(f"/api/v1/companies/{cid}/status", json={"status": "client"})
        assert changed.status_code == 200 and changed.json()["company"]["status"] == "client"
        assert (await c.put(f"/api/v1/companies/{uuid.uuid4()}/status", json={"status": "client"})).status_code == 404
        assert (await c.put(f"/api/v1/companies/{cid}/status", json={"status": "kunde"})).status_code == 422
    async with SessionLocal() as s:
        assert {r["name"] for r in await service.overview(s, tenant_id=tenant, kind="clients")} >= {"Route Neu GmbH"}
