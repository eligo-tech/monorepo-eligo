"""ELI-65: a lead entered by hand — from a job ad or a LinkedIn profile.

Leads were only ever people a public ad names, taken from Markt. Panam also
works jobs Markt does not hold, and wants those leads on the same list so the
tracking adds up. The form asks for little: the job, the contact's name and
title, the company, e-mail and number if known, and the link it came from.

What must hold:
  * the row is a lead (stage `bus_dev`) of THIS workspace, at the workspace's
    own company (an existing one by name, else a new one);
  * its provenance says "entered by hand" plus the link, and — a person's data
    the subject did not give us — the Art. 14 notice is owed;
  * the job shows on the Leads row and the lead page; the row is marked manual;
  * the same name at the same company is shown, not created a second time;
  * the old rule still holds for everything else: managers typed in or
    imported elsewhere do not appear under Leads.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.hub import call_list
from app.domain.managers import service as managers
from app.domain.managers.models import Manager
from app.domain.managers.schemas import LeadCreate, ManagerCreate
from app.domain.verification.models import Receipt

DEFAULT = settings.default_tenant_id
API = settings.api_v1_prefix

LEAD = {
    "job_title": "Senior Java Entwickler (m/w/d)",
    "source_url": "https://www.stepstone.de/stellenangebote--Senior-Java-12345.html",
    "full_name": "Anna Kraft",
    "role_title": "Head of Engineering",
    "company_name": "Nordlicht Software GmbH",
    "email": "anna.kraft@nordlicht.example",
    "phone": "+49 40 123456",
}


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _contacts(**kw) -> dict:
    async with SessionLocal() as s:
        return await call_list.contacts(s, tenant_id=kw.pop("tenant", DEFAULT), **kw)


async def test_a_lead_by_hand_is_a_lead_with_its_job_and_provenance() -> None:
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json=LEAD)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["stage"] == "bus_dev"
    assert body["full_name"] == "Anna Kraft"
    assert body["first_name"] == "Anna" and body["last_name"] == "Kraft"
    assert body["role_title"] == "Head of Engineering"
    assert body["email"] == LEAD["email"] and body["phone"] == LEAD["phone"]
    assert body["lead_job_title"] == LEAD["job_title"]
    # Entered by a person from a source the subject did not give us.
    assert body["source"] == ConfidenceSource.THIRD_PARTY_SOURCE.value
    assert body["source_detail"] == LEAD["source_url"]
    assert body["art14_outstanding"] is True
    assert body["manual_lead"] is True

    page = await _contacts()
    (row,) = page["rows"]
    assert row["manager_id"] == uuid.UUID(body["id"])
    assert row["company_name"] == "Nordlicht Software GmbH"
    assert row["manual"] is True
    # The job, linking to the ad it came from.
    assert row["jobs"][0]["title"] == LEAD["job_title"]
    assert row["jobs"][0]["url"] == LEAD["source_url"]

    async with SessionLocal() as s:
        companies = (await s.scalars(select(Company).where(Company.tenant_id == DEFAULT))).all()
        assert [co.name for co in companies] == ["Nordlicht Software GmbH"]
        # One receipt for the act — references only, never the person.
        receipts = (await s.scalars(select(Receipt).where(Receipt.subject_id == body["id"]))).all()
        assert len(receipts) == 1
        text = f"{receipts[0].summary} {receipts[0].payload}"
        assert "Kraft" not in text and "nordlicht" not in text.lower() and "stepstone" not in text


async def test_the_lead_page_carries_the_job() -> None:
    async with _api() as c:
        made = (await c.post(f"{API}/managers/leads", json=LEAD)).json()
        got = (await c.get(f"{API}/managers/{made['id']}")).json()
    assert got["lead_job_title"] == LEAD["job_title"]
    assert got["manual_lead"] is True


async def test_an_existing_company_of_that_name_is_used() -> None:
    async with SessionLocal() as s:
        own = Company(tenant_id=DEFAULT, name="Nordlicht Software GmbH")
        # Another workspace's company of the same name is not this one's.
        s.add_all([own, Company(tenant_id=uuid.uuid4(), name="Nordlicht Software GmbH")])
        await s.commit()
        own_id = own.id
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json={**LEAD, "company_name": "  nordlicht software gmbh "})
    assert r.status_code == 201, r.text
    assert r.json()["company_id"] == str(own_id)
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count()).select_from(Company).where(Company.tenant_id == DEFAULT))
    assert n == 1


async def test_the_same_person_at_the_same_company_is_shown_not_doubled() -> None:
    async with _api() as c:
        first = (await c.post(f"{API}/managers/leads", json=LEAD)).json()
        again = await c.post(
            f"{API}/managers/leads",
            json={**LEAD, "job_title": "Teamlead Backend", "full_name": "anna  kraft", "email": None},
        )
    assert again.status_code == 409
    detail = again.json()["detail"]
    assert detail["code"] == "lead_exists"
    assert detail["manager_id"] == first["id"]
    assert detail["stage"] == "bus_dev"
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count()).select_from(Manager))
    assert n == 1


async def test_a_manager_already_held_is_shown_and_not_moved_into_leads() -> None:
    async with SessionLocal() as s:
        company = Company(tenant_id=DEFAULT, name="Nordlicht Software GmbH")
        s.add(company)
        await s.commit()
        held = await managers.create_manager(
            s, tenant_id=DEFAULT,
            payload=ManagerCreate(company_id=company.id, full_name="Anna Kraft", first_name="Anna", last_name="Kraft"),
        )
        held_id = held.id
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json=LEAD)
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "lead_exists", "manager_id": str(held_id), "stage": "manager", "full_name": "Anna Kraft",
        # ELI-77: matched by name at that company, not by a profile link.
        "match": "name",
    }
    # The old rule stands for every other way in: a manager typed in or
    # imported is not a lead.
    assert (await _contacts())["rows"] == []


async def test_a_linkedin_profile_is_the_persons_profile_not_the_jobs_ad() -> None:
    url = "https://www.linkedin.com/in/anna-kraft-123/"
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json={**LEAD, "source_url": url})
    assert r.status_code == 201, r.text
    assert r.json()["linkedin_url"] == url
    assert r.json()["source_detail"] == url
    (row,) = (await _contacts())["rows"]
    assert row["jobs"][0] == {
        "title": LEAD["job_title"], "location": None, "url": None, "posting_id": None, "job_id": None,
    }


async def test_without_a_link_the_provenance_still_says_by_hand() -> None:
    async with _api() as c:
        r = await c.post(
            f"{API}/managers/leads",
            json={"job_title": "Controller", "full_name": "Ben Ott", "company_name": "Ott KG"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source_detail"] == "von Hand angelegt"
    assert body["email"] is None and body["phone"] is None and body["role_title"] is None
    assert body["art14_outstanding"] is True


async def test_job_name_and_company_are_required_and_the_link_must_be_a_link() -> None:
    async with _api() as c:
        for missing in ("job_title", "full_name", "company_name"):
            r = await c.post(f"{API}/managers/leads", json={**LEAD, missing: "  "})
            assert r.status_code == 422, missing
        r = await c.post(f"{API}/managers/leads", json={**LEAD, "source_url": "javascript:alert(1)"})
        assert r.status_code == 422
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(Manager)) == 0
        assert await s.scalar(select(func.count()).select_from(Company)) == 0


async def test_markt_leads_are_not_marked_manual() -> None:
    async with SessionLocal() as s:
        company = Company(tenant_id=DEFAULT, name="Forschner GmbH")
        s.add(company)
        await s.commit()
        await managers.create_manager(
            s, tenant_id=DEFAULT,
            payload=ManagerCreate(company_id=company.id, full_name="Leonie Denkinger", last_name="Denkinger",
                                  source=ConfidenceSource.PUBLIC_WEB, source_detail="https://example.org/ad"),
        )
    (row,) = (await _contacts())["rows"]
    assert row["manual"] is False


async def test_service_keeps_the_lead_in_its_workspace() -> None:
    other = uuid.uuid4()
    async with SessionLocal() as s:
        lead = await managers.create_manual_lead(
            s, tenant_id=other, payload=LeadCreate(**LEAD), actor=None,
        )
        company = await s.get(Company, lead.company_id)
        assert company.tenant_id == other and lead.tenant_id == other
    assert (await _contacts())["rows"] == []
    assert len((await _contacts(tenant=other))["rows"]) == 1


async def test_a_salutation_or_title_is_not_a_first_name() -> None:
    """"Frau Kraft" copied from an ad is the Anna Kraft already held."""
    async with _api() as c:
        first = (await c.post(f"{API}/managers/leads", json=LEAD)).json()
        again = await c.post(f"{API}/managers/leads", json={**LEAD, "full_name": "Frau Kraft"})
        titled = await c.post(
            f"{API}/managers/leads",
            json={**LEAD, "full_name": "Herr Dr. Jonas Weber", "company_name": "Weber AG"},
        )
    assert again.status_code == 409 and again.json()["detail"]["manager_id"] == first["id"]
    assert titled.status_code == 201, titled.text
    assert titled.json()["first_name"] == "Jonas" and titled.json()["last_name"] == "Weber"
    assert titled.json()["full_name"] == "Herr Dr. Jonas Weber"


def test_links_fit_their_columns_and_keep_one_spelling() -> None:
    import pytest
    from pydantic import ValidationError

    from app.domain.managers.models import Manager as M

    # A bare host gets its scheme, and the prefixed link still fits.
    assert LeadCreate(**{**LEAD, "source_url": "www.jobs.example/1"}).source_url == "https://www.jobs.example/1"
    assert LeadCreate(**{**LEAD, "source_url": "HTTPS://Jobs.Example/1"}).source_url == "https://Jobs.Example/1"
    width = M.__table__.c.source_detail.type.length
    with pytest.raises(ValidationError):
        LeadCreate(**{**LEAD, "source_url": "www.x.de/" + "a" * (width - 9)})
    # A profile link too long for the profile column stays the source only.
    long_profile = "https://www.linkedin.com/in/anna?" + "x" * 300
    assert managers.profile_links(long_profile) == {}
    assert managers.profile_links("https://de.linkedin.com/in/anna") == {"linkedin_url": "https://de.linkedin.com/in/anna"}
    assert managers.profile_links("https://www.xing.com/profile/Anna_Kraft") == {
        "xing_url": "https://www.xing.com/profile/Anna_Kraft"}
    assert managers.profile_links("https://jobs.example/1") == {}


async def test_a_failure_after_the_company_leaves_nothing_behind(monkeypatch) -> None:
    from app.domain.verification import service as verification

    async def broken(*_a, **_k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(verification, "append_receipt", broken)
    async with SessionLocal() as s:
        try:
            await managers.create_manual_lead(s, tenant_id=DEFAULT, payload=LeadCreate(**LEAD))
        except RuntimeError:
            await s.rollback()
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(Company)) == 0
        assert await s.scalar(select(func.count()).select_from(Manager)) == 0


async def test_someone_erased_here_is_not_entered_again_by_hand(monkeypatch) -> None:
    import datetime as dt

    from app.domain.erasure import service as erasure

    monkeypatch.setattr(settings, "suppression_key", "k" * 40)
    async with SessionLocal() as s:
        company = Company(tenant_id=DEFAULT, name="Altkunde GmbH")
        s.add(company)
        await s.flush()
        gone = Manager(tenant_id=DEFAULT, company_id=company.id, full_name="Hans Chef", email="hans.chef@alt.example")
        s.add(gone)
        await s.commit()
        gone_id = gone.id
    async with SessionLocal() as s:
        await erasure.erase_manager(s, tenant_id=DEFAULT, manager_id=gone_id, confirm_name="hans chef",
                                    reason="erasure", requested_on=dt.date(2026, 11, 2),
                                    actor_user_id="u", actor_name="A")
        await s.commit()
    async with _api() as c:
        by_mail = await c.post(f"{API}/managers/leads", json={
            **LEAD, "full_name": "Hans Chef", "company_name": "Neue Firma AG", "email": "Hans.Chef@alt.example"})
        by_name = await c.post(f"{API}/managers/leads", json={
            **LEAD, "full_name": "Hans Chef", "company_name": "Altkunde GmbH", "email": None, "phone": None})
    assert by_mail.status_code == 409 and by_mail.json()["detail"]["code"] == "suppressed"
    assert by_name.status_code == 409 and by_name.json()["detail"]["code"] == "suppressed"
    async with SessionLocal() as s:
        names = (await s.scalars(select(Company.name).where(Company.tenant_id == DEFAULT))).all()
    # Nothing half-made: no company was created for the refused lead.
    assert names == ["Altkunde GmbH"]
