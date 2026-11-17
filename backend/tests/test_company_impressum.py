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

import asyncio
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



class _Slow(_Fetcher):
    """`slow.de` never answers within the batch."""

    async def get(self, url: str) -> sites.SitePage:
        if "slow.de" in url:
            await asyncio.sleep(5)
        return await super().get(url)


async def test_two_companies_on_one_slow_domain_do_not_lose_the_batch() -> None:
    # Review of #267: cancelling one company's read cancelled the shared page
    # fetch, and the other company's read raised CancelledError mid-loop —
    # the whole batch, incl. the verified Tempton, was never committed.
    tenant = uuid.uuid4()
    await _company(tenant, "Aaa Slow GmbH", domain="slow.de")
    fast = await _company(tenant, "Tempton Group GmbH", domain="tempton.de")
    await _company(tenant, "Zzz Slow Zwei GmbH", domain="slow.de")
    async with SessionLocal() as s:
        out = await impressum.check_companies(
            s, tenant_id=tenant, fetcher=_Slow(_tempton()), limit=20, now=NOW, seconds=0.5
        )
    assert out["checked"] == 1 and out["verified"] == 1
    assert (await _get(fast)).impressum["status"] == "verified"


def test_values_are_found_on_the_page_as_printed() -> None:
    # Review of #267: "CHE-123.456.789" on the page, "CHE123456789" stored;
    # a court broken across lines.
    page = "Muster Personal AG\nUID: CHE-123.456.789 MWST\nVertreten durch: Max Mustermann"
    assert impressum.on_page({"vat_id": "CHE123456789"}, page)[0]
    assert impressum.on_page({"register_court": "Frankfurt am Main"}, "Amtsgericht Frankfurt\n   am Main HRB 1")[0]


async def test_a_new_website_candidate_reopens_a_settled_check() -> None:
    # Review of #267: "no Impressum" on a contact's group domain must not stay
    # final once the recruiter enters the company's own domain.
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", emails=("m.mustermann@other-group.de",))
    await _run(tenant, _Fetcher({}))
    assert (await _get(cid)).impressum["status"] == "no_impressum"
    async with SessionLocal() as s:
        (await s.get(Company, cid)).domain = "tempton.de"
        await s.commit()
    assert (await _run(tenant, _Fetcher(_tempton())))["verified"] == 1


async def test_a_settled_check_is_retried_after_a_quarter() -> None:
    tenant = uuid.uuid4()
    await _company(tenant, "Tempton Group GmbH", domain="tempton.de")
    await _run(tenant, _Fetcher({}))
    assert (await _run(tenant, _Fetcher(_tempton()), NOW + dt.timedelta(days=30)))["checked"] == 0
    assert (await _run(tenant, _Fetcher(_tempton()), NOW + dt.timedelta(days=91)))["verified"] == 1


async def _linked_markt_board(tenant: uuid.UUID, cid: uuid.UUID, facts: dict) -> None:
    async with SessionLocal() as s:
        hub = HubCompany(
            name="Tempton Group GmbH", normalized_name=normalize_company_name("Tempton Group GmbH"),
            dedupe_key=f"k-{uuid.uuid4()}", resolution_basis="name_place", source="bundesagentur",
            kind=EMPLOYER, first_seen_at=NOW, last_seen_at=NOW,
        )
        s.add(hub)
        await s.flush()
        s.add(HubSiteCheck(domain="tempton.de", group_key=f"employer:{hub.id}", hub_company_id=hub.id,
                           status="verified", facts=facts, checked_at=NOW))
        s.add(HubCompanyLink(tenant_id=tenant, hub_company_id=hub.id, company_id=cid))
        await s.commit()


async def test_a_phone_only_markt_reading_does_not_hide_the_register() -> None:
    # Review of #267: Markt's switchboard has only a phone — the company's
    # own reading still runs, and the page shows both, field by field.
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", domain="tempton.de")
    await _linked_markt_board(tenant, cid, {"phone": "+49 201 89479-0"})
    assert (await _run(tenant, _Fetcher(_tempton())))["verified"] == 1
    async with SessionLocal() as s:
        board = (await company_switchboards(s, tenant, [cid]))[cid]
    assert board["phone"] == "+49 201 89479-0"
    assert board["vat_id"] == "DE252406571" and board["register"] == "HRB 28871"


