"""Checking agency website candidates against their Impressum (PR7, option A).

The nightly step takes each agency's best UNVERIFIED candidate (PR6), fetches
the homepage and its Impressum through `SiteFetcher`, and only when the
Impressum names the agency as operator writes the company facts — website,
VAT, register — onto the agency's corpus rows, and only where empty. People
named in the Impressum are parsed but never stored.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.hub import agencies, sites
from app.domain.hub.models import (
    PRIVATE_RECRUITER,
    HubAgencyProfile,
    HubCompany,
    HubJobPosting,
    HubObservation,
    HubPostingPayload,
    HubSiteCheck,
)
from app.domain.hub.resolution import normalize_company_name

FX = pathlib.Path(__file__).parent / "fixtures" / "impressum"
NOW = dt.datetime.now(dt.UTC)


def _html(text: str) -> str:
    return "<html><body>" + "".join(f"<p>{line}</p>" for line in text.split("\n")) + "</body></html>"


class _Fetcher:
    """Answers from a dict of URL → (status, html); records every request."""

    def __init__(self, pages: dict[str, tuple[int, str | None]]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def get(self, url: str) -> sites.SitePage:
        self.requested.append(url)
        status, html = self.pages.get(url, (404, None))
        return sites.SitePage(url=url, final_url=url, status=status, html=html)


async def _agency(name: str, ad: str, *, website: str | None = None) -> None:
    async with SessionLocal() as s:
        c = HubCompany(
            name=name, normalized_name=normalize_company_name(name), dedupe_key=f"pav:{uuid.uuid4()}",
            resolution_basis="name_place", city="Köln", source="bundesagentur", kind=PRIVATE_RECRUITER,
            open_postings_count=1, suspected_natural_person=False, first_seen_at=NOW, last_seen_at=NOW,
            website_domain=website,
        )
        s.add(c)
        await s.flush()
        s.add(HubJobPosting(
            hub_company_id=c.id, title="Recruiter (m/w/d)", berufsfeld="IT", source="bundesagentur",
            external_id=f"e-{uuid.uuid4().hex[:6]}", content_hash=uuid.uuid4().hex, segment=PRIVATE_RECRUITER,
            posted_at=NOW, first_seen_at=NOW, last_seen_at=NOW, is_active=True,
            payload=HubPostingPayload(raw={}, description=ad),
        ))
        await s.commit()
    async with SessionLocal() as s:
        await agencies.refresh_profiles(s)


def _focus_pages() -> dict:
    return {
        "https://focussearch.de/": (200, '<a href="/?Impressum">Impressum</a>'),
        "https://focussearch.de/?Impressum": (200, _html((FX / "focussearch_de.txt").read_text())),
    }


async def _check(fetcher, limit: int = 10) -> dict:
    async with SessionLocal() as s:
        return await sites.check_agency_sites(s, fetcher=fetcher, limit=limit)


async def test_a_verified_site_writes_company_facts_only_where_empty() -> None:
    await _agency("FOCUS search GmbH", "Bewerbung an jobs@focussearch.de")
    outcome = await _check(_Fetcher(_focus_pages()))
    async with SessionLocal() as s:
        check = await s.scalar(select(HubSiteCheck))
        company = await s.scalar(select(HubCompany))
        observations = await s.scalar(select(func.count()).select_from(HubObservation).where(HubObservation.source == "impressum"))
    assert outcome["verified"] == 1
    assert check.status == "verified" and check.domain == "focussearch.de"
    assert check.facts["register"] == "HRB 78563" and check.facts["register_court"] == "Köln"
    assert company.website_domain == "focussearch.de"
    assert (company.register_number, company.register_court) == ("HRB 78563", "Köln")
    assert observations == 1 and check.observation_id is not None
    # Option A: people parsed, never stored.
    assert "Mustermann" not in str(check.facts)


async def test_a_known_website_is_never_overwritten() -> None:
    await _agency("FOCUS search GmbH", "jobs@focussearch.de", website="focus-search.com")
    await _check(_Fetcher(_focus_pages()))
    async with SessionLocal() as s:
        assert (await s.scalar(select(HubCompany))).website_domain == "focus-search.com"


async def test_someone_elses_impressum_rejects_the_candidate() -> None:
    await _agency("Zebrafink Personal GmbH", "Bewerbung an jobs@focussearch.de")
    outcome = await _check(_Fetcher(_focus_pages()))
    async with SessionLocal() as s:
        check = await s.scalar(select(HubSiteCheck))
        company = await s.scalar(select(HubCompany))
    assert outcome["not_named"] == 1 and check.status == "not_named"
    assert company.website_domain is None and company.register_number is None


async def test_a_checked_domain_is_not_fetched_again() -> None:
    await _agency("FOCUS search GmbH", "jobs@focussearch.de")
    await _check(_Fetcher(_focus_pages()))
    again = _Fetcher(_focus_pages())
    outcome = await _check(again)
    assert again.requested == [] and outcome["checked"] == 0


async def test_an_error_is_retried_after_a_week_not_the_next_night() -> None:
    await _agency("FOCUS search GmbH", "jobs@focussearch.de")
    await _check(_Fetcher({}))  # every URL 404 → no impressum? homepage missing → error
    async with SessionLocal() as s:
        check = await s.scalar(select(HubSiteCheck))
        assert check.status in ("error", "no_impressum")
        check.status = "error"
        await s.commit()
    tomorrow = _Fetcher(_focus_pages())
    await _check(tomorrow)
    assert tomorrow.requested == []
    async with SessionLocal() as s:
        check = await s.scalar(select(HubSiteCheck))
        check.checked_at = NOW - dt.timedelta(days=8)
        await s.commit()
    next_week = _Fetcher(_focus_pages())
    await _check(next_week)
    assert next_week.requested


async def test_a_likely_client_domain_is_skipped_for_the_next_candidate() -> None:
    async with SessionLocal() as s:
        s.add(HubCompany(
            name="Die Autobahn GmbH des Bundes", normalized_name="die autobahn des bundes", dedupe_key="emp:autobahn",
            resolution_basis="name_place", source="bundesagentur", kind="employer", open_postings_count=1,
            suspected_natural_person=False, first_seen_at=NOW, last_seen_at=NOW,
        ))
        await s.commit()
    await _agency("FOCUS search GmbH", "Für unseren Kunden https://www.autobahn.de/x — Bewerbung jobs@focussearch.de")
    fetcher = _Fetcher(_focus_pages())
    await _check(fetcher)
    assert all("autobahn" not in u for u in fetcher.requested)


async def test_the_verification_shows_on_the_profile_after_the_rebuild() -> None:
    await _agency("FOCUS search GmbH", "jobs@focussearch.de")
    await _check(_Fetcher(_focus_pages()))
    async with SessionLocal() as s:
        await agencies.refresh_profiles(s)
        profile = await s.scalar(select(HubAgencyProfile))
    assert profile.website_candidates[0]["check"] == "verified"


# --- the fetcher: polite, and never into an internal address ------------------


def _transport(routes: dict[str, httpx.Response]):
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))
    return httpx.MockTransport(handler)


@pytest.fixture
def public_dns(monkeypatch):
    async def resolve(host: str) -> bool:
        return host not in {"evil-internal.de"}
    monkeypatch.setattr(sites, "_resolves_public", resolve)


async def test_a_redirect_into_a_private_address_is_refused(public_dns) -> None:
    routes = {
        "https://firma.de/robots.txt": httpx.Response(404),
        "https://firma.de/": httpx.Response(302, headers={"location": "http://127.0.0.1:8080/admin"}),
    }
    async with httpx.AsyncClient(transport=_transport(routes)) as client:
        page = await sites.SiteFetcher(client=client, per_host_delay=0).get("https://firma.de/")
    assert page.status == sites.STATUS_BLOCKED and page.html is None


async def test_a_host_resolving_to_a_private_address_is_refused(public_dns) -> None:
    async with httpx.AsyncClient(transport=_transport({})) as client:
        page = await sites.SiteFetcher(client=client, per_host_delay=0).get("https://evil-internal.de/")
    assert page.status == sites.STATUS_BLOCKED


async def test_robots_txt_is_respected(public_dns) -> None:
    routes = {"https://firma.de/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /")}
    async with httpx.AsyncClient(transport=_transport(routes)) as client:
        page = await sites.SiteFetcher(client=client, per_host_delay=0).get("https://firma.de/")
    assert page.status == sites.STATUS_BLOCKED


async def test_an_agencys_own_redirect_is_followed(public_dns) -> None:
    # Measured: woltersdorf-pb.de forwards to a Jimdo site.
    routes = {
        "https://firma.de/robots.txt": httpx.Response(404),
        "https://firma.de/": httpx.Response(302, headers={"location": "https://firma.jimdosite.com/"}),
        "https://firma.jimdosite.com/robots.txt": httpx.Response(404),
        "https://firma.jimdosite.com/": httpx.Response(200, text="<a href='/impressum/'>Impressum</a>"),
    }
    async with httpx.AsyncClient(transport=_transport(routes)) as client:
        page = await sites.SiteFetcher(client=client, per_host_delay=0).get("https://firma.de/")
    assert page.status == 200 and page.final_url == "https://firma.jimdosite.com/"
