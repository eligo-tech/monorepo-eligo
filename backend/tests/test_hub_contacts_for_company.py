"""Contacts read out of an employer's public ads.

Works over data already in the corpus: nothing here fetches, and nothing is
stored until a recruiter adopts a contact into `managers`. (The flat
"workspace" listing this file also covered is gone — projects replaced it.)
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
    # The recruiter sees before dialling whether it reaches the person (ELI-22).
    assert bennicke["phone_kind"] == "direct"
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
        contacts = await client.get(f"/api/v1/hub/companies/{anchor}/contacts")
        assert contacts.status_code == 200
        assert contacts.json()["contacts"][0]["full_name"] == "Sophie Bennicke"
        missing = await client.get(f"/api/v1/hub/companies/{uuid.uuid4()}/contacts")
        assert missing.status_code == 404


async def test_contact_data_without_a_recognised_name_is_still_shown(employer) -> None:
    # ELI-25 safety net: a number in an ad is never lost because the parser
    # could not name its owner. A named person's number is not repeated.
    anchor, weizen = employer
    async with SessionLocal() as s:
        company = await s.get(HubCompany, weizen)
        s.add_all(
            [
                _posting(
                    company,
                    "Kommissionierer (m/w/d)",
                    "Für Rückfragen erreichen Sie uns unter 07141 643660 oder per WhatsApp unter 01525 7677699.",
                    days_ago=2,
                ),
                _posting(company, "Fahrer (m/w/d)", "WhatsApp: 01525 7677699", days_ago=5),
            ]
        )
        await s.commit()
        result = await service.company_contacts(s, tenant_id=TENANT, hub_company_id=anchor)
    unnamed = {u["value"]: u for u in result["unnamed"]}
    assert set(unnamed) == {"07141 643660", "01525 7677699"}
    assert unnamed["01525 7677699"]["mention_count"] == 2
    assert unnamed["01525 7677699"]["kind"] == "phone"
    assert unnamed["01525 7677699"]["phone_kind"] == "direct"
    assert unnamed["01525 7677699"]["url"].startswith("https://www.arbeitsagentur.de/")
    assert "WhatsApp" in unnamed["01525 7677699"]["quote"]
    # Most-seen first.
    assert result["unnamed"][0]["value"] == "01525 7677699"


async def test_a_person_the_model_found_is_shown_and_marked(employer) -> None:
    # ELI-25 layer 2: the nightly model pass stored a person the rules missed;
    # the card shows them, says so, and no longer lists their number as unnamed.
    from app.domain.hub.models import HubAdContact

    anchor, weizen = employer
    async with SessionLocal() as s:
        company = await s.get(HubCompany, weizen)
        posting = _posting(
            company,
            "PTA (m/w/d)",
            "Ihre Bewerbung richten Sie bitte direkt an Hussien Bader: h.bader@apotheke-am-hit.de oder 0711 123456.",
            days_ago=1,
        )
        s.add(posting)
        await s.flush()
        s.add(
            HubAdContact(
                hub_job_posting_id=posting.id, hub_company_id=company.id, person_key="hussien|bader",
                full_name="Hussien Bader", first_name="Hussien", last_name="Bader", salutation=None,
                role_title=None, phone="0711 123456", phone_kind="direct", email="h.bader@apotheke-am-hit.de",
                quote="Ihre Bewerbung richten Sie bitte direkt an Hussien Bader: h.bader@apotheke-am-hit.de",
                text_source="ad", source_fetched_at=NOW, found_by="model",
            )
        )
        await s.commit()
        result = await service.company_contacts(s, tenant_id=TENANT, hub_company_id=anchor)
    by_last = {c["last_name"]: c for c in result["contacts"]}
    assert by_last["Bader"]["found_by"] == "model"
    assert by_last["Bader"]["email"] == "h.bader@apotheke-am-hit.de"
    assert by_last["Bader"]["evidence"][0]["url"].startswith("https://www.arbeitsagentur.de/")
    assert by_last["Bennicke"]["found_by"] == "rules"
    assert "0711 123456" not in {u["value"] for u in result["unnamed"]}


async def test_the_recruiters_mobile_is_on_the_person_not_unnamed(employer) -> None:
    anchor, weizen = employer
    async with SessionLocal() as s:
        company = await s.get(HubCompany, weizen)
        s.add(
            _posting(
                company,
                "Embedded Software Engineer (m/w/d)",
                "Für Fragen steht Janet Jürgens telefonisch unter +49 5491 666 2834 oder auch über WhatsApp "
                "unter +49 151 51446810 gerne zur Verfügung.",
                days_ago=1,
            )
        )
        await s.commit()
        result = await service.company_contacts(s, tenant_id=TENANT, hub_company_id=anchor)
    jurgens = next(c for c in result["contacts"] if c["last_name"] == "Jürgens")
    assert (jurgens["phone"], jurgens["mobile"]) == ("+49 5491 666 2834", "+49 151 51446810")
    assert "+49 151 51446810" not in {u["value"] for u in result["unnamed"]}


# --- ELI-30: the switchboard from the employer's own Impressum ---------------


async def _site_check(company_id: uuid.UUID, status: str, facts: dict) -> None:
    from app.domain.hub.employer_sites import group_key
    from app.domain.hub.models import HubSiteCheck

    async with SessionLocal() as s:
        s.add(HubSiteCheck(
            domain="sto.de", group_key=group_key(company_id), hub_company_id=company_id, status=status,
            impressum_url="https://sto.de/impressum", facts=facts, checked_at=NOW,
        ))
        await s.commit()


async def test_a_verified_impressum_switchboard_is_on_the_card(employer) -> None:
    _, weizen = employer  # checked on a sibling site, shown on the anchor's card
    await _site_check(weizen, "verified", {
        "phone": "+49 7744 57-0", "vat_id": "DE142215600", "register": "HRA 270002", "register_court": "Freiburg",
    })
    async with SessionLocal() as s:
        card = await service.company_contacts(s, tenant_id=TENANT, hub_company_id=employer[0])
    assert card["switchboard"] == {
        "phone": "+49 7744 57-0", "vat_id": "DE142215600", "register": "HRA 270002",
        "register_court": "Freiburg", "impressum_url": "https://sto.de/impressum", "domain": "sto.de",
        "checked_at": card["switchboard"]["checked_at"],
    }


async def test_someone_elses_impressum_is_never_on_the_card(employer) -> None:
    anchor, _ = employer
    await _site_check(anchor, "not_named", {})
    async with SessionLocal() as s:
        card = await service.company_contacts(s, tenant_id=TENANT, hub_company_id=anchor)
    assert card["switchboard"] is None


async def test_the_route_carries_the_switchboard(employer) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    anchor, _ = employer
    await _site_check(anchor, "verified", {"phone": "+49 7744 57-0"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        body = (await client.get(f"/api/v1/hub/companies/{anchor}/contacts")).json()
    assert body["switchboard"]["phone"] == "+49 7744 57-0"
    assert body["switchboard"]["impressum_url"] == "https://sto.de/impressum"
