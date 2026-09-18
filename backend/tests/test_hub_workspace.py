"""The workspace: watched employers, and the people their public ads name.

Both reads work over data already in the corpus. Nothing here fetches, and
nothing is stored until a recruiter adopts a contact into `managers`.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.core.database import SessionLocal
from app.domain.common.enums import ConfidenceSource
from app.domain.hub import service
from app.domain.hub.models import HubCompany, HubJobPosting, HubPostingPayload
from app.domain.managers.models import Manager

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = dt.datetime.now(dt.UTC)


def _company(city: str) -> HubCompany:
    return HubCompany(
        name="Sto SE & Co. KGaA",
        normalized_name="sto",
        dedupe_key=f"k-{uuid.uuid4()}",
        resolution_basis="name_place",
        city=city,
        source="bundesagentur",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def _posting(company: HubCompany, title: str, text: str | None, *, days_ago: int, active: bool = True) -> HubJobPosting:
    posting = HubJobPosting(
        hub_company_id=company.id,
        title=title,
        source="bundesagentur",
        external_id=f"10001-{uuid.uuid4().hex[:10]}-S",
        posted_at=NOW - dt.timedelta(days=days_ago),
        first_seen_at=NOW,
        last_seen_at=NOW,
        is_active=active,
        content_hash=uuid.uuid4().hex,
    )
    posting.payload = HubPostingPayload(raw={}, description=text)
    return posting


@pytest.fixture
async def employer() -> tuple[uuid.UUID, uuid.UUID]:
    """One employer, two sites; contacts spread across both."""
    async with SessionLocal() as s:
        stuehlingen, weizen = _company("Stühlingen"), _company("Weizen")
        s.add_all([stuehlingen, weizen])
        await s.flush()
        s.add_all(
            [
                _posting(
                    stuehlingen,
                    "Personalreferent (m/w/d)",
                    "Ihre Ansprechpartnerin: Frau Sophie Bennicke, Bereich Personal\n"
                    "Tel. +49 7744 57 1660\nBewerbung an bewerbung@sto.com",
                    days_ago=1,
                ),
                _posting(
                    weizen,
                    "Lagerist (m/w/d)",
                    # Same person, formal form, in the other site's ad.
                    "Fragen beantwortet Frau Bennicke gerne. bewerbung@sto.com",
                    days_ago=3,
                ),
                _posting(
                    weizen,
                    "Schichtleiter (m/w/d)",
                    "Für fachliche Fragen: Herr Tobias Pramberger (Teamleitung Produktion)",
                    days_ago=40,
                    active=False,
                ),
                # An ad without text yet — counted, not read.
                _posting(stuehlingen, "Elektriker (m/w/d)", None, days_ago=2),
            ]
        )
        await s.commit()
        return stuehlingen.id, weizen.id


async def test_workspace_rolls_an_employer_up_across_its_sites(employer) -> None:
    anchor, _ = employer
    async with SessionLocal() as s:
        await service.track_company(s, tenant_id=TENANT, hub_company_id=anchor, relationship="watching")
        rows = await service.workspace_companies(s, tenant_id=TENANT)
    assert len(rows) == 1
    row = rows[0]
    assert row["sites"] == 2
    assert sorted(row["cities"]) == ["Stühlingen", "Weizen"]
    assert row["open_roles"] == 3  # the closed ad does not count
    assert row["company_id"] is None


async def test_workspace_is_per_tenant_and_hides_ignored(employer) -> None:
    anchor, _ = employer
    async with SessionLocal() as s:
        await service.track_company(s, tenant_id=OTHER, hub_company_id=anchor, relationship="ignored")
        assert await service.workspace_companies(s, tenant_id=TENANT) == []
        assert await service.workspace_companies(s, tenant_id=OTHER) == []


async def test_contacts_are_read_from_every_site_and_merged(employer) -> None:
    anchor, _ = employer
    async with SessionLocal() as s:
        result = await service.company_contacts(s, tenant_id=TENANT, hub_company_id=anchor)
    assert result is not None
    by_last = {c["last_name"]: c for c in result["contacts"]}
    assert set(by_last) == {"Bennicke", "Pramberger"}

    bennicke = by_last["Bennicke"]
    assert bennicke["full_name"] == "Sophie Bennicke"
    assert bennicke["mention_count"] == 2
    assert bennicke["phone"] == "+49 7744 57 1660"
    assert bennicke["role_title"] == "Bereich Personal"
    # Evidence points at the ad, so a recruiter can check the parser.
    assert all(e["url"].startswith("https://www.arbeitsagentur.de/") for e in bennicke["evidence"])
    assert "Sophie Bennicke" in bennicke["evidence"][0]["quote"]
    # Most-named first: that is the talent-acquisition desk.
    assert result["contacts"][0]["last_name"] == "Bennicke"

    # A closed ad still names who hired for that team.
    assert by_last["Pramberger"]["role_title"] == "Teamleitung Produktion"
    assert by_last["Pramberger"]["evidence"][0]["is_active"] is False

    assert result["mailboxes"] == [{"email": "bewerbung@sto.com", "mention_count": 2}]
    assert (result["postings_scanned"], result["postings_with_text"]) == (4, 3)


async def test_contacts_mark_who_the_workspace_already_holds(employer) -> None:
    anchor, _ = employer
    async with SessionLocal() as s:
        company, _, manager = await service.adopt_company(
            s,
            tenant_id=TENANT,
            hub_company_id=anchor,
            manager={
                "full_name": "Sophie Bennicke",
                "source": ConfidenceSource.PUBLIC_WEB.value,
                "source_detail": "https://www.arbeitsagentur.de/jobsuche/jobdetail/x",
            },
        )
        assert manager is not None and manager.art14_outstanding

        result = await service.company_contacts(s, tenant_id=TENANT, hub_company_id=anchor)
        assert result["company_id"] == company.id
        held = {c["last_name"]: c["manager_id"] for c in result["contacts"]}
        assert held == {"Bennicke": manager.id, "Pramberger": None}

        # Another workspace sees the same public contacts, none of them held.
        other = await service.company_contacts(s, tenant_id=OTHER, hub_company_id=anchor)
        assert other["company_id"] is None
        assert all(c["manager_id"] is None for c in other["contacts"])
        # And the adopted manager stays in the adopting workspace only.
        assert (await s.get(Manager, manager.id)).tenant_id == TENANT


async def test_contacts_for_an_unknown_company() -> None:
    async with SessionLocal() as s:
        assert await service.company_contacts(s, tenant_id=TENANT, hub_company_id=uuid.uuid4()) is None


async def test_routes(employer) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    anchor, _ = employer
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        await client.put(f"/api/v1/hub/companies/{anchor}/track", json={"relationship": "watching"})
        workspace = (await client.get("/api/v1/hub/workspace")).json()
        assert [w["name"] for w in workspace] == ["Sto SE & Co. KGaA"]
        contacts = await client.get(f"/api/v1/hub/companies/{anchor}/contacts")
        assert contacts.status_code == 200
        assert contacts.json()["contacts"][0]["full_name"] == "Sophie Bennicke"
        missing = await client.get(f"/api/v1/hub/companies/{uuid.uuid4()}/contacts")
        assert missing.status_code == 404