async def test_writing_the_found_website_is_its_own_receipted_change() -> None:
    # Review of #267: the domain write must be named in the ledger, not ride
    # along inside the "impressum" change.
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", emails=("m.mustermann@tempton.de",))
    await _run(tenant, _Fetcher(_tempton()))
    async with SessionLocal() as s:
        records = (await s.scalars(select(EnrichmentRecord).where(EnrichmentRecord.entity_id == cid))).all()
        writes = (await s.scalars(select(Receipt).where(Receipt.tenant_id == tenant, Receipt.action == "write"))).all()
    assert sorted(r.field for r in records) == ["domain", "impressum"] and all(r.committed for r in records)
    assert sorted(w.payload["field"] for w in writes) == ["domain", "impressum"]


async def test_an_error_on_one_candidate_is_retried_after_a_week_not_a_quarter() -> None:
    """The own domain was down; the contact's mail domain has no Impressum.
    The company is "error", not "no Impressum": asked again after a week."""
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", domain="tempton.de", emails=("m.mustermann@tempton-gruppe.de",))
    down = _Fetcher({"https://tempton.de/": (503, None), "https://tempton-gruppe.de/": (200, "<p>Willkommen</p>")})
    assert (await _run(tenant, down))["error"] == 1
    assert (await _get(cid)).impressum["status"] == "error"
    assert (await _run(tenant, _Fetcher(_tempton()), NOW + dt.timedelta(days=8)))["verified"] == 1


# --- Website finder by web search -------------------------------------------
# A company with no website candidate (or whose candidates' Impressum names
# another firm) is looked up by name (+ town). The search only PROPOSES
# domains; the same Impressum checks decide. No network: a fake search client.


class _Search:
    """Answers query → result URLs (or raises); records every query. The
    caller spends `remaining`; the await lets concurrent reads interleave."""

    def __init__(self, results: list[str] | Exception | None = None, budget: int = 20) -> None:
        self.results = results if results is not None else []
        self.queries: list[str] = []
        self.remaining = budget

    async def search(self, query: str) -> list[str] | None:
        await asyncio.sleep(0.01)
        self.queries.append(query)
        if isinstance(self.results, Exception):
            raise self.results
        return list(self.results)


async def _run_search(tenant: uuid.UUID, fetcher: _Fetcher, searcher, now: dt.datetime = NOW) -> dict:
    async with SessionLocal() as s:
        return await impressum.check_companies(
            s, tenant_id=tenant, fetcher=fetcher, searcher=searcher, limit=20, now=now
        )


async def _company_in(tenant: uuid.UUID, name: str, location: str | None, **kw) -> uuid.UUID:
    cid = await _company(tenant, name, **kw)
    async with SessionLocal() as s:
        (await s.get(Company, cid)).location = location
        await s.commit()
    return cid


async def test_without_a_search_key_there_is_no_search_client() -> None:
    from app.domain.companies import website_search

    assert website_search.from_settings(api_key=None, budget=20) is None
    assert website_search.from_settings(api_key="", budget=20) is None
    assert website_search.from_settings(api_key="k", budget=0) is None
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH")
    outcome = await _run_search(tenant, _Fetcher(_tempton()), None)
    assert outcome["no_domain"] == 1 and outcome["searched"] == 0
    assert "search" not in (await _get(cid)).impressum


async def test_a_found_website_is_verified_through_the_impressum_and_committed() -> None:
    tenant = uuid.uuid4()
    cid = await _company_in(tenant, "Tempton Group GmbH", "Essen")
    search = _Search([
        "https://www.northdata.de/Tempton+Group+GmbH,+Essen/HRB+28871",
        "https://de.linkedin.com/company/tempton",
        "https://www.tempton.de/impressum",
    ])
    fetcher = _Fetcher(_tempton())
    outcome = await _run_search(tenant, fetcher, search)
    company = await _get(cid)
    assert search.queries == ["Tempton Group GmbH Essen Impressum"]
    assert outcome["verified"] == 1 and outcome["searched"] == 1
    facts = company.impressum
    assert facts["status"] == "verified" and facts["vat_id"] == "DE252406571"
    assert facts["found_by"] == "search" and facts["search"]["domains"] == ["tempton.de"]
    assert facts["candidates"] == []  # the workspace's own candidates, unchanged
    assert company.domain == "tempton.de"
    # Directories and social networks are never fetched.
    assert not any("northdata" in u or "linkedin" in u for u in fetcher.requested)
    async with SessionLocal() as s:
        records = (await s.scalars(select(EnrichmentRecord).where(EnrichmentRecord.entity_id == cid))).all()
    assert sorted(r.field for r in records) == ["domain", "impressum"]
    assert all("web search" in r.source_detail for r in records)


