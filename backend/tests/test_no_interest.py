"""ELI-60: "Kein Interesse" takes a lead off the Leads list — and keeps them.

A lead called with the outcome "Kein Interesse" leaves the Leads list by
default. Nothing is deleted: the manager row, the call and its note stay and
are shown on the manager and company pages with "Kein Interesse (seit …)".
The Leads list shows them again under the "Kein Interesse" filter, and
"Wieder als Lead aufnehmen" undoes it. Taking the same person from Markt
again does not create them a second time, and does not move them back.

A sales status — not the ELI-32 "Nicht mehr kontaktieren" mark, which is a
data-protection request; the two are set and cleared independently.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.hub import call_list
from app.domain.hub.models import HubCompanyLink
from app.domain.managers import service as managers
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.managers.schemas import ManagerCreate
from app.domain.verification.models import Receipt
from tests.test_call_list import market  # noqa: F401 — fixture

DEFAULT = settings.default_tenant_id
API = settings.api_v1_prefix


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _call(hub_company_id, person_key, outcome, *, tenant=DEFAULT, **kw) -> dict:
    async with SessionLocal() as s:
        return await call_list.log_call(
            s, tenant_id=tenant, hub_company_id=hub_company_id, person_key=person_key, outcome=outcome, **kw
        )


async def _contacts(**kw) -> dict:
    async with SessionLocal() as s:
        return await call_list.contacts(s, tenant_id=kw.pop("tenant", DEFAULT), **kw)


async def test_kein_interesse_takes_the_lead_off_the_list_and_keeps_everything(market) -> None:  # noqa: F811
    first = await _call(market["forschner"], "denkinger", "not_reached")
    assert [r["full_name"] for r in (await _contacts())["rows"]] == ["Leonie Denkinger"]

    await _call(market["forschner"], "denkinger", "not_interested", summary="Kein Bedarf, alles intern")
    page = await _contacts()
    assert page["rows"] == [] and page["total"] == 0
    assert page["no_interest_total"] == 1

    # Under the filter, with the date and the last call.
    hidden = await _contacts(no_interest=True)
    (row,) = hidden["rows"]
    assert row["full_name"] == "Leonie Denkinger" and row["no_interest_at"] is not None
    assert row["last_outcome"] == "not_interested"

    async with SessionLocal() as s:
        manager = await s.get(Manager, first["manager_id"])
        calls = (await s.scalars(select(ManagerInteraction).where(ManagerInteraction.manager_id == manager.id))).all()
        receipts = (await s.scalars(select(Receipt).where(Receipt.subject_id == str(manager.id)))).all()
    # Same record, same stage, both calls and the note kept.
    assert manager.stage == "bus_dev" and manager.no_interest_at is not None
    assert sorted(c.outcome for c in calls) == ["not_interested", "not_reached"]
    assert any(c.summary == "Kein Bedarf, alles intern" for c in calls)
    # The status change leaves a receipt naming the call, not its words.
    (mark,) = [r for r in receipts if r.summary == "Kein Interesse vermerkt"]
    assert "intern" not in str(mark.payload)
    # A sales status, not the data-protection mark.
    assert manager.do_not_contact_at is None


async def test_kein_interesse_on_the_lead_row_and_wieder_als_lead(market) -> None:  # noqa: F811
    result = await _call(market["forschner"], "denkinger", "not_reached")
    mid = result["manager_id"]
    async with _api() as c:
        r = await c.post(f"{API}/managers/{mid}/interactions",
                         json={"interaction_type": "business_call", "summary": "", "outcome": "not_interested"})
        assert r.status_code == 201
        got = (await c.get(f"{API}/managers/{mid}")).json()
        assert got["no_interest_at"] is not None
        listed = (await c.get(f"{API}/hub/call-list/contacts")).json()
        assert listed["rows"] == [] and listed["no_interest_total"] == 1
        only = (await c.get(f"{API}/hub/call-list/contacts", params={"no_interest": "true"})).json()
        assert [r["manager_id"] for r in only["rows"]] == [str(mid)]

        # The company page keeps them under Leads, with the date.
        page = (await c.get(f"{API}/companies/{result['company_id']}/page")).json()
        assert [p["no_interest_at"] is not None for p in page["leads"]] == [True]

        back = await c.delete(f"{API}/managers/{mid}/no-interest")
        assert back.status_code == 200 and back.json()["no_interest_at"] is None
        listed = (await c.get(f"{API}/hub/call-list/contacts")).json()
        assert [r["manager_id"] for r in listed["rows"]] == [str(mid)]
        assert listed["no_interest_total"] == 0
        assert (await c.delete(f"{API}/managers/{uuid.uuid4()}/no-interest")).status_code == 404

    async with SessionLocal() as s:
        receipts = (await s.scalars(select(Receipt).where(Receipt.subject_id == str(mid)))).all()
    assert {"Kein Interesse vermerkt", "Wieder als Lead aufgenommen"} <= {r.summary for r in receipts}


async def test_a_vetted_manager_is_not_a_lead_and_gets_no_lead_status() -> None:
    async with SessionLocal() as s:
        company = Company(tenant_id=DEFAULT, name="Kunde GmbH")
        s.add(company)
        await s.flush()
        m = Manager(tenant_id=DEFAULT, company_id=company.id, full_name="Petra Kunde", stage="manager")
        s.add(m)
        await s.commit()
    async with _api() as c:
        r = await c.post(f"{API}/managers/{m.id}/interactions",
                         json={"interaction_type": "business_call", "summary": "", "outcome": "not_interested"})
        assert r.status_code == 201
        assert (await c.get(f"{API}/managers/{m.id}")).json()["no_interest_at"] is None


async def test_the_same_person_is_not_taken_again_from_markt(market) -> None:  # noqa: F811
    result = await _call(market["forschner"], "denkinger", "not_interested")
    company_id = result["company_id"]

    # Markt's "Übernehmen" on an adopted company posts a new manager: refused,
    # naming the existing record — no second Denkinger.
    async with _api() as c:
        r = await c.post(f"{API}/managers", json={
            "company_id": str(company_id), "full_name": "Leonie Denkinger", "first_name": "Leonie",
            "last_name": "Denkinger", "source": "public_web", "source_detail": "https://example.invalid/ad",
        })
        assert r.status_code == 409
        assert r.json()["detail"]["manager_id"] == str(result["manager_id"])
        # "Frau Denkinger" from another ad is the same person too.
        r = await c.post(f"{API}/managers", json={
            "company_id": str(company_id), "full_name": "Denkinger", "last_name": "Denkinger",
            "source": "public_web",
        })
        assert r.status_code == 409

    # Calling again from the Markt list reuses the record and keeps the status.
    again = await _call(market["forschner"], "denkinger", "call_back",
                        next_action_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=3))
    assert again["manager_id"] == result["manager_id"] and again["created_manager"] is False
    async with SessionLocal() as s:
        n = len((await s.scalars(select(Manager).where(Manager.tenant_id == DEFAULT))).all())
        manager = await s.get(Manager, result["manager_id"])
    assert n == 1 and manager.no_interest_at is not None
    assert (await _contacts())["rows"] == []


async def test_a_different_person_at_the_company_is_still_taken(market) -> None:  # noqa: F811
    result = await _call(market["forschner"], "denkinger", "not_interested")
    async with SessionLocal() as s:
        created = await managers.create_manager(s, tenant_id=DEFAULT, payload=ManagerCreate(
            company_id=result["company_id"], full_name="Max Muster", first_name="Max", last_name="Muster",
            source=ConfidenceSource.PUBLIC_WEB,
        ))
    assert created.stage == "bus_dev" and created.no_interest_at is None


async def test_markt_shows_the_person_as_kein_interesse(market) -> None:  # noqa: F811
    """The Markt card's Ansprechpartner say who is "Kein Interesse"."""
    from app.domain.hub import service as hub
    from app.domain.hub.models import HubJobPosting, HubPostingPayload

    result = await _call(market["linde"], "kraft", "not_interested")
    async with SessionLocal() as s:
        posting = await s.scalar(select(HubJobPosting).where(HubJobPosting.hub_company_id == market["linde"],
                                                             HubJobPosting.is_active))
        s.add(HubPostingPayload(hub_job_posting_id=posting.id,
                                description="Ihre Ansprechpartnerin: Frau Anna Kraft, Tel. 030 2295 0"))
        await s.commit()
        link = await s.scalar(select(HubCompanyLink).where(HubCompanyLink.tenant_id == DEFAULT))
        assert link.company_id == result["company_id"]
        page = await hub.company_contacts(s, tenant_id=DEFAULT, hub_company_id=market["linde"])
    kraft = next(c for c in page["contacts"] if c["last_name"] == "Kraft")
    assert kraft["manager_id"] == result["manager_id"]
    assert kraft["no_interest_at"] is not None


@pytest.mark.parametrize("outcome", ["call_back", "meeting_booked", "not_reached"])
async def test_other_outcomes_keep_the_lead_on_the_list(market, outcome) -> None:  # noqa: F811
    await _call(market["forschner"], "denkinger", outcome,
                next_action_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1))
    assert len((await _contacts())["rows"]) == 1
