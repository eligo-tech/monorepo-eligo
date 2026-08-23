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


async def _posting(
    session,
    company,
    title: str,
    ext: str,
    occupation: str | None = None,
    berufsfeld: str | None = None,
    region: str | None = None,
):
    now = dt.datetime.now(dt.UTC)
    session.add(
        HubJobPosting(
            hub_company_id=company.id,
            title=title,
            occupation=occupation,
            berufsfeld=berufsfeld,
            region=region,
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
        # As many postings as each site's counter claims — the fixture has to be
        # internally consistent now that the reported number IS a count of
        # matching postings rather than a denormalized column.
        regions = ("BERLIN", "NORDRHEIN_WESTFALEN", "BADEN_WUERTTEMBERG")
        for site, (comp, region) in enumerate(
            zip((a1, a2, a3), regions, strict=True)
        ):
            for n in range(comp.open_postings_count):
                await _posting(
                    s, comp, "Verkäufer (m/w/d)", f"n{site}-{n}", "Verkäufer/in",
                    berufsfeld="Verkauf", region=region,
                )
        await _posting(
            s, b, "Embedded Software Entwickler", "e1", "Softwareentwickler/in",
            berufsfeld="Softwareentwicklung", region="BADEN_WUERTTEMBERG",
        )
        await _posting(
            s, b, "Senior Firmware Entwickler", "e2", "Softwareentwickler/in",
            berufsfeld="Softwareentwicklung", region="BAYERN",
        )
        await _posting(
            s, c, "Pflegefachkraft", "p1", "Pflegefachmann/-frau",
            berufsfeld="Krankenpflege", region="BADEN_WUERTTEMBERG",
        )
        await s.commit()


async def test_stats_count_the_corpus_not_a_page(corpus) -> None:
    async with SessionLocal() as s:
        stats = await service.corpus_stats(s)
    assert stats["companies"] == 5
    # Three Netto rows collapse to one employer, so 5 rows are 3 employers.
    assert stats["employers"] == 3
    assert stats["open_postings"] == 9   # 2+3+1 Verkauf, 2 Software, 1 Pflege
    assert stats["cities"] == 4          # Berlin, Köln, Ulm, Stuttgart
    assert stats["unverified_identity"] == 5
    assert stats["last_ingest_at"] is None  # nothing ingested, only seeded


async def test_search_rolls_branches_up_into_one_employer(corpus) -> None:
    async with SessionLocal() as s:
        hits = await service.search_employers(s, q="Netto")
    assert len(hits) == 1, "238 branches must not be 238 rows"
    hit = hits[0]
    assert hit["sites"] == 3
    # A hit on the COMPANY name makes all of its roles relevant.
    assert hit["open_roles"] == 6          # 2 + 3 + 1
    assert set(hit["cities"]) == {"Berlin", "Köln", "Ulm"}
    assert hit["city_count"] == 3


async def test_the_count_matches_the_evidence(corpus) -> None:
    """The headline number must count the SAME roles it lists underneath.

    Regression: `open_roles` was SUM(open_postings_count) — every active posting
    at the employer — while the list was filtered. A search for "Embedded" then
    reported "2 Rollen" above a single Embedded role, which a recruiter reads as
    two Embedded vacancies.
    """
    async with SessionLocal() as s:
        # "Firmware" hits ONE of Embedded Systems GmbH's two roles, and does not
        # appear in the company name — so this isolates role matching. Searching
        # "Embedded" would legitimately return both, because the company itself
        # matches and then all of its roles are relevant.
        hits = await service.search_employers(s, q="Firmware")
    assert len(hits) == 1
    assert hits[0]["open_roles"] == 1, "counted roles that did not match"
    assert len(hits[0]["matching_roles"]) == 1
    assert hits[0]["open_roles"] == len(hits[0]["matching_roles"])


async def test_a_company_name_hit_counts_all_of_its_roles(corpus) -> None:
    """The other half of the rule: match the employer, and every role counts."""
    async with SessionLocal() as s:
        hits = await service.search_employers(s, q="Embedded Systems")
    assert hits[0]["open_roles"] == 2
    assert len(hits[0]["matching_roles"]) == 2


async def test_the_count_respects_structured_filters_too(corpus) -> None:
    async with SessionLocal() as s:
        hits = await service.search_employers(
            s, berufsfelder=["Softwareentwicklung"], regions=["BAYERN"]
        )
    # Two software roles exist, but only one is in Bayern.
    assert hits[0]["open_roles"] == 1
    assert [r.region for r in hits[0]["matching_roles"]] == ["BAYERN"]


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


# ---------------------------------------------------------------------------
# Structured filters
# ---------------------------------------------------------------------------


async def test_regions_widen_and_berufsfeld_narrows(corpus) -> None:
    """OR within a filter, AND across them."""
    async with SessionLocal() as s:
        bw = await service.search_employers(s, regions=["BADEN_WUERTTEMBERG"])
        assert {h["name"] for h in bw} == {
            "Embedded Systems GmbH",
            "Klinikum Musterstadt",
            "Netto Marken-Discount Stiftung & Co. KG",
        }

        # A second region widens.
        widened = await service.search_employers(
            s, regions=["BADEN_WUERTTEMBERG", "BERLIN"]
        )
        assert len(widened) >= len(bw)

        # A Berufsfeld narrows within it.
        narrowed = await service.search_employers(
            s, regions=["BADEN_WUERTTEMBERG"], berufsfelder=["Softwareentwicklung"]
        )
        assert [h["name"] for h in narrowed] == ["Embedded Systems GmbH"]


async def test_a_filtered_hit_shows_only_matching_roles_as_evidence(corpus) -> None:
    """Filtered to BW, an employer must not justify itself with a Bayern role."""
    async with SessionLocal() as s:
        hits = await service.search_employers(
            s, regions=["BADEN_WUERTTEMBERG"], berufsfelder=["Softwareentwicklung"]
        )
    roles = hits[0]["matching_roles"]
    assert [r.region for r in roles] == ["BADEN_WUERTTEMBERG"]
    assert "Senior Firmware Entwickler" not in [r.title for r in roles]


async def test_an_employer_qualifies_through_a_role_not_its_head_office(corpus) -> None:
    """Embedded Systems GmbH sits in Stuttgart but has a Bayern vacancy."""
    async with SessionLocal() as s:
        hits = await service.search_employers(s, regions=["BAYERN"])
    assert [h["name"] for h in hits] == ["Embedded Systems GmbH"]


async def test_facets_are_derived_from_the_corpus(corpus) -> None:
    async with SessionLocal() as s:
        facets = await service.corpus_facets(s)
    fields = {f["value"]: f["count"] for f in facets["berufsfelder"]}
    assert fields == {"Verkauf": 6, "Softwareentwicklung": 2, "Krankenpflege": 1}
    regions = {r["value"] for r in facets["regions"]}
    assert "BAYERN" in regions
    # Options are ordered by volume so the useful ones surface first.
    counts = [f["count"] for f in facets["berufsfelder"]]
    assert counts == sorted(counts, reverse=True)


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


async def test_filters_are_repeatable_query_params(client, corpus) -> None:
    hits = (
        await client.get(
            "/api/v1/hub/search?region=BADEN_WUERTTEMBERG&region=BAYERN"
            "&berufsfeld=Softwareentwicklung"
        )
    ).json()
    assert [h["name"] for h in hits] == ["Embedded Systems GmbH"]
    assert hits[0]["matching_roles"][0]["berufsfeld"] == "Softwareentwicklung"


async def test_stats_endpoint_matches_the_service(client, corpus) -> None:
    body = (await client.get("/api/v1/hub/stats")).json()
    assert body["companies"] == 5 and body["employers"] == 3


async def test_a_multi_word_query_ands_its_terms(corpus) -> None:
    """Regression: the query is a set of terms, not a phrase.

    `LIKE '%embedded entwickler%'` required the words adjacent in that order, so
    "Embedded Software Entwickler" was invisible. Measured on the real corpus,
    one such query lost 5 of 5 matches.
    """
    async with SessionLocal() as s:
        # Adjacent in neither order, but both words are present.
        hits = await service.search_employers(s, q="entwickler embedded")
    assert [h["name"] for h in hits] == ["Embedded Systems GmbH"]
    assert "Embedded Software Entwickler" in [
        r.title for r in hits[0]["matching_roles"]
    ]


async def test_every_term_must_match_somewhere(corpus) -> None:
    async with SessionLocal() as s:
        # "firmware" matches a role; "zzz" matches nothing — so the pair must not.
        assert await service.search_employers(s, q="firmware zzz") == []
        assert len(await service.search_employers(s, q="firmware")) == 1


async def test_terms_match_per_posting_not_across_the_employer(corpus) -> None:
    """Embedded Systems GmbH has an "Embedded" role and a "Firmware" role.

    A query for both words must not match on the strength of two DIFFERENT
    postings — otherwise "python entwickler" would hit any company that happens
    to have one Python role and one unrelated Entwickler role.
    """
    async with SessionLocal() as s:
        hits = await service.search_employers(s, q="embedded firmware")
    # "Embedded" is in the company name, so the company matches both terms —
    # legitimate. What must NOT happen is a role list containing roles that
    # satisfy only one term each.
    for hit in hits:
        for role in hit["matching_roles"]:
            haystack = f"{role.title} {role.occupation or ''} {hit['name']}".lower()
            assert "embedded" in haystack and "firmware" in haystack or "embedded" in hit["name"].lower()


async def test_search_reaches_the_ad_text_once_it_is_stored(corpus) -> None:
    """The point of storing descriptions: a stack named only in the body."""
    from sqlalchemy import select

    from app.domain.hub.models import HubJobPosting

    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(HubJobPosting).where(HubJobPosting.external_id == "e1")
            )
        ).scalar_one()
        row.description = "Wir suchen Verstärkung mit Kotlin und Gradle."
        await s.commit()

        hits = await service.search_employers(s, q="kotlin")
    assert [h["name"] for h in hits] == ["Embedded Systems GmbH"]
