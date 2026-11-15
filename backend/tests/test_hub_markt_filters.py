"""ELI-27: two Markt filters — leave out recruitment agencies, and size.

* **Agencies.** pav ads are already in their own segment and never reach
  Markt. What still does: firms whose NAME says staffing or placement
  ("… Personalberatung GmbH", Hays) posting as an employer. Decided once, at
  ingest, by the same name rule EURES uses to sort ads
  (`adapters/eures.staffing_signal`), and stored on `hub_companies` — so the
  filter is a column check, never a text scan per request.
* **Size.** The corpus has no headcount. The honest proxy is how many open
  ads the employer has in the corpus, across all its sites, in buckets. The
  UI says "offene Stellen", not "Mitarbeiter".
"""

from __future__ import annotations

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import service
from app.domain.hub.adapters.base import FetchResult, SourcedCompany, SourcedPosting
from app.domain.hub.models import HubCompany


def _result(employer: str, n: int, *, city: str = "Berlin", postcode: str = "10115") -> FetchResult:
    now = dt.datetime.now(dt.UTC)
    slug = employer.split()[0].lower()
    return FetchResult(
        source="bundesagentur", request_url="https://example.test/feed", fetched_at=now,
        http_status=200, robots_allowed=True, total_available=n, content_hash=None,
        postings=[
            SourcedPosting(
                external_id=f"{slug}:{city}:{i}", title=f"Pflegefachkraft {i}",
                company=SourcedCompany(name=employer, postal_code=postcode, city=city, country="DEUTSCHLAND"),
                postal_code=postcode, city=city, country="DEUTSCHLAND", raw={},
            )
            for i in range(n)
        ],
    )


async def _ingest(*results: FetchResult) -> None:
    async with SessionLocal() as s:
        for i, result in enumerate(results):
            await service.merge_fetch(s, result=result, key=f"k{i}")


# --- agencies -------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,agency",
    [
        ("Muster Personalberatung GmbH", True),
        ("Hays AG", True),
        ("ABC Personaldienstleistungen GmbH", True),
        ("Zeitarbeit Nord GmbH", True),
        ("Klinikum Musterstadt gGmbH", False),
        ("Bäckerei Müller", False),
        # A broker is an employer: only placement of PEOPLE counts.
        ("Versicherungsvermittlung Schmidt GmbH", False),
    ],
)
async def test_ingest_marks_staffing_firms_by_name(name: str, agency: bool) -> None:
    await _ingest(_result(name, 1))
    async with SessionLocal() as s:
        flag = await s.scalar(select(HubCompany.staffing_name).where(HubCompany.name == name))
    assert flag is agency


async def test_excluding_agencies_drops_them_from_the_search_and_its_count() -> None:
    await _ingest(_result("Muster Personalberatung GmbH", 2), _result("Klinikum Musterstadt gGmbH", 2))
    async with SessionLocal() as s:
        everyone = await service.search_employers(s, q="pflegefachkraft")
        employers = await service.search_employers(s, q="pflegefachkraft", exclude_agencies=True)
        total = await service.count_employers(s, q="pflegefachkraft", exclude_agencies=True)
    assert {h["name"] for h in everyone} == {"Muster Personalberatung GmbH", "Klinikum Musterstadt gGmbH"}
    assert [h["name"] for h in employers] == ["Klinikum Musterstadt gGmbH"]
    assert total == 1


# --- size -----------------------------------------------------------------------


async def test_size_buckets_count_open_ads_across_all_sites() -> None:
    # Chain: 3 + 3 = 6 open ads over two sites → "m" (5–19), though no single
    # site reaches 5.
    await _ingest(
        _result("Kette Pflege GmbH", 3, city="Berlin", postcode="10115"),
        _result("Kette Pflege GmbH", 3, city="Hamburg", postcode="20095"),
        _result("Kleiner Dienst GmbH", 2),
        _result("Großklinik AG", 25),
    )
    async with SessionLocal() as s:
        small = await service.search_employers(s, sizes=["s"])
        medium = await service.search_employers(s, sizes=["m"])
        small_or_large = await service.search_employers(s, sizes=["s", "l"])
        counted = await service.count_employers(s, sizes=["m"])
    assert [h["name"] for h in small] == ["Kleiner Dienst GmbH"]
    assert [h["name"] for h in medium] == ["Kette Pflege GmbH"]
    assert {h["name"] for h in small_or_large} == {"Kleiner Dienst GmbH", "Großklinik AG"}
    assert counted == 1


async def test_a_city_filter_does_not_shrink_an_employer_to_one_site() -> None:
    """Size is the employer's, not the matched site's."""
    await _ingest(
        _result("Kette Pflege GmbH", 3, city="Berlin", postcode="10115"),
        _result("Kette Pflege GmbH", 3, city="Hamburg", postcode="20095"),
    )
    async with SessionLocal() as s:
        hits = await service.search_employers(s, city="Berlin", sizes=["m"])
    assert [h["name"] for h in hits] == ["Kette Pflege GmbH"]


# --- route ------------------------------------------------------------------------


async def test_the_search_route_takes_both_filters() -> None:
    from app.core.auth import get_current_tenant
    from app.main import app

    await _ingest(_result("Muster Personalberatung GmbH", 2), _result("Klinikum Musterstadt gGmbH", 2))
    app.dependency_overrides[get_current_tenant] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            url = f"{settings.api_v1_prefix}/hub/search"
            without = await client.get(url, params={"q": "pflegefachkraft", "exclude_agencies": "true"})
            sized = await client.get(url, params={"q": "pflegefachkraft", "size": "s"})
            refused = await client.get(url, params={"size": "huge"})
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
    assert without.status_code == 200, without.text
    assert [h["name"] for h in without.json()["items"]] == ["Klinikum Musterstadt gGmbH"]
    assert sized.status_code == 200 and len(sized.json()["items"]) == 2
    assert refused.status_code == 422