def test_directory_and_aggregator_domains_are_filtered() -> None:
    urls = [
        "https://www.northdata.de/x", "https://www.firmenwissen.de/x", "https://www.wer-zu-wem.de/x",
        "https://www.gelbeseiten.de/x", "https://www.dasoertliche.de/x", "https://www.kununu.com/de/x",
        "https://de.indeed.com/x", "https://www.stepstone.de/x", "https://de.wikipedia.org/wiki/X",
        "https://www.youtube.com/x", "https://www.google.com/maps/x", "https://www.bing.com/x",
        "https://www.handelsregister.de/x", "https://www.unternehmensregister.de/x",
        "https://www.moneyhouse.ch/x", "https://www.xing.com/pages/x", "https://www.facebook.com/x",
        "https://www.instagram.com/x", "https://www.linkedin.com/company/x",
        "https://www.muster-bau.de/kontakt", "https://muster-bau.de/impressum", "not a url",
    ]
    assert impressum.search_domains(urls) == ["muster-bau.de"]


async def test_a_search_runs_after_the_own_candidates_named_another_firm() -> None:
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", emails=("m.mustermann@other-group.de",))
    other = {
        "https://other-group.de/": (200, '<a href="/impressum">Impressum</a>'),
        "https://other-group.de/impressum": (200, _html("Impressum\nOther Group GmbH\nHRB 1 Amtsgericht Köln")),
    }
    search = _Search(["https://tempton.de/"])
    fetcher = _Fetcher({**other, **_tempton()})
    assert (await _run_search(tenant, fetcher, search))["verified"] == 1
    assert fetcher.requested[0] == "https://other-group.de/"  # the workspace's own lead first
    facts = (await _get(cid)).impressum
    assert facts["domain"] == "tempton.de" and facts["found_by"] == "search"
    assert facts["candidates"] == ["other-group.de"]


async def test_a_verified_own_candidate_is_never_searched() -> None:
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", domain="tempton.de")
    search = _Search(["https://tempton.de/"])
    await _run_search(tenant, _Fetcher(_tempton()), search)
    assert search.queries == [] and (await _get(cid)).impressum["found_by"] == "workspace"


async def test_a_search_is_not_repeated_within_the_period() -> None:
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Muster Bau GmbH")
    search = _Search(["https://muster-bau.de/"])
    await _run_search(tenant, _Fetcher({}), search)
    facts = (await _get(cid)).impressum
    assert facts["status"] == "no_impressum" and facts["search"]["domains"] == ["muster-bau.de"]
    assert facts["search"]["name"] == "Muster Bau GmbH"

    again = _Search(["https://muster-bau.de/"])
    assert (await _run_search(tenant, _Fetcher({}), again, NOW + dt.timedelta(days=30)))["checked"] == 0
    assert again.queries == []
    # A quarter later: asked again, once.
    later = _Search(["https://muster-bau.de/"])
    await _run_search(tenant, _Fetcher({}), later, NOW + dt.timedelta(days=91))
    assert len(later.queries) == 1


async def test_a_company_settled_before_the_finder_existed_is_searched() -> None:
    # Prod: 138 "no domain" and 71 "not named" companies checked without a
    # search must not wait a quarter once the key is set.
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", emails=("m.mustermann@other-group.de",))
    await _run(tenant, _Fetcher({}))
    assert (await _get(cid)).impressum["status"] == "no_impressum"
    search = _Search(["https://tempton.de/"])
    out = await _run_search(tenant, _Fetcher(_tempton()), search, NOW + dt.timedelta(days=1))
    assert out["verified"] == 1 and len(search.queries) == 1


async def test_a_renamed_company_is_searched_again() -> None:
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Muster Bau GmbH")
    await _run_search(tenant, _Fetcher({}), _Search([]))
    async with SessionLocal() as s:
        (await s.get(Company, cid)).name = "Muster Hochbau GmbH"
        await s.commit()
    again = _Search([])
    await _run_search(tenant, _Fetcher({}), again, NOW + dt.timedelta(days=1))
    assert again.queries == ["Muster Hochbau GmbH Impressum"]


async def test_stored_search_domains_are_retried_without_searching() -> None:
    # A site error on the found domain: retried after a week from the stored
    # result, not by asking the search provider again.
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH")
    await _run_search(tenant, _Fetcher({"https://tempton.de/": (503, None)}), _Search(["https://tempton.de/"]))
    assert (await _get(cid)).impressum["status"] == "error"
    again = _Search(["https://elsewhere.de/"])
    out = await _run_search(tenant, _Fetcher(_tempton()), again, NOW + dt.timedelta(days=8))
    assert out["verified"] == 1 and again.queries == []


