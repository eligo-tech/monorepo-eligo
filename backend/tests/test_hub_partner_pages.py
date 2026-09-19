"""Partner-board pages — the "Quelle" behind a BA posting.

Parser tests run against real pages captured Sept 2026 (tests/fixtures/
partner_*.html), with no network. The service tests use a fake fetcher, so they
exercise selection, stamping and evidence without touching the internet.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.hub import service
from app.domain.hub.adapters.partner_pages import (
    STATUS_ERROR,
    STATUS_ROBOTS,
    STATUS_SKIPPED,
    PartnerPage,
    PartnerPageFetcher,
    page_text,
)
from app.domain.hub.contacts import extract_contacts
from app.domain.hub.models import (
    HubCompany,
    HubCompanyLink,
    HubJobPosting,
    HubObservation,
    HubPostingPayload,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
NOW = dt.datetime.now(dt.UTC)


def _contacts(name: str) -> dict[str, tuple]:
    text = page_text((FIXTURES / name).read_text(encoding="utf-8"))
    return {c.full_name: (c.role_title, c.email, c.phone) for c in extract_contacts(text)}


# --------------------------------------------------------------------------
# page_text + extraction on real pages
# --------------------------------------------------------------------------


def test_jobexport_heading_then_name_then_role() -> None:
    """The example from the product brief: the contact the BA text leaves out."""
    assert _contacts("partner_jobexport.html") == {
        "Kathrin Telega": ("Junior People & Culture Business Partner", None, None)
    }


def test_interamt_label_block_with_email_and_phone() -> None:
    found = _contacts("partner_interamt.html")
    assert found["Isabelle Requardt"] == (
        "Fachbereichsleiterin",
        "isabelle.requardt@lkn.landsh.de",
        "04841-667/ 234",
    )
    assert "Enrico Nitze" in found


def test_bewerbung_jobs_role_on_the_next_line() -> None:
    assert _contacts("partner_bewerbung.html") == {
        "Andre Risch": ("HR-Manager / Prokurist", "andre.risch@brekstar.de", "+49 69 6605 999 120")
    }


def test_page_text_drops_scripts_and_keeps_lines() -> None:
    text = page_text(
        "<html><head><title>x</title></head><body><script>var a='Frau Evil Script'</script>"
        "<h4>Ihr Kontakt</h4><p><strong>Jana Beispiel</strong><br>Recruiterin</p></body></html>"
    )
    assert "Evil" not in text
    assert text.splitlines() == ["Ihr Kontakt", "", "Jana Beispiel", "Recruiterin"]


def test_site_furniture_is_not_a_person() -> None:
    text = "Kontakt\nCookie Einstellungen\n\nAnsprechpartnerin\nFrau Bewerbermanagement\n"
    assert extract_contacts(text) == []


def test_nul_bytes_never_reach_the_database() -> None:
    """Production, 2026-09-18: one gute-jobs.de page carried a NUL byte and
    Postgres refused the whole batch ("invalid byte sequence ... 0x00").
    SQLite stores it, so only this test stands between CI and that failure."""
    text = page_text("<p>Ansprech\x00partnerin</p><p>Jana\x07 Beispiel\tHR</p>")
    assert "\x00" not in text and "\x07" not in text
    assert text.splitlines() == ["Ansprechpartnerin", "", "Jana Beispiel HR"]


# --------------------------------------------------------------------------
# The fetcher: refusals happen before any request
# --------------------------------------------------------------------------


async def test_blocked_hosts_are_skipped_without_a_request() -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not be requested")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
        page = await PartnerPageFetcher(client=client).fetch("https://www.heyjobs.co/de-de/jobs/1")
    assert page.status == STATUS_SKIPPED and page.text is None


async def test_an_unexpected_error_is_a_failed_page_not_a_failed_batch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise ValueError("charset nobody expected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await PartnerPageFetcher(client=client, per_host_delay=0).fetch(
            "https://board.example/job/1"
        )
    assert page.status == STATUS_ERROR and page.note == "ValueError"


async def test_robots_txt_is_respected() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /stellen/\n")
        return httpx.Response(200, text="<p>Ansprechpartnerin: Jana Beispiel</p>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = PartnerPageFetcher(client=client, per_host_delay=0)
        refused = await fetcher.fetch("https://board.example/stellen/1")
        allowed = await fetcher.fetch("https://board.example/job/2")
    assert refused.status == STATUS_ROBOTS
    assert allowed.status == 200 and "Jana Beispiel" in (allowed.text or "")
    # robots.txt read once per host, the disallowed page never requested.
    assert seen == ["/robots.txt", "/job/2"]


# --------------------------------------------------------------------------
# The nightly pass
# --------------------------------------------------------------------------


class FakeFetcher:
    def __init__(self, pages: dict[str, PartnerPage]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> PartnerPage:
        self.calls.append(url)
        return self.pages[url]


def _company(name: str) -> HubCompany:
    return HubCompany(
        name=name,
        normalized_name=name.lower(),
        dedupe_key=f"k-{uuid.uuid4()}",
        resolution_basis="name_place",
        city="Berlin",
        source="bundesagentur",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def _posting(company: HubCompany, url: str | None, *, days_ago: int) -> HubJobPosting:
    posting = HubJobPosting(
        hub_company_id=company.id,
        title="Senior Solution Architect (m/w/d)",
        source="bundesagentur",
        external_id=f"10001-{uuid.uuid4().hex[:10]}-S",
        source_url=url,
        posted_at=NOW - dt.timedelta(days=days_ago),
        first_seen_at=NOW,
        last_seen_at=NOW,
        is_active=True,
        content_hash=uuid.uuid4().hex,
    )
    posting.payload = HubPostingPayload(raw={}, description="Bewerbung an jobs@avelion.example")
    return posting


@pytest.fixture
async def corpus() -> dict:
    async with SessionLocal() as s:
        watched, other = _company("Avelion"), _company("Andere")
        s.add_all([watched, other])
        await s.flush()
        # The unwatched posting is NEWER: ordering must still put watched first.
        s.add_all(
            [
                _posting(other, "https://board.example/other", days_ago=0),
                _posting(watched, "https://www.jobexport.de/detail/1", days_ago=5),
                _posting(watched, "https://www.heyjobs.co/x", days_ago=6),
                _posting(watched, None, days_ago=1),  # no Quelle — never selected
            ]
        )
        s.add(HubCompanyLink(tenant_id=uuid.uuid4(), hub_company_id=watched.id))
        await s.commit()
        return {"watched": watched.id}


async def test_nightly_pass_reads_watched_first_and_records_evidence(corpus) -> None:
    telega = page_text((FIXTURES / "partner_jobexport.html").read_text(encoding="utf-8"))
    fetcher = FakeFetcher(
        {
            "https://www.jobexport.de/detail/1": PartnerPage(
                "https://www.jobexport.de/detail/1",
                "https://www.jobexport.de/detail/1?board=ba",
                200,
                telega,
            ),
            "https://www.heyjobs.co/x": PartnerPage(
                "https://www.heyjobs.co/x", None, STATUS_SKIPPED, None, "bot-check"
            ),
            "https://board.example/other": PartnerPage(
                "https://board.example/other", "https://board.example/other", 404, None
            ),
        }
    )
    async with SessionLocal() as s:
        first = await service.fetch_missing_partner_pages(s, fetcher=fetcher, limit=2)
        assert fetcher.calls == ["https://www.jobexport.de/detail/1", "https://www.heyjobs.co/x"]
        assert first == {"attempted": 2, "stored": 1, "failed": 0, "skipped": 1}

        rest = await service.fetch_missing_partner_pages(s, fetcher=fetcher, limit=10)
        assert rest == {"attempted": 1, "stored": 0, "failed": 1, "skipped": 0}
        # Every row attempted once: a third pass does nothing.
        assert (await service.fetch_missing_partner_pages(s, fetcher=fetcher, limit=10))[
            "attempted"
        ] == 0
        assert len(fetcher.calls) == 3

        # One observation per fetch, including the skip and the 404.
        observations = (
            await s.execute(select(HubObservation).where(HubObservation.source == "partner_page"))
        ).scalars().all()
        assert sorted(o.http_status or 0 for o in observations) == [0, 200, 404]

        progress = await service.partner_pages_progress(s)
        assert progress == {"with_source_url": 3, "source_page_attempted": 3, "source_page_read": 1}

        # The page text is linked to the fetch that produced it.
        payload = (
            await s.execute(
                select(HubPostingPayload).where(HubPostingPayload.source_page_text.is_not(None))
            )
        ).scalar_one()
        assert payload.source_page_url == "https://www.jobexport.de/detail/1?board=ba"
        assert payload.source_page_observation_id in {o.id for o in observations}

        # And "Ansprechpartner finden" now finds her, with the Quelle as evidence.
        result = await service.company_contacts(
            s, tenant_id=uuid.uuid4(), hub_company_id=corpus["watched"]
        )
        telega_contact = next(c for c in result["contacts"] if c["last_name"] == "Telega")
        assert telega_contact["role_title"] == "Junior People & Culture Business Partner"
        assert telega_contact["mention_count"] == 1
        assert [(e["origin"], e["url"]) for e in telega_contact["evidence"]] == [
            ("quelle", "https://www.jobexport.de/detail/1?board=ba")
        ]


async def test_no_partner_page_rows_means_no_fetch() -> None:
    fetcher = FakeFetcher({})
    async with SessionLocal() as s:
        assert await service.fetch_missing_partner_pages(s, fetcher=fetcher) == {
            "attempted": 0, "stored": 0, "failed": 0, "skipped": 0,
        }
        assert await s.scalar(select(func.count(HubObservation.id))) == 0
