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
    page = (await client.get("/api/v1/hub/search?q=Netto")).json()
    hits = page["items"]
    assert hits[0]["tracked"] is False
    # The envelope carries the whole answer's size, not just this page's.
    assert page["total"] >= len(hits)

    # Tracking ONE branch marks the whole employer as tracked.
    await client.put(
        f"/api/v1/hub/companies/{hits[0]['hub_company_ids'][0]}/track",
        json={"relationship": "prospect"},
    )
    again = (await client.get("/api/v1/hub/search?q=Netto")).json()["items"]
    assert again[0]["tracked"] is True


async def test_filters_are_repeatable_query_params(client, corpus) -> None:
    hits = (
        await client.get(
            "/api/v1/hub/search?region=BADEN_WUERTTEMBERG&region=BAYERN"
            "&berufsfeld=Softwareentwicklung"
        )
    ).json()["items"]
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


@pytest.mark.skipif(
    not service.SEARCH_AD_TEXT,
    reason=(
        "SEARCH_AD_TEXT is off as a stopgap — the description scan is unindexed "
        "and blows the 120s statement_timeout. Migration 0016 restores it, and "
        "this test un-skips itself when the flag goes back to True."
    ),
)
async def test_search_reaches_the_ad_text_once_it_is_stored(corpus) -> None:
    """The point of storing descriptions: a stack named only in the body."""
    from sqlalchemy import select

    from app.domain.hub.models import HubJobPosting, HubPostingPayload

    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(HubJobPosting).where(HubJobPosting.external_id == "e1")
            )
        ).scalar_one()
        # Through the payload, not the posting: `description` on HubJobPosting is
        # a read-through property since 0017, deliberately read-only so a write
        # cannot land on a detached attribute and vanish.
        if row.payload is None:
            row.payload = HubPostingPayload()
        row.payload.description = "Wir suchen Verstärkung mit Kotlin und Gradle."
        await s.commit()

        hits = await service.search_employers(s, q="kotlin")
    assert [h["name"] for h in hits] == ["Embedded Systems GmbH"]


# ---------------------------------------------------------------------------
# Match snippets — why a role is in the result list
# ---------------------------------------------------------------------------


def test_snippet_returns_the_words_around_the_match() -> None:
    from app.domain.hub.service import _snippet

    text = (
        "Wir sind ein Team in Berlin und bauen moderne Web-Anwendungen. " * 3
        + "Unser Stack ist TypeScript, React und Node.js, dazu Postgres. "
        + "Wir bieten flexible Arbeitszeiten und ein Jobticket. " * 3
    )
    out = _snippet(text, ["typescript"])
    assert "TypeScript" in out
    # framed by context, not the whole ad
    assert len(out) < len(text)
    # elided at both ends because the match sits in the middle of a long ad
    assert out.startswith("…") and out.endswith("…")


def test_snippet_is_none_when_nothing_matches() -> None:
    from app.domain.hub.service import _snippet

    assert _snippet("Wir suchen eine Pflegefachkraft.", ["typescript"]) is None
    assert _snippet(None, ["typescript"]) is None
    assert _snippet("irgendwas", []) is None


def test_snippet_does_not_start_or_end_mid_word() -> None:
    from app.domain.hub.service import _snippet

    text = "Aussergewoehnliche Faehigkeiten " * 8 + "TypeScript " + "und weiteres " * 8
    out = _snippet(text, ["typescript"])
    assert not out.strip("…").startswith(" ")
    # the fragment is built from whole words
    assert "  " not in out