async def test_a_search_error_does_not_break_the_batch() -> None:
    tenant = uuid.uuid4()
    lost = await _company(tenant, "Aaa Muster GmbH")
    ok = await _company(tenant, "Tempton Group GmbH", domain="tempton.de")
    out = await _run_search(tenant, _Fetcher(_tempton()), _Search(RuntimeError("search down")))
    assert out["checked"] == 2 and out["verified"] == 1 and out["no_domain"] == 1
    assert out["search_failed"] == 1 and out["searched"] == 0
    assert (await _get(ok)).impressum["status"] == "verified"
    facts = (await _get(lost)).impressum
    assert facts["search"]["failed"] is True and facts["search"]["domains"] == []
    # Not again within the day (the daily loop would re-pick it batch after
    # batch while the provider is down) — but the next day.
    soon = _Search(["https://muster.de/"])
    assert (await _run_search(tenant, _Fetcher({}), soon, NOW + dt.timedelta(hours=2)))["checked"] == 0
    later = _Search([])
    await _run_search(tenant, _Fetcher({}), later, NOW + dt.timedelta(days=1, hours=1))
    assert later.queries == ["Aaa Muster GmbH Impressum"]


async def test_a_suspected_natural_person_is_never_searched() -> None:
    tenant = uuid.uuid4()
    await _company(tenant, "Andreas Uwe Weiss")
    search = _Search(["https://weiss-personal.de/"])
    assert (await _run_search(tenant, _Fetcher({}), search))["checked"] == 0
    assert search.queries == []


async def test_searches_stay_within_the_budget() -> None:
    tenant = uuid.uuid4()
    for name in ("Aaa Bau GmbH", "Bbb Bau GmbH", "Ccc Bau GmbH"):
        await _company(tenant, name)
    search = _Search([], budget=2)
    out = await _run_search(tenant, _Fetcher({}), search)
    assert len(search.queries) == 2 and out["searched"] == 2 and out["search_failed"] == 0
    # The one left out is not marked failed: it is simply searched next time.
    async with SessionLocal() as s:
        rows = (await s.scalars(select(Company).where(Company.tenant_id == tenant))).all()
    assert sorted("search" in c.impressum for c in rows) == [False, True, True]


async def test_a_company_due_only_for_the_search_is_not_fetched_again() -> None:
    # Its own website was read last week (another firm's Impressum): only the
    # finder's domains are fetched now, on a budget slot reserved for it.
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Tempton Group GmbH", emails=("m.mustermann@other-group.de",))
    await _run(tenant, _Fetcher({}))
    await _company(tenant, "Aaa Neu GmbH")  # due anyway, sorts first, also wants a search
    search = _Search(["https://tempton.de/"], budget=1)
    fetcher = _Fetcher(_tempton())
    await _run_search(tenant, fetcher, search, NOW + dt.timedelta(days=7))
    assert search.queries == ["Tempton Group GmbH Impressum"]
    assert not any("other-group" in u for u in fetcher.requested)
    assert (await _get(cid)).impressum["status"] == "verified"


async def test_a_search_answer_survives_a_read_that_did_not_finish() -> None:
    # The query is paid for: a batch timeout on the found site must not make
    # the next batch ask the provider again.
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Slow Bau GmbH")
    async with SessionLocal() as s:
        await impressum.check_companies(
            s, tenant_id=tenant, fetcher=_Slow({}), searcher=_Search(["https://slow.de/"]),
            limit=20, now=NOW, seconds=0.5,
        )
    assert (await _get(cid)).impressum["search"]["domains"] == ["slow.de"]
    again = _Search(["https://elsewhere.de/"])
    out = await _run_search(tenant, _Fetcher({}), again)
    assert again.queries == [] and out["checked"] == 1


class _Broken(_Fetcher):
    async def get(self, url: str) -> sites.SitePage:
        if "broken.de" in url:
            raise RuntimeError("boom")
        return await super().get(url)


async def test_a_search_answer_survives_a_failed_read() -> None:
    tenant = uuid.uuid4()
    cid = await _company(tenant, "Broken Bau GmbH")
    out = await _run_search(tenant, _Broken({}), _Search(["https://broken.de/"]))
    facts = (await _get(cid)).impressum
    assert out["error"] == 1 and facts["status"] == "error"
    assert facts["search"]["domains"] == ["broken.de"]


def test_a_domain_the_workspace_entered_is_never_filtered_as_a_directory() -> None:
    # Directories are filtered from SEARCH results only: amazon.de is a firm.
    assert impressum.website_candidates("https://www.amazon.de", ["a@ebay.de"]) == ["amazon.de", "ebay.de"]
    assert impressum.search_domains(["https://www.amazon.de/dp/1", "https://ebay.de/"]) == []


