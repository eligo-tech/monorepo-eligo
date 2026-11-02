"""The agency finder: nightly profiles, Eligo-only reads, adoption.

Profiles are DERIVED from the private-recruiter corpus and rebuilt by the
nightly job (machine-only). The reads are visible to the workspaces on
`agency_finder_tenants` and nobody else — fail-closed: an empty list means
nobody, unlike the interviewer allowlist where empty means everyone.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import agencies, suppression
from app.domain.hub.models import (
    EMPLOYER,
    PRIVATE_RECRUITER,
    HubAgencyProfile,
    HubCompany,
    HubJobPosting,
    HubPostingPayload,
)
from app.domain.hub.resolution import normalize_company_name
from app.main import app

NOW = dt.datetime.now(dt.UTC)
_AGENCY = "Zebrafink Personalberatung GmbH"


async def _company(s, name: str, kind: str = PRIVATE_RECRUITER, city: str = "Leipzig") -> HubCompany:
    row = HubCompany(
        name=name,
        normalized_name=normalize_company_name(name),
        dedupe_key=f"{kind}:{name}:{city}",
        resolution_basis="name_place",
        city=city,
        region="SACHSEN",
        source="bundesagentur",
        kind=kind,
        open_postings_count=0,
        suspected_natural_person=False,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    s.add(row)
    await s.flush()
    return row


async def _posting(s, company: HubCompany, title: str, field: str, text: str | None = None, days_ago: int = 1) -> None:
    segment = company.kind
    s.add(
        HubJobPosting(
            hub_company_id=company.id,
            title=title,
            berufsfeld=field,
            region="SACHSEN",
            city=company.city,
            source="bundesagentur",
            external_id=f"x-{uuid.uuid4().hex[:8]}",
            content_hash=uuid.uuid4().hex,
            segment=segment,
            posted_at=NOW - dt.timedelta(days=days_ago),
            first_seen_at=NOW,
            last_seen_at=NOW,
            is_active=True,
            payload=HubPostingPayload(raw={}, description=text),
        )
    )


async def _seed() -> None:
    async with SessionLocal() as s:
        leipzig = await _company(s, f"{_AGENCY} - Niederlassung Leipzig")
        dresden = await _company(s, f"{_AGENCY} - Niederlassung Dresden", city="Dresden")
        await _posting(
            s, leipzig, "Projektleiter (m/w/d)", "Bau",
            "Unser Mandant ist ein Bauunternehmen. Kontakt: Frau Jana Beispiel, "
            "j.beispiel@zebrafink-personal.de",
        )
        await _posting(s, dresden, "Recruiter (m/w/d) für unser Team", "Personalwesen", days_ago=20)
        # A client named in an agency's ad: also in the corpus as an employer.
        await _posting(s, await _company(s, "KHS GmbH"), "Servicetechniker", "Technik")
        await _posting(s, await _company(s, "KHS GmbH", kind=EMPLOYER), "Elektroniker", "Technik")
        await s.commit()


async def _refresh() -> dict:
    async with SessionLocal() as s:
        return await agencies.refresh_profiles(s)


@pytest.fixture
def eligo(monkeypatch):
    monkeypatch.setattr(settings, "agency_finder_tenants", str(settings.default_tenant_id))


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# --- the nightly rebuild -------------------------------------------------------


async def test_branches_become_one_profile_with_its_evidence() -> None:
    await _seed()
    outcome = await _refresh()
    async with SessionLocal() as s:
        zebra = await s.scalar(select(HubAgencyProfile).where(HubAgencyProfile.group_key == "zebrafink personalberatung"))
        khs = await s.scalar(select(HubAgencyProfile).where(HubAgencyProfile.group_key == "khs"))
    assert outcome["profiles"] == 2
    assert len(zebra.company_ids) == 2 and zebra.open_postings == 2
    assert zebra.verdict == "agency"
    codes = {r["code"] for r in zebra.reasons}
    assert {"name", "client_phrase", "mail_domain", "hiring_recruiters", "new_7d"} <= codes
    mail = next(r for r in zebra.reasons if r["code"] == "mail_domain")
    assert mail["evidence"]["domains"] == ["zebrafink-personal.de"]
    assert khs.verdict == "client"
    # No person in the profile: the contact stays in the ad text.
    assert "Beispiel" not in str(zebra.reasons)


async def test_the_rebuild_replaces_rather_than_accumulates() -> None:
    await _seed()
    await _refresh()
    await _refresh()
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(HubAgencyProfile)) == 2


async def test_suppressing_an_agency_removes_its_profile_at_once() -> None:
    await _seed()
    await _refresh()
    async with SessionLocal() as s:
        await suppression.suppress(s, scope="company", name=f"{_AGENCY} - Niederlassung Leipzig", reason="objection")
        keys = (await s.execute(select(HubAgencyProfile.group_key))).scalars().all()
    assert keys == ["khs"]


# --- who may see it ------------------------------------------------------------


async def test_nobody_sees_agencies_while_the_allowlist_is_empty() -> None:
    await _seed()
    await _refresh()
    async with _client() as c:
        responses = [await c.get("/api/v1/hub/agencies")]
        async with SessionLocal() as s:
            one = await s.scalar(select(HubAgencyProfile.id))
        responses += [
            await c.get(f"/api/v1/hub/agencies/{one}"),
            await c.post(f"/api/v1/hub/agencies/{one}/adopt", json={}),
        ]
    assert [r.status_code for r in responses] == [404, 404, 404]
    assert all("Zebrafink" not in r.text for r in responses)


async def test_another_workspace_gets_404(monkeypatch) -> None:
    monkeypatch.setattr(settings, "agency_finder_tenants", str(uuid.uuid4()))
    await _seed()
    await _refresh()
    async with _client() as c:
        response = await c.get("/api/v1/hub/agencies")
    assert response.status_code == 404


async def test_eligo_sees_agencies_ranked_and_clients_only_on_request(eligo) -> None:
    await _seed()
    await _refresh()
    async with _client() as c:
        default = (await c.get("/api/v1/hub/agencies")).json()
        clients = (await c.get("/api/v1/hub/agencies?verdict=client")).json()
    assert [a["group_key"] for a in default["items"]] == ["zebrafink personalberatung"]
    assert default["items"][0]["score"] > 0 and default["items"][0]["reasons"]
    assert [a["name"] for a in clients["items"]] == ["KHS GmbH"]


async def test_the_detail_shows_branches_ads_and_ad_contacts(eligo) -> None:
    await _seed()
    await _refresh()
    async with SessionLocal() as s:
        zebra = await s.scalar(select(HubAgencyProfile).where(HubAgencyProfile.verdict == "agency"))
    async with _client() as c:
        detail = (await c.get(f"/api/v1/hub/agencies/{zebra.id}")).json()
    assert {b["city"] for b in detail["branches"]} == {"Leipzig", "Dresden"}
    assert len(detail["postings"]) == 2
    assert [p["full_name"] for p in detail["contacts"]["contacts"]] == ["Jana Beispiel"]


async def test_adopting_an_agency_puts_it_in_the_crm_once(eligo) -> None:
    await _seed()
    await _refresh()
    async with SessionLocal() as s:
        zebra = await s.scalar(select(HubAgencyProfile).where(HubAgencyProfile.verdict == "agency"))
    async with _client() as c:
        first = await c.post(f"/api/v1/hub/agencies/{zebra.id}/adopt", json={})
        again = await c.post(f"/api/v1/hub/agencies/{zebra.id}/adopt", json={})
    assert first.status_code == 201, first.text
    assert first.json()["hub_company_id"] == str(zebra.primary_company_id)
    assert again.status_code == 409


async def test_a_profile_whose_companies_are_gone_is_not_shown(eligo) -> None:
    # Between a deletion and the next rebuild, the read re-checks existence.
    await _seed()
    await _refresh()
    async with SessionLocal() as s:
        zebra = await s.scalar(select(HubAgencyProfile).where(HubAgencyProfile.verdict == "agency"))
        zebra.primary_company_id = uuid.uuid4()
        await s.commit()
    async with _client() as c:
        listing = (await c.get("/api/v1/hub/agencies")).json()
        detail = await c.get(f"/api/v1/hub/agencies/{zebra.id}")
    assert listing["items"] == [] and detail.status_code == 404


async def test_a_firm_listed_as_an_employer_under_its_full_name_is_a_client() -> None:
    # Group key "piening", employer row "piening saarbruecken": still the same firm.
    async with SessionLocal() as s:
        await _posting(s, await _company(s, "Piening GmbH (Saarbrücken)"), "Lagerist", "Logistik")
        await _posting(s, await _company(s, "Piening GmbH (Saarbrücken)", kind=EMPLOYER), "Lagerist", "Logistik")
        await s.commit()
    await _refresh()
    async with SessionLocal() as s:
        profile = await s.scalar(select(HubAgencyProfile).where(HubAgencyProfile.group_key == "piening"))
    assert "also_employer" in {r["code"] for r in profile.reasons}


async def test_an_expired_ad_is_not_evidence() -> None:
    async with SessionLocal() as s:
        row = await _company(s, "Neutral GmbH")
        await _posting(s, row, "Lagerist", "Logistik", "Unser Mandant ist ein Logistiker.")
        await s.flush()
        posting = await s.scalar(select(HubJobPosting).where(HubJobPosting.hub_company_id == row.id))
        posting.is_active = False
        await _posting(s, row, "Fahrer", "Logistik")
        await s.commit()
    await _refresh()
    async with SessionLocal() as s:
        profile = await s.scalar(select(HubAgencyProfile))
    assert "client_phrase" not in {r["code"] for r in profile.reasons}


async def test_pages_come_from_the_database_in_order(eligo) -> None:
    async with SessionLocal() as s:
        for i in range(5):
            await _posting(s, await _company(s, f"Agentur{i} Personal GmbH", city=f"Ort{i}"), "Lagerist", "Logistik")
        await s.commit()
    await _refresh()
    async with _client() as c:
        first = (await c.get("/api/v1/hub/agencies?limit=2")).json()["items"]
        second = (await c.get("/api/v1/hub/agencies?limit=2&offset=2")).json()["items"]
        logistik = (await c.get("/api/v1/hub/agencies?berufsfeld=Logistik&limit=10")).json()["items"]
    assert len(first) == len(second) == 2
    assert not {a["id"] for a in first} & {a["id"] for a in second}
    assert len(logistik) == 5
