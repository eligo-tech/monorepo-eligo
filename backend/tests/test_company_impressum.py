"""A workspace company's website, VAT id and register from its Impressum (ELI-39).

`companies/impressum.py`: for a company Markt cannot answer for (not linked,
or linked without a verified Impressum), the website comes from data the
workspace already holds — the company's own `domain`, else its contacts'
company mail domains — and its Impressum is read by the employer check's
fetcher and parser. Facts are kept only when the Impressum names THIS company
as operator, every value re-checks against the fetched text, and the write
goes through the verification gate (receipts, provenance record).

Asserted on what is stored and on the requests that actually left (the
recording fetcher). Fixtures are real Impressum pages (`fixtures/impressum/`).
"""

from __future__ import annotations

import datetime as dt
import pathlib
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.companies import impressum, service
from app.domain.companies.models import Company
from app.domain.hub import sites
from app.domain.hub.call_list import company_switchboards
from app.domain.hub.models import EMPLOYER, HubCompany, HubCompanyLink, HubSiteCheck
from app.domain.hub.resolution import normalize_company_name
from app.domain.managers.models import Manager
from app.domain.verification.models import EnrichmentRecord, Receipt

FX = pathlib.Path(__file__).parent / "fixtures" / "impressum"
NOW = dt.datetime(2026, 11, 15, 9, 0, tzinfo=dt.UTC)


def _html(text: str) -> str:
    return "<html><body>" + "".join(f"<p>{line}</p>" for line in text.split("\n")) + "</body></html>"