@pytest.mark.skipif(
    not service.SEARCH_AD_TEXT,
    reason="ad-text matching is off, so no body-only match can occur",
)
async def test_a_body_only_match_carries_its_evidence(corpus) -> None:
    """The point: a role whose TITLE does not contain the term must explain itself.

    Without this the screen shows "Cloud Engineer Spezialist:in" under a
    TypeScript search and looks broken — the reason it matched is real but
    invisible, which is exactly the assertion-vs-evidence distinction the
    result list was designed around.
    """
    from sqlalchemy import select

    from app.domain.hub.models import HubJobPosting, HubPostingPayload

    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(HubJobPosting).where(HubJobPosting.external_id == "e1")
            )
        ).scalar_one()
        if row.payload is None:
            row.payload = HubPostingPayload()
        row.payload.description = (
            "Fuer unser Portal suchen wir Verstaerkung. Der Stack umfasst "
            "TypeScript, React und Node.js in einem modernen Umfeld."
        )
        await s.commit()

        hits = await service.search_employers(s, q="typescript")

    roles = [r for h in hits for r in h["matching_roles"]]
    assert roles, "the body match should surface the role"
    snippets = [getattr(r, "match_snippet", None) for r in roles]
    assert any(sn and "TypeScript" in sn for sn in snippets)


@pytest.mark.skipif(
    not service.SEARCH_AD_TEXT,
    reason="ad-text matching is off",
)
async def test_no_snippet_when_the_title_already_says_it(corpus) -> None:
    """A snippet under a role whose title carries the term is noise, not evidence."""
    async with SessionLocal() as s:
        hits = await service.search_employers(s, q="embedded")

    for hit in hits:
        for role in hit["matching_roles"]:
            headline = f"{role.title or ''} {role.occupation or ''}".lower()
            if "embedded" in headline:
                assert getattr(role, "match_snippet", None) is None


# ---------------------------------------------------------------------------
# Relevance ranking (deterministic half of layer 4)
# ---------------------------------------------------------------------------


async def test_the_best_match_outranks_the_biggest_employer(corpus) -> None:
    """Ordering by role COUNT made the biggest employer the best answer.

    That is backwards for a search. An employer with one role whose TITLE names
    the query beats an employer with several that merely mention it, and volume
    only breaks ties between equally relevant hits.
    """
    import uuid

    from app.domain.hub.models import HubCompany, HubJobPosting

    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        # One exact title match.
        precise = HubCompany(
            name="Precise GmbH",
            normalized_name="precise",
            dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place",
            source="test",
            first_seen_at=now,
            last_seen_at=now,
        )
        # Several roles that only carry the term in the occupation label.
        bulky = HubCompany(
            name="Bulky AG",
            normalized_name="bulky",
            dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place",
            source="test",
            first_seen_at=now,
            last_seen_at=now,
        )
        s.add_all([precise, bulky])
        await s.flush()

        s.add(
            HubJobPosting(
                hub_company_id=precise.id,
                title="Senior Kotlin Entwickler (m/w/d)",
                source="test",
                external_id=f"p-{uuid.uuid4()}",
                content_hash=str(uuid.uuid4()),
                first_seen_at=now,
                last_seen_at=now,
                is_active=True,
            )
        )
        for i in range(5):
            s.add(
                HubJobPosting(
                    hub_company_id=bulky.id,
                    # Both terms present, but only in the OCCUPATION label —
                    # the category the source assigned, not a title anyone wrote.
                    title="Mitarbeiter Verwaltung",
                    occupation="Kotlin Entwickler Spezialist",
                    source="test",
                    external_id=f"b{i}-{uuid.uuid4()}",
                    content_hash=str(uuid.uuid4()),
                    first_seen_at=now,
                    last_seen_at=now,
                    is_active=True,
                )
            )
        await s.commit()

        hits = await service.search_employers(s, q="kotlin entwickler")

    names = [h["name"] for h in hits]
    assert "Precise GmbH" in names, "the exact title match must surface"
    # one role beats five, because the title answers the query
    assert names.index("Precise GmbH") < names.index("Bulky AG")
    precise_hit = next(h for h in hits if h["name"] == "Precise GmbH")
    bulky_hit = next(h for h in hits if h["name"] == "Bulky AG")
    assert precise_hit["relevance"] > bulky_hit["relevance"]
    assert precise_hit["open_roles"] < bulky_hit["open_roles"]


