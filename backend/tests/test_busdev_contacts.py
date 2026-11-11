"""Bus-Dev-Kontakte (ELI-23): new contacts from Markt, not yet vetted managers.

A person taken from Markt (a public ad) starts as a business-development
contact. Once the first contact is done, a recruiter moves them to Managers.
Contacts imported or entered by hand are managers from the start. Nothing is
deleted on either move — the stage is a column on the same record.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.hub import call_list
from app.domain.hub import service as hub
from app.domain.hub.models import HubCompany
from app.domain.managers import service as managers
from app.domain.managers.schemas import ManagerCreate

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()


@pytest.fixture
async def company() -> uuid.UUID:
    async with SessionLocal() as s:
        c = Company(tenant_id=TENANT, name="STW GmbH")
        s.add(c)
        await s.commit()
        return c.id


async def _create(company_id: uuid.UUID, name: str, source: ConfidenceSource):
    async with SessionLocal() as s:
        return await managers.create_manager(
            s, tenant_id=TENANT, payload=ManagerCreate(company_id=company_id, full_name=name, source=source)
        )


async def test_a_person_from_markt_starts_as_bus_dev_and_a_typed_one_as_manager(company) -> None:
    from_ad = await _create(company, "Nazlican Özcan", ConfidenceSource.PUBLIC_WEB)
    by_hand = await _create(company, "Petra Vogel", ConfidenceSource.SELF_REPORTED)
    assert (from_ad.stage, by_hand.stage) == ("bus_dev", "manager")


async def test_adopting_an_employer_with_its_ad_contact_makes_a_bus_dev_contact() -> None:
    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        hc = HubCompany(name="Eugen Forschner GmbH", normalized_name="eugen forschner", dedupe_key="k",
                        resolution_basis="name_place", source="bundesagentur", first_seen_at=now, last_seen_at=now)
        s.add(hc)
        await s.commit()
    async with SessionLocal() as s:
        _company, _link, person = await hub.adopt_company(
            s, tenant_id=TENANT, hub_company_id=hc.id,
            manager={"full_name": "Leonie Denkinger", "phone": "+49 7424 943 126", "source": "public_web"},
        )
    assert person.stage == "bus_dev"


async def test_the_list_shows_bus_dev_contacts_only(company) -> None:
    await _create(company, "Nazlican Özcan", ConfidenceSource.PUBLIC_WEB)
    await _create(company, "Petra Vogel", ConfidenceSource.SELF_REPORTED)
    async with SessionLocal() as s:
        page = await call_list.contacts(s, tenant_id=TENANT)
    assert [r["full_name"] for r in page["rows"]] == ["Nazlican Özcan"]
    assert page["total"] == 1
    # The company filter offers only companies with bus-dev contacts.
    assert [(c["name"], c["contacts"]) for c in page["companies"]] == [("STW GmbH", 1)]


async def test_moving_to_managers_after_the_first_contact(company) -> None:
    person = await _create(company, "Nazlican Özcan", ConfidenceSource.PUBLIC_WEB)
    async with SessionLocal() as s:
        moved = await managers.promote_manager(s, tenant_id=TENANT, manager_id=person.id)
    assert moved.stage == "manager" and moved.promoted_at is not None
    async with SessionLocal() as s:
        assert (await call_list.contacts(s, tenant_id=TENANT))["rows"] == []
        listed = await managers.list_managers(s, tenant_id=TENANT, stage="manager")
        assert [m.full_name for m in listed] == ["Nazlican Özcan"]
        # Same record: provenance and the Art. 14 duty travel with it.
        assert listed[0].source == "public_web" and listed[0].art14_outstanding is True


async def test_the_managers_screen_lists_managers_not_bus_dev(company) -> None:
    await _create(company, "Nazlican Özcan", ConfidenceSource.PUBLIC_WEB)
    await _create(company, "Petra Vogel", ConfidenceSource.SELF_REPORTED)
    async with SessionLocal() as s:
        assert [m.full_name for m in await managers.list_managers(s, tenant_id=TENANT, stage="manager")] == ["Petra Vogel"]
        assert await managers.count_managers(s, tenant_id=TENANT, stage="manager") == 1
        # Without a stage, every contact — the mandate editor's contact picker.
        assert len(await managers.list_managers(s, tenant_id=TENANT)) == 2


async def test_a_call_from_the_market_list_makes_a_bus_dev_contact() -> None:
    from app.domain.hub.models import HubAdContact, HubJobPosting

    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        hc = HubCompany(name="Gasthaus Linde GmbH", normalized_name="gasthaus linde", dedupe_key="k2",
                        resolution_basis="name_place", source="bundesagentur", first_seen_at=now, last_seen_at=now)
        s.add(hc)
        await s.flush()
        p = HubJobPosting(hub_company_id=hc.id, title="Koch", source="bundesagentur", external_id="x",
                          content_hash="h", first_seen_at=now, last_seen_at=now, is_active=True)
        s.add(p)
        await s.flush()
        s.add(HubAdContact(hub_job_posting_id=p.id, hub_company_id=hc.id, person_key="kraft", full_name="Anna Kraft",
                           first_name="Anna", last_name="Kraft", quote="q", text_source="ad"))
        await s.commit()
    async with SessionLocal() as s:
        result = await call_list.log_call(s, tenant_id=TENANT, hub_company_id=hc.id, person_key="kraft", outcome="voicemail")
        person = await managers.get_manager(s, tenant_id=TENANT, manager_id=result["manager_id"])
    assert person.stage == "bus_dev"


def _client(tenant: uuid.UUID):
    from app.core.auth import get_current_tenant
    from app.main import app

    app.dependency_overrides[get_current_tenant] = lambda: tenant
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _no_overrides():
    yield
    from app.main import app

    app.dependency_overrides.clear()


async def test_the_routes(company) -> None:
    from app.core.config import settings

    person = await _create(company, "Nazlican Özcan", ConfidenceSource.PUBLIC_WEB)
    await _create(company, "Petra Vogel", ConfidenceSource.SELF_REPORTED)
    base = settings.api_v1_prefix
    async with _client(OTHER) as c:
        assert (await c.post(f"{base}/managers/{person.id}/promote")).status_code == 404
    async with _client(TENANT) as c:
        listed = await c.get(f"{base}/managers?stage=manager")
        assert [m["full_name"] for m in listed.json()] == ["Petra Vogel"]
        assert listed.headers["X-Total-Count"] == "1"
        moved = await c.post(f"{base}/managers/{person.id}/promote")
        assert moved.status_code == 200 and moved.json()["stage"] == "manager"
        assert len((await c.get(f"{base}/managers?stage=manager")).json()) == 2