class _Fetcher:
    """Answers from URL → (status, html); records every request."""

    def __init__(self, pages: dict[str, tuple[int, str | None]]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def get(self, url: str) -> sites.SitePage:
        self.requested.append(url)
        status, html = self.pages.get(url, (404, None))
        return sites.SitePage(url=url, final_url=url, status=status, html=html)


def _tempton(text: str | None = None) -> dict:
    return {
        "https://tempton.de/": (200, '<a href="/impressum">Impressum</a>'),
        "https://tempton.de/impressum": (200, _html(text or (FX / "tempton_de.txt").read_text())),
    }


async def _company(tenant: uuid.UUID, name: str, *, domain: str | None = None, emails: tuple[str, ...] = ()) -> uuid.UUID:
    async with SessionLocal() as s:
        c = Company(tenant_id=tenant, name=name, domain=domain, source="aifind")
        s.add(c)
        await s.flush()
        for i, email in enumerate(emails):
            s.add(Manager(tenant_id=tenant, company_id=c.id, stage="manager", full_name=f"Max Mustermann {i}", email=email))
        await s.commit()
        return c.id


async def _run(tenant: uuid.UUID, fetcher: _Fetcher, now: dt.datetime = NOW) -> dict:
    async with SessionLocal() as s:
        return await impressum.check_companies(s, tenant_id=tenant, fetcher=fetcher, limit=20, now=now)


async def _get(company_id: uuid.UUID) -> Company:
    async with SessionLocal() as s:
        return await s.get(Company, company_id)


async def test_a_verified_impressum_stores_website_vat_and_register_with_provenance() -> None:
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", domain="https://www.tempton.de/karriere")
    fetcher = _Fetcher(_tempton())
    outcome = await _run(tenant, fetcher)
    company = await _get(cid)
    facts = company.impressum
    assert outcome["checked"] == 1 and outcome["verified"] == 1
    assert facts["status"] == "verified" and facts["domain"] == "tempton.de"
    assert facts["vat_id"] == "DE252406571"
    assert (facts["register"], facts["register_court"]) == ("HRB 28871", "Essen")
    assert facts["impressum_url"] == "https://tempton.de/impressum"
    assert facts["fetched_at"].startswith("2026-11-15")
    assert len(facts["content_sha256"]) == 64
    assert "phone" not in facts and "Mustermann" not in str(facts)  # company facts only
    assert company.domain == "https://www.tempton.de/karriere"  # a recruiter's value is never replaced
    assert all(u.startswith("https://tempton.de/") for u in fetcher.requested)

    async with SessionLocal() as s:
        receipts = (await s.scalars(select(Receipt).where(Receipt.tenant_id == tenant))).all()
        [record] = (await s.scalars(select(EnrichmentRecord).where(EnrichmentRecord.entity_id == cid))).all()
    assert sorted(str(r.action) for r in receipts) == ["verify", "write"]
    assert all(r.subject_id == str(cid) and r.agent == "company_impressum" for r in receipts)
    assert all("DE252406571" not in r.summary + str(r.payload) for r in receipts)  # references only
    assert record.committed and record.field == "impressum"
    assert record.source_detail.startswith("https://tempton.de/impressum @ 2026-11-15")


async def test_the_website_is_found_from_the_contacts_company_mail() -> None:
    tenant = uuid.uuid4()
    cid = await _company(
        tenant, "Tempton Group GmbH",
        emails=("max.mustermann@gmail.com", "m.mustermann@tempton.de", "e.musterfrau@tempton.de"),
    )
    fetcher = _Fetcher(_tempton())
    await _run(tenant, fetcher)
    company = await _get(cid)
    assert company.impressum["status"] == "verified" and company.impressum["vat_id"] == "DE252406571"
    assert company.domain == "tempton.de"  # found and verified: now on the record
    assert not any("gmail" in u for u in fetcher.requested)


async def test_without_a_company_domain_nothing_is_fetched() -> None:
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Muster Bau GmbH", emails=("muster.bau@gmail.com", "info@t-online.de"))
    fetcher = _Fetcher({})
    outcome = await _run(tenant, fetcher)
    company = await _get(cid)
    assert outcome["no_domain"] == 1 and fetcher.requested == []
    assert company.impressum["status"] == "no_domain" and "vat_id" not in company.impressum


async def test_another_firms_impressum_stores_nothing() -> None:
    # The domain a contact's mail names, but its Impressum is TEMPTON's — a
    # parent's or a service provider's page is not this company's.
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Netzfrequenz GmbH", emails=("m.mustermann@tempton.de",))
    await _run(tenant, _Fetcher(_tempton()))
    company = await _get(cid)
    assert company.impressum["status"] == "not_named"
    assert not {"vat_id", "register", "impressum_url"} & set(company.impressum)
    assert company.domain is None
    async with SessionLocal() as s:
        assert (await s.scalars(select(Receipt).where(Receipt.tenant_id == tenant))).all() == []


async def test_a_vat_id_failing_its_check_digit_is_not_stored() -> None:
    tenant = uuid.uuid4()
    page = "Tempton Group GmbH\nAmtsgericht Essen HRB 28871\nUSt-IdNr.: DE252406572"
    cid = await _company(tenant, "Tempton Group GmbH", domain="tempton.de")
    await _run(tenant, _Fetcher(_tempton(page)))
    facts = (await _get(cid)).impressum
    assert facts["status"] == "verified" and "vat_id" not in facts
    assert facts["register"] == "HRB 28871"


async def test_a_value_not_on_the_page_fails_the_postcondition() -> None:
    page = (FX / "tempton_de.txt").read_text()
    ok, _ = impressum.on_page({"vat_id": "DE252406571", "register": "HRB 28871"}, page)
    assert ok
    ok, reason = impressum.on_page({"vat_id": "DE314696624"}, page)
    assert not ok and "vat_id" in reason
    ok, _ = impressum.on_page({"register": "HRB 99999"}, page)
    assert not ok


async def test_a_checked_company_is_not_fetched_again_and_an_error_is_retried_after_a_week() -> None:
    tenant = uuid.uuid4()
    await _company(tenant, "Tempton Group GmbH", domain="tempton.de")
    await _run(tenant, _Fetcher(_tempton()))
    again = _Fetcher(_tempton())
    assert (await _run(tenant, again))["checked"] == 0 and again.requested == []

    other = uuid.uuid4()
    cid = await _company(other, "Tempton Group GmbH", domain="tempton.de")
    await _run(other, _Fetcher({"https://tempton.de/": (503, None)}))
    assert (await _get(cid)).impressum["status"] == "error"
    soon = _Fetcher(_tempton())
    assert (await _run(other, soon, NOW + dt.timedelta(days=2)))["checked"] == 0
    assert (await _run(other, _Fetcher(_tempton()), NOW + dt.timedelta(days=8)))["verified"] == 1


async def test_a_company_markt_already_answers_for_is_not_fetched() -> None:
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", domain="tempton.de")
    async with SessionLocal() as s:
        hub = HubCompany(
            name="Tempton Group GmbH",
            normalized_name=normalize_company_name("Tempton Group GmbH"),
            dedupe_key=f"k-{uuid.uuid4()}", resolution_basis="name_place", source="bundesagentur",
            kind=EMPLOYER, first_seen_at=NOW, last_seen_at=NOW,
        )
        s.add(hub)
        await s.flush()
        s.add(HubSiteCheck(domain="tempton.de", group_key=f"employer:{hub.id}", hub_company_id=hub.id,
                           status="verified", facts={"vat_id": "DE252406571"}, checked_at=NOW))
        s.add(HubCompanyLink(tenant_id=tenant, hub_company_id=hub.id, company_id=cid))
        await s.commit()
    fetcher = _Fetcher(_tempton())
    assert (await _run(tenant, fetcher))["checked"] == 0 and fetcher.requested == []


async def test_a_sole_trader_is_never_checked() -> None:
    tenant = uuid.uuid4()
    await _company(tenant, "Andreas Uwe Weiss", domain="weiss-personal.de")
    fetcher = _Fetcher({})
    assert (await _run(tenant, fetcher))["checked"] == 0 and fetcher.requested == []


async def test_only_this_workspaces_companies_are_checked() -> None:
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    their_company = await _company(theirs, "Tempton Group GmbH", domain="tempton.de")
    fetcher = _Fetcher(_tempton())
    outcome = await _run(mine, fetcher)
    # Not even fetched: another workspace's client list never drives a request.
    assert fetcher.requested == [] and outcome["checked"] == 0
    assert (await _get(their_company)).impressum is None


async def test_the_company_page_and_the_register_show_the_verified_facts() -> None:
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", domain="tempton.de")
    async with SessionLocal() as s:
        assert (await company_switchboards(s, tenant, [cid])) == {}
    await _run(tenant, _Fetcher(_tempton()))
    async with SessionLocal() as s:
        page = await service.company_page(s, tenant_id=tenant, company_id=cid)
        other = await company_switchboards(s, uuid.uuid4(), [cid])
    board = page["switchboard"]
    assert board["vat_id"] == "DE252406571" and board["register"] == "HRB 28871"
    assert board["register_court"] == "Essen" and board["phone"] is None
    assert board["impressum_url"] == "https://tempton.de/impressum" and board["domain"] == "tempton.de"
    assert board["checked_at"].isoformat().startswith("2026-11-15")
    assert other == {}  # another workspace never reads it


def test_the_endpoint_is_machine_only() -> None:
    from tests.test_operator_endpoints import DECLARED_OPERATOR_ROUTES

    assert ("POST", "/hub/companies/impressum/check") in DECLARED_OPERATOR_ROUTES


async def test_the_register_route() -> None:
    # The Mandate's Stammdaten read it; no data yet → null, unknown company → 404.
    from httpx import ASGITransport, AsyncClient

    from app.core.config import settings
    from app.main import app

    cid = await _company(settings.default_tenant_id, "Tempton Group GmbH", domain="tempton.de")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.get(f"/api/v1/companies/{cid}/register")).json() is None
        await _run(settings.default_tenant_id, _Fetcher(_tempton()))
        body = (await client.get(f"/api/v1/companies/{cid}/register")).json()
        assert (await client.get(f"/api/v1/companies/{uuid.uuid4()}/register")).status_code == 404
    assert body["vat_id"] == "DE252406571" and body["register"] == "HRB 28871"
    assert body["impressum_url"] == "https://tempton.de/impressum" and body["checked_at"].startswith("2026-11-15")