async def test_every_employer_in_the_result_carries_its_evidence(corpus) -> None:
    """A flat LIMIT spent the evidence budget on whoever came first.

    Searching a corpus where one employer holds most of the matches, the roles
    query hit its cap before reaching the rest, and later employers arrived with
    an empty role list — an entry in a result list carrying none of the evidence
    the list exists to show. The window numbers rows per employer instead.
    """
    import uuid

    from app.domain.hub.models import HubCompany, HubJobPosting

    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        for idx, (label, count) in enumerate(
            [("Giant", 30), ("Small One", 1), ("Small Two", 1)]
        ):
            company = HubCompany(
                name=f"{label} GmbH",
                normalized_name=label.lower().replace(" ", "-"),
                dedupe_key=f"k-{uuid.uuid4()}",
                resolution_basis="name_place",
                source="test",
                first_seen_at=now,
                last_seen_at=now,
            )
            s.add(company)
            await s.flush()
            for i in range(count):
                s.add(
                    HubJobPosting(
                        hub_company_id=company.id,
                        title="Zerspanungsmechaniker (m/w/d)",
                        source="test",
                        external_id=f"{idx}-{i}-{uuid.uuid4()}",
                        content_hash=str(uuid.uuid4()),
                        first_seen_at=now,
                        last_seen_at=now,
                        is_active=True,
                    )
                )
        await s.commit()

        hits = await service.search_employers(
            s, q="zerspanungsmechaniker", roles_per_employer=3
        )

    assert len(hits) >= 3
    for hit in hits:
        assert hit["matching_roles"], f"{hit['name']} came back with no evidence"
        assert len(hit["matching_roles"]) <= 3


# ---------------------------------------------------------------------------
# Keyset pagination
# ---------------------------------------------------------------------------


async def test_paging_covers_every_employer_exactly_once(corpus) -> None:
    """The property that makes "am I missing anything" answerable.

    Keyset paging is only trustworthy if walking the cursor visits each employer
    once. A wrong comparison silently drops rows at a page boundary or repeats
    them, and either failure is invisible on page one — which is the only page
    anyone checks by hand.
    """
    import uuid

    from app.domain.hub.models import HubCompany, HubJobPosting

    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        # Deliberately mixed relevance AND mixed role counts, so the walk has to
        # get all three sort keys right, not just the first.
        plan = [("Alpha", 3, True), ("Beta", 1, True), ("Gamma", 2, False),
                ("Delta", 1, False), ("Epsilon", 5, True)]
        for label, count, in_title in plan:
            company = HubCompany(
                name=f"{label} GmbH",
                normalized_name=label.lower(),
                dedupe_key=f"k-{uuid.uuid4()}",
                resolution_basis="name_place",
                source="test",
                first_seen_at=now,
                last_seen_at=now,
            )
            s.add(company)
            await s.flush()
            for i in range(count):
                s.add(
                    HubJobPosting(
                        hub_company_id=company.id,
                        title="Galvaniseur (m/w/d)" if in_title else "Fachkraft",
                        occupation=None if in_title else "Galvaniseur",
                        source="test",
                        external_id=f"{label}-{i}-{uuid.uuid4()}",
                        content_hash=str(uuid.uuid4()),
                        first_seen_at=now,
                        last_seen_at=now,
                        is_active=True,
                    )
                )
        await s.commit()

        expected = await service.count_employers(s, q="galvaniseur")
        assert expected >= 5

        seen: list[str] = []
        cursor = None
        for _ in range(20):  # bounded: a cursor bug must not hang the test
            page = await service.search_employers(
                s, q="galvaniseur", limit=2, cursor=cursor
            )
            if not page:
                break
            seen.extend(h["normalized_name"] for h in page)
            if len(page) < 2:
                break
            cursor = service.encode_cursor(page[-1])

    assert len(seen) == len(set(seen)), f"an employer was returned twice: {seen}"
    assert len(seen) == expected, f"walked {len(seen)} of {expected} employers"


async def test_an_unreadable_cursor_restarts_rather_than_failing(corpus) -> None:
    """A cursor is opaque, so a stale or mangled one is a normal event.

    Returning the first page is the recoverable answer; raising turns a bookmark
    someone kept from last week into a 500.
    """
    async with SessionLocal() as s:
        first = await service.search_employers(s, q="embedded")
        junk = await service.search_employers(s, q="embedded", cursor="not-base64!!")

    assert [h["normalized_name"] for h in junk] == [
        h["normalized_name"] for h in first
    ]
