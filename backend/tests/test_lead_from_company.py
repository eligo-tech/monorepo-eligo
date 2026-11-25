"""ELI-78: a person found for a Markt company with no named contact can
land in Leads.

When an ad names nobody, the recruiter takes the company ("Übernehmen")
and adds the person on its page. "Manager hinzufügen" makes a vetted
manager — never a lead — so the person was missing from Leads with no
way there. What must hold:

  * "+ Lead" on the company page creates the lead AT THAT company
    (`company_id`), never at a same-name company elsewhere, and only at
    this workspace's own;
  * a manager added by hand and not contacted yet can be moved to Leads
    ("Zu Leads", `POST /managers/{id}/to-lead`) — the reverse of
    "Zu Managern" — with a receipt naming references only;
  * that move is refused (409) once the relationship has begun: a call or
    note recorded, a last contact imported, a mandate owned — and for an
    imported contact, which belongs to the customer's own system;
  * the company page says which managers may still be moved.
"""

from __future__ import annotations

import datetime as dt
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.companies.models import Company
from app.domain.hub import call_list
from app.domain.jobs.models import Job
from app.domain.managers import service as managers
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.managers.schemas import ManagerCreate
from app.domain.verification.models import Receipt

DEFAULT = settings.default_tenant_id
API = settings.api_v1_prefix

LEAD = {
    "job_title": "Senior Java Entwickler (m/w/d)",
    "full_name": "Anna Kraft",
    "role_title": "Head of Engineering",
    "company_name": "Nordlicht Software GmbH",
}


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _company(name: str = "Nordlicht Software GmbH", *, location: str | None = None,
                   tenant: uuid.UUID = DEFAULT) -> uuid.UUID:
    async with SessionLocal() as s:
        row = Company(tenant_id=tenant, name=name, location=location)
        s.add(row)
        await s.commit()
        return row.id


async def _manager(company_id: uuid.UUID, name: str = "Jonas Weber", **extra) -> uuid.UUID:
    async with SessionLocal() as s:
        row = await managers.create_manager(
            s, tenant_id=DEFAULT, payload=ManagerCreate(company_id=company_id, full_name=name),
        )
        for k, v in extra.items():
            setattr(row, k, v)
        await s.commit()
        return row.id


async def _lead_ids() -> list[uuid.UUID]:
    async with SessionLocal() as s:
        page = await call_list.contacts(s, tenant_id=DEFAULT)
    return [r["manager_id"] for r in page["rows"]]


# --- "+ Lead" on the company page ----------------------------------------


async def test_a_lead_from_the_company_page_lands_at_that_company() -> None:
    # Two companies of one name in two towns: the name alone would pick the
    # older one, the company page means THIS one.
    await _company(location="Hamburg")
    here = await _company(location="München")
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json={**LEAD, "company_id": str(here)})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["company_id"] == str(here)
    assert body["stage"] == "bus_dev"
    assert uuid.UUID(body["id"]) in await _lead_ids()


async def test_another_workspaces_company_is_refused() -> None:
    theirs = await _company(tenant=uuid.uuid4())
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json={**LEAD, "company_id": str(theirs)})
    assert r.status_code == 422
    async with SessionLocal() as s:
        assert (await s.scalars(select(Manager))).all() == []


async def test_the_manager_already_held_there_is_offered_not_doubled() -> None:
    here = await _company()
    held = await _manager(here, "Anna Kraft")
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json={**LEAD, "company_id": str(here)})
    assert r.status_code == 409
    assert r.json()["detail"]["manager_id"] == str(held)
    assert r.json()["detail"]["stage"] == "manager"


# --- "Zu Leads" ------------------------------------------------------------


async def test_a_manager_added_by_hand_moves_to_leads() -> None:
    here = await _company()
    mid = await _manager(here)
    assert await _lead_ids() == []
    async with _api() as c:
        r = await c.post(f"{API}/managers/{mid}/to-lead")
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "bus_dev"
    assert await _lead_ids() == [mid]
    async with SessionLocal() as s:
        receipt = (await s.scalars(select(Receipt).where(Receipt.subject_id == str(mid)))).all()[-1]
    assert receipt.summary == "Zu Leads verschoben"
    # References only: no name, no address.
    assert "Jonas" not in str(receipt.payload) and "Weber" not in str(receipt.payload)
    # Idempotent, like promote.
    async with _api() as c:
        again = await c.post(f"{API}/managers/{mid}/to-lead")
    assert again.status_code == 200 and again.json()["stage"] == "bus_dev"


async def test_once_contacted_a_manager_stays_a_manager() -> None:
    here = await _company()
    called = await _manager(here, "Jonas Weber")
    imported_contact = await _manager(here, "Lena Ott", last_contact_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    owns_mandate = await _manager(here, "Paul Gerber")
    imported = await _manager(here, "Ida Brandt", external_source="aifind", external_id="MNGR1")
    dnc = await _manager(here, "Max Roth", do_not_contact_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC))
    async with SessionLocal() as s:
        s.add(ManagerInteraction(tenant_id=DEFAULT, manager_id=called, interaction_type="call",
                                 occurred_at=dt.datetime.now(dt.UTC)))
        s.add(Job(tenant_id=DEFAULT, title="Backend Lead", client_company_id=here, manager_id=owns_mandate))
        await s.commit()
    async with _api() as c:
        codes = {}
        for mid in (called, imported_contact, owns_mandate, imported, dnc):
            r = await c.post(f"{API}/managers/{mid}/to-lead")
            assert r.status_code == 409, r.text
            codes[mid] = r.json()["detail"]["code"]
    assert codes == {
        called: "has_contact", imported_contact: "has_contact", owns_mandate: "has_mandate", imported: "imported",
        dnc: "do_not_contact",
    }
    assert await _lead_ids() == []


async def test_another_workspaces_manager_is_not_found() -> None:
    other = uuid.uuid4()
    async with SessionLocal() as s:
        co = Company(tenant_id=other, name="Fremd GmbH")
        s.add(co)
        await s.flush()
        m = Manager(tenant_id=other, company_id=co.id, full_name="Eva Fremd")
        s.add(m)
        await s.commit()
        mid = m.id
    async with _api() as c:
        r = await c.post(f"{API}/managers/{mid}/to-lead")
    assert r.status_code == 404
    async with SessionLocal() as s:
        assert (await s.get(Manager, mid)).stage == "manager"


async def test_the_company_page_says_who_can_still_move_to_leads() -> None:
    here = await _company()
    fresh = await _manager(here, "Jonas Weber")
    called = await _manager(here, "Lena Ott")
    async with SessionLocal() as s:
        s.add(ManagerInteraction(tenant_id=DEFAULT, manager_id=called, interaction_type="call",
                                 occurred_at=dt.datetime.now(dt.UTC)))
        await s.commit()
    async with _api() as c:
        page = (await c.get(f"{API}/companies/{here}/page")).json()
    movable = {m["id"]: m["can_be_lead"] for m in page["managers"]}
    assert movable == {str(fresh): True, str(called): False}
