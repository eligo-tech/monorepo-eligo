"""Corpus search and stats — the recruiter-facing read path.

Two properties matter here and neither is cosmetic:
  * stats are counted in the DATABASE, not over whatever page the UI loaded,
  * results are EMPLOYERS, rolled up across sites, because `name_place` identity
    produces one corpus row per branch and a discounter would otherwise bury
    every specialist employer beneath a few hundred of its own stores.
"""

from __future__ import annotations

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.hub import service
from app.domain.hub.models import HubCompany, HubJobPosting
from app.main import app


async def _company(session, name: str, city: str, key: str, roles: int = 0) -> HubCompany:
    from app.domain.hub.resolution import normalize_company_name

    now = dt.datetime.now(dt.UTC)
    row = HubCompany(
        name=name,
        normalized_name=normalize_company_name(name),
        dedupe_key=key,
        resolution_basis="name_place",
        city=city,
        source="test",
        open_postings_count=roles,
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(row)
    return row


async def _posting(session, company, title: str, ext: str, occupation: str | None = None):
    now = dt.datetime.now(dt.UTC)
    session.add(
        HubJobPosting(
            hub_company_id=company.id,
            title=title,
            occupation=occupation,
            source="test",
            external_id=ext,
            content_hash=ext,
            first_seen_at=now,
            last_seen_at=now,
            is_active=True,
            city=company.city,
        )
    )


@pytest.fixture
async def corpus():
    """A discounter with three branches plus two specialist employers."""
    async with SessionLocal() as s:
        a1 = await _company(s, "Netto Marken-Discount Stiftung & Co. KG", "Berlin", "k1", 2)
        a2 = await _company(s, "Netto Marken-Discount Stiftung & Co. KG", "Köln", "k2", 3)
        a3 = await _company(s, "Netto Marken-Discount Stiftung & Co. KG", "Ulm", "k3", 1)
        b = await _company(s, "Embedded Systems GmbH", "Stuttgart", "k4", 2)
        c = await _company(s, "Klinikum Musterstadt", "Stuttgart", "k5", 1)
        await s.flush()
        for i, comp in enumerate((a1, a2, a3)):
            await _posting(s, comp, "Verkäufer (m/w/d)", f"n{i}", "Verkäufer/in")
        await _posting(s, b, "Embedded Software Entwickler", "e1", "Softwareentwickler/in")
        await _posting(s, b, "Senior Firmware Entwickler", "e2", "Softwareentwickler/in")
        await _posting(s, c, "Pflegefachkraft", "p1", "Pflegefachmann/-frau")
        await s.commit()


async def test_stats_count_the_corpus_not_a_page(corpus) -> None:
    async with SessionLocal() as s:
        stats = await service.corpus_stats(s)
    assert stats["companies"] == 5
    # Three Netto rows collapse to one employer, so 5 rows are 3 employers.
    assert stats["employers"] == 3
    assert stats["open_postings"] == 6
    assert stats["cities"] == 4          # Berlin, Köln, Ulm, Stuttgart
    assert stats["unverified_identity"] == 5
    assert stats["last_ingest_at"] is None  # nothing ingested, only seeded


async def test_search_rolls_branches_up_into_one_employer(corpus) -> None:
    async with SessionLocal() as s:
        hits = await service.search_employers(s, q="Netto")
    assert len(hits) == 1, "238 branches must not be 238 rows"
    hit = hits[0]
    assert hit["sites"] == 3
    assert hit["open_roles"] == 6          # 2 + 3 + 1
    assert set(hit["cities"]) == {"Berlin", "Köln", "Ulm"}
    assert hit["city_count"] == 3


async def test_search_matches_on_roles_not_only_names(corpus) -> None:
    """A recruiter asks who is hiring embedded engineers, not for a company name."""
    async with SessionLocal() as s:
        hits = await service.search_employers(s, q="Embedded")
    assert [h["name"] for h in hits] == ["Embedded Systems GmbH"]
    titles = [r.title for r in hits[0]["matching_roles"]]
    assert "Embedded Software Entwickler" in titles


async def test_results_carry_the_roles_that_justify_them(corpus) -> None:
    async with SessionLocal() as s:
        hits = await service.search_employers(s, q="Pflege")
    assert len(hits) == 1
    # Only the matching role comes back — the answer shows its own evidence.
    assert [r.title for r in hits[0]["matching_roles"]] == ["Pflegefachkraft"]


async def test_city_filter_and_min_roles(corpus) -> None:
    async with SessionLocal() as s:
        stuttgart = await service.search_employers(s, city="Stuttgart")
        assert {h["name"] for h in stuttgart} == {
            "Embedded Systems GmbH",
            "Klinikum Musterstadt",
        }
        big = await service.search_employers(s, min_roles=5)
        assert [h["name"] for h in big] == [
            "Netto Marken-Discount Stiftung & Co. KG"
        ]


async def test_empty_query_returns_the_whole_corpus_ranked(corpus) -> None:
    async with SessionLocal() as s:
        hits = await service.search_employers(s)
    assert [h["open_roles"] for h in hits] == sorted(
        [h["open_roles"] for h in hits], reverse=True
    )


async def test_a_query_matching_nothing_returns_nothing(corpus) -> None:
    async with SessionLocal() as s:
        assert await service.search_employers(s, q="zzzznomatch") == []


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_search_endpoint_reports_tracking_per_employer(client, corpus) -> None:
    hits = (await client.get("/api/v1/hub/search?q=Netto")).json()
    assert hits[0]["tracked"] is False

    # Tracking ONE branch marks the whole employer as tracked.
    await client.put(
        f"/api/v1/hub/companies/{hits[0]['hub_company_ids'][0]}/track",
        json={"relationship": "prospect"},
    )
    again = (await client.get("/api/v1/hub/search?q=Netto")).json()
    assert again[0]["tracked"] is True


async def test_stats_endpoint_matches_the_service(client, corpus) -> None:
    body = (await client.get("/api/v1/hub/stats")).json()
    assert body["companies"] == 5 and body["employers"] == 3