def test_the_query_holds_the_town_not_a_street() -> None:
    assert impressum.search_query("Muster GmbH", "Hauptstr. 1, 45127 Essen") == "Muster GmbH 45127 Essen Impressum"
    assert impressum.search_query("Muster GmbH", " Essen ") == "Muster GmbH Essen Impressum"
    assert impressum.search_query("Muster GmbH", None) == "Muster GmbH Impressum"


async def test_the_search_query_never_reaches_the_logs(caplog) -> None:
    import logging

    import httpx

    from app.domain.companies import website_search

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"web": {"results": []}})

    client = website_search.BraveSearch("k-123", min_interval=0, transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.DEBUG):
        async with client:
            await client.search("Geheimkunde GmbH Essen Impressum")
    assert "Geheimkunde" not in caplog.text and "k-123" not in caplog.text


async def test_the_brave_client_reads_result_urls_and_degrades_to_none() -> None:
    import httpx

    from app.domain.companies import website_search

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "fail" in str(request.url):
            return httpx.Response(429)
        return httpx.Response(200, json={"web": {"results": [{"url": "https://tempton.de/"}, {"title": "x"}]}})

    client = website_search.BraveSearch("k-123", budget=3, min_interval=0, transport=httpx.MockTransport(handler))
    async with client:
        assert await client.search("Tempton Group GmbH Essen") == ["https://tempton.de/"]
        assert await client.search("fail") is None
    assert seen[0].headers["X-Subscription-Token"] == "k-123"
    assert seen[0].url.params["q"] == "Tempton Group GmbH Essen" and seen[0].url.params["country"] == "de"
    assert client.remaining == 3  # the budget is the caller's to spend


async def test_the_operator_route_says_whether_the_website_finder_is_on(monkeypatch) -> None:
    """A run that searched nothing must say whether the finder was off (no
    key) or had nobody to search — the same zeros otherwise hide which."""
    import uuid as _uuid

    from httpx import ASGITransport, AsyncClient

    from app.core.config import settings
    from app.main import app

    token = "eli39-" + _uuid.uuid4().hex * 2
    monkeypatch.setattr(settings, "ingest_token", token)
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        monkeypatch.setattr(settings, "search_api_key", None)
        off = await client.post("/api/v1/hub/companies/impressum/check?limit=5", headers=headers)
        monkeypatch.setattr(settings, "search_api_key", "test-key")
        on = await client.post("/api/v1/hub/companies/impressum/check?limit=5", headers=headers)
    assert off.status_code == 200 and off.json()["search_enabled"] == 0
    assert on.status_code == 200 and on.json()["search_enabled"] == 1


async def test_hub_daily_prints_when_the_website_finder_is_off() -> None:
    import httpx

    from scripts.hub_daily import _check_company_impressum

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"checked": 0, "search_enabled": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://t") as client:
        totals = await _check_company_impressum(client, budget=10)
    assert totals["search_enabled"] == 0


async def test_hub_daily_rides_out_a_deploy_mid_run(monkeypatch) -> None:
    """2026-11-17: a deploy restarted the API 13 minutes into a run; one
    502 ended the job and lost every count it had collected."""
    import httpx

    import scripts.hub_daily as daily

    monkeypatch.setattr(daily, "_RETRY_WAITS", (0.0, 0.0))
    answers = iter([
        httpx.Response(200, json={"checked": 20, "verified": 5, "search_enabled": 1}),
        httpx.Response(502),
        httpx.Response(200, json={"checked": 3, "verified": 1, "search_enabled": 1}),
        httpx.Response(200, json={"checked": 0}),
        httpx.Response(200, json={"checked": 0}),
    ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: next(answers)), base_url="http://t") as c:
        totals = await daily._check_company_impressum(c, budget=100)
    assert totals["checked"] == 23 and totals["verified"] == 6


async def test_hub_daily_prints_what_it_had_when_the_api_stays_down(monkeypatch, capsys) -> None:
    import httpx
    import pytest

    import scripts.hub_daily as daily

    monkeypatch.setattr(daily, "_RETRY_WAITS", (0.0,))
    answers = iter([httpx.Response(200, json={"checked": 20, "verified": 5, "search_enabled": 1})])

    def answer(request: httpx.Request) -> httpx.Response:
        return next(answers, httpx.Response(502))

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://t") as c:
        with pytest.raises(httpx.HTTPStatusError):
            await daily._check_company_impressum(c, budget=100)
    out = capsys.readouterr()
    assert "20 geprüft, 5 bestätigt" in out.out + out.err
