"""ELI-54: employer headcount on Markt — the passes, the filter, the gate.

* The weekly ad-text pass stores what an employer's own ads say, with the
  quote and the ad it came from, and re-reads only when new text arrived.
* Wikidata matches ONLY by exact identity (official website = the stored
  registrable domain), never by name; mocked HTTP, no network.
* The Markt filter matches a range against every bucket it overlaps, hides
  unknown-size employers and says how many; it is offered only from 30%
  coverage, computed by the weekly snapshot.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import headcount, service
from app.domain.hub.adapters import wikidata
from app.domain.hub.adapters.base import FetchResult, SourcedCompany, SourcedPosting
from app.domain.hub.models import HubCompany, HubJobPosting, HubObservation, HubPostingPayload


def _result(employer: str, texts: list[str | None], *, domain: str | None = None,
            postcode: str = "10115", city: str = "Berlin") -> FetchResult:
    now = dt.datetime.now(dt.UTC)
    slug = employer.split()[0].lower()
    return FetchResult(
        source="bundesagentur", request_url="https://example.test/feed", fetched_at=now,
        http_status=200, robots_allowed=True, total_available=len(texts), content_hash=None,
        postings=[
            SourcedPosting(
                external_id=f"{slug}:{city}:{i}", title=f"Pflegefachkraft {i}",
                company=SourcedCompany(name=employer, website_domain=domain, postal_code=postcode,
                                       city=city, country="DEUTSCHLAND"),
                description=text, postal_code=postcode, city=city, country="DEUTSCHLAND", raw={},
            )
            for i, text in enumerate(texts)
        ],
    )


async def _ingest(*results: FetchResult) -> None:
    async with SessionLocal() as s:
        for i, result in enumerate(results):
            await service.merge_fetch(s, result=result, key=f"k{i}")


async def _stamp_texts() -> None:
    """The ingest stores inline texts; give them a fetch time like the
    description pass does."""
    async with SessionLocal() as s:
        for p in (await s.execute(select(HubJobPosting))).scalars():
            p.description_fetched_at = p.description_fetched_at or dt.datetime.now(dt.UTC)
        await s.commit()


async def _company(name: str) -> HubCompany:
    async with SessionLocal() as s:
        return (await s.execute(select(HubCompany).where(HubCompany.name == name))).scalars().first()


async def _run_backfill() -> list[dict]:
    out, after = [], None
    async with SessionLocal() as s:
        while True:
            r = await headcount.backfill(s, limit=2, after=after)
            out.append(r)
            if r["done"]:
                return out
            after = __import__("uuid").UUID(r["last_id"])


# --- the ad-text pass -------------------------------------------------------------------


async def test_the_pass_stores_the_statement_with_its_evidence() -> None:
    await _ingest(
        _result("Klinikum Muster gGmbH", [
            "Mit rund 250 Mitarbeitenden sind wir ein Haus der Grundversorgung.",
            "Sie arbeiten in einem Team von 15 Mitarbeitern.",
        ]),
        _result("Bäckerei Ohne GmbH", ["Wir backen täglich frisch."]),
    )
    await _stamp_texts()
    await _run_backfill()
    sized = await _company("Klinikum Muster gGmbH")
    assert (sized.employees_min, sized.employees_max, sized.employees_source) == (250, 250, "ad_text")
    assert sized.employees_evidence == "Mit rund 250 Mitarbeitenden sind wir ein Haus der Grundversorgung."
    assert sized.employees_source_ref == "bundesagentur:klinikum:Berlin:0"
    assert sized.employees_rules == headcount.HEADCOUNT_RULES
    unsized = await _company("Bäckerei Ohne GmbH")
    assert unsized.employees_min is None and unsized.employees_rules == headcount.HEADCOUNT_RULES


async def test_a_second_run_reads_nothing_until_new_text_arrives() -> None:
    await _ingest(_result("Klinikum Muster gGmbH", ["Mit über 500 Mitarbeitern sind wir groß."]))
    await _stamp_texts()
    await _run_backfill()
    again = await _run_backfill()
    assert sum(r["read"] for r in again) == 0
    # A newer ad text queues the company again.
    async with SessionLocal() as s:
        p = (await s.execute(select(HubJobPosting))).scalars().first()
        p.description_fetched_at = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)
        await s.commit()
    assert sum(r["read"] for r in await _run_backfill()) == 1
    c = await _company("Klinikum Muster gGmbH")
    assert (c.employees_min, c.employees_max) == (500, None)


async def test_a_value_its_own_ad_no_longer_states_is_cleared() -> None:
    await _ingest(_result("Klinikum Muster gGmbH", ["Mit rund 250 Mitarbeitenden sind wir da."]))
    await _stamp_texts()
    await _run_backfill()
    async with SessionLocal() as s:
        payload = (await s.execute(select(HubPostingPayload))).scalars().first()
        payload.description = "Wir freuen uns auf Sie."
        p = (await s.execute(select(HubJobPosting))).scalars().first()
        p.description_fetched_at = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)
        await s.commit()
    await _run_backfill()
    c = await _company("Klinikum Muster gGmbH")
    assert c.employees_min is None and c.employees_source is None


async def test_an_ad_without_stored_text_does_not_requeue_its_employer() -> None:
    # The text pass stamps the fetch even when the source returned no text.
    await _ingest(_result("Klinikum Muster gGmbH", ["Mit über 500 Mitarbeitern sind wir groß.", None]))
    async with SessionLocal() as s:
        for p in (await s.execute(select(HubJobPosting))).scalars():
            p.description_fetched_at = dt.datetime.now(dt.UTC)
        await s.commit()
    await _run_backfill()
    assert sum(r["read"] for r in await _run_backfill()) == 0
    assert (await _company("Klinikum Muster gGmbH")).employees_min == 500


# --- Wikidata --------------------------------------------------------------------------------


def _sparql(*rows: tuple[str, str, str, str | None]) -> dict:
    bindings = []
    for item, site, n, t in rows:
        b = {
            "item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{item}"},
            "site": {"type": "uri", "value": site},
            "n": {"type": "literal", "value": n},
        }
        if t:
            b["t"] = {"type": "literal", "value": t}
        bindings.append(b)
    return {"results": {"bindings": bindings}}


def test_wikidata_matches_only_the_exact_registrable_domain() -> None:
    payload = _sparql(
        ("Q1", "https://www.muster-klinik.de/", "1200", "2023-01-01T00:00:00Z"),
        ("Q1", "https://www.muster-klinik.de/", "1100", "2021-01-01T00:00:00Z"),
        # Another domain the query did not ask about: ignored.
        ("Q2", "https://muster-klinik.com/", "9", None),
    )
    hits = wikidata.parse_bindings(payload, ["muster-klinik.de"])
    assert set(hits) == {"muster-klinik.de"}
    assert (hits["muster-klinik.de"].qid, hits["muster-klinik.de"].employees) == ("Q1", 1200)
    assert hits["muster-klinik.de"].as_of == dt.datetime(2023, 1, 1, tzinfo=dt.UTC)


def test_two_items_claiming_one_website_are_not_an_identity() -> None:
    payload = _sparql(
        ("Q1", "https://muster.de/", "100", None),
        ("Q2", "http://www.muster.de", "5000", None),
    )
    assert wikidata.parse_bindings(payload, ["muster.de"]) == {}


def test_the_query_asks_by_website_iri_never_by_name() -> None:
    q = wikidata.build_query(["muster.de"])
    assert "<https://www.muster.de/>" in q and "<http://muster.de>" in q
    assert "rdfs:label" not in q and "CONTAINS" not in q.upper()
    assert "P1128" in q and "P856" in q


async def test_wikidata_pass_sizes_by_domain_and_keeps_newer_ad_statements() -> None:
    await _ingest(
        _result("Muster Klinik GmbH", [None], domain="muster-klinik.de"),
        # Same NAME, other domain: must not be touched.
        _result("Muster Klinik GmbH", [None], domain="andere-klinik.de", postcode="20095", city="Hamburg"),
        _result("Fabrik AG", ["Mit rund 250 Mitarbeitenden fertigen wir Teile."], domain="fabrik.de"),
    )
    await _stamp_texts()
    await _run_backfill()

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append({"ua": request.headers["user-agent"], "body": request.content.decode()})
        return httpx.Response(200, json=_sparql(
            ("Q1", "https://www.muster-klinik.de/", "1200", "2023-01-01T00:00:00Z"),
            ("Q7", "https://fabrik.de/", "300", "2020-01-01T00:00:00Z"),
        ))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = wikidata.WikidataClient(http=http, pause=0)
    async with SessionLocal() as s:
        result = await headcount.wikidata_backfill(s, limit=100, client=client)
    assert result["failed"] == 0 and result["matched"] == 2
    assert sent and sent[0]["ua"] == settings.hub_user_agent

    async with SessionLocal() as s:
        rows = {
            (r.website_domain): r
            for r in (await s.execute(select(HubCompany))).scalars()
        }
        observations = (await s.execute(select(HubObservation).where(HubObservation.source == "wikidata"))).scalars().all()
    klinik = rows["muster-klinik.de"]
    assert (klinik.employees_min, klinik.employees_source, klinik.employees_source_ref) == (1200, "wikidata", "Q1")
    assert "P1128" in klinik.employees_evidence
    assert rows["andere-klinik.de"].employees_min is None
    # The 2020 Wikidata figure does not replace this week's ad statement.
    assert (rows["fabrik.de"].employees_min, rows["fabrik.de"].employees_source) == (250, "ad_text")
    assert len(observations) == 1 and observations[0].http_status == 200

    # Asked domains are stamped: a second run asks nothing.
    async with SessionLocal() as s:
        again = await headcount.wikidata_backfill(s, limit=100, client=client)
    assert again["asked"] == 0 and len(sent) == 1


async def test_a_domain_shared_by_two_employers_is_not_an_identity() -> None:
    # A group's site used by a subsidiary: the group's P1128 is not theirs.
    # Ingested without a domain (one row each); the domain arrives later, e.g.
    # from the Impressum backfill, onto two rows of different employers.
    await _ingest(
        _result("Gruppe Holding AG", [None]),
        _result("Tochter Service GmbH", [None], postcode="20095", city="Hamburg"),
    )
    async with SessionLocal() as s:
        for c in (await s.execute(select(HubCompany))).scalars():
            c.website_domain = "gruppe.de"
        await s.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_sparql(("Q9", "https://gruppe.de/", "50000", "2024-01-01T00:00:00Z")))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with SessionLocal() as s:
        result = await headcount.wikidata_backfill(s, limit=100, client=wikidata.WikidataClient(http=http, pause=0))
    assert result["sized"] == 0
    assert (await _company("Tochter Service GmbH")).employees_min is None
    assert (await _company("Gruppe Holding AG")).employees_min is None


async def test_a_refused_wikidata_query_stamps_nothing() -> None:
    await _ingest(_result("Muster Klinik GmbH", [None], domain="muster-klinik.de"))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    async with SessionLocal() as s:
        result = await headcount.wikidata_backfill(
            s, limit=100, client=wikidata.WikidataClient(http=http, pause=0)
        )
    assert result["failed"] == 1 and result["asked"] == 0
    assert (await _company("Muster Klinik GmbH")).employees_wikidata_at is None


# --- EURES -------------------------------------------------------------------------------------


async def test_a_eures_size_code_is_stored_at_ingest() -> None:
    from app.domain.hub.adapters import eures

    payload = {
        "numberRecords": 1,
        "jvs": [{
            "id": "abc-1", "title": "Koch", "description": "Wir kochen.",
            "creationDate": "2026-11-01T00:00:00Z",
            "employer": {"name": "Gasthaus Alpen GmbH", "organisationSizeCode": "10-49"},
            "locationMap": {"AT": ["AT33"]},
        }],
    }
    result = eures.parse_response(
        payload, request_url="https://eures.test", fetched_at=dt.datetime.now(dt.UTC), location="at",
    )
    assert (result.postings[0].company.employees_min, result.postings[0].company.employees_max) == (10, 49)
    await _ingest(result)
    c = await _company("Gasthaus Alpen GmbH")
    assert (c.employees_min, c.employees_max, c.employees_source) == (10, 49, "eures")
    assert c.employees_source_ref == "eures:abc-1"


# --- the filter --------------------------------------------------------------------------------


async def _sized(name: str, lo: int | None, hi: int | None) -> None:
    async with SessionLocal() as s:
        for c in (await s.execute(select(HubCompany).where(HubCompany.name == name))).scalars():
            c.employees_min, c.employees_max, c.employees_source = lo, hi, "ad_text"
        await s.commit()


async def _three_employers() -> None:
    await _ingest(
        _result("Klein GmbH", [None]),
        _result("Mittel GmbH", [None]),
        _result("Gross AG", [None]),
        _result("Unbekannt GmbH", [None]),
    )
    await _sized("Klein GmbH", 8, 8)
    await _sized("Mittel GmbH", 51, 200)
    await _sized("Gross AG", 500, None)


async def test_a_range_matches_every_bucket_it_overlaps_and_unknown_is_hidden() -> None:
    await _three_employers()
    async with SessionLocal() as s:
        small = await service.search_employers(s, employees=["4-10"])
        mid = await service.search_employers(s, employees=["151-300"])
        big = await service.search_employers(s, employees=["10001+"])
        both = await service.count_employers(s, employees=["4-10", "51-150"])
        unknown = await service.count_employers(s, employees_unknown=True)
    assert [h["name"] for h in small] == ["Klein GmbH"]
    # 51–200 overlaps 151–300 …
    assert [h["name"] for h in mid] == ["Mittel GmbH"]
    # … and "über 500" overlaps every bucket above.
    assert [h["name"] for h in big] == ["Gross AG"]
    assert both == 2
    assert unknown == 1


async def test_the_chip_shows_the_site_the_filter_matched() -> None:
    await _ingest(
        _result("Kette GmbH", [None], postcode="10115", city="Berlin"),
        _result("Kette GmbH", [None], postcode="20095", city="Hamburg"),
    )
    async with SessionLocal() as s:
        rows = (await s.execute(select(HubCompany).order_by(HubCompany.city))).scalars().all()
        rows[0].employees_min = rows[0].employees_max = 80   # Berlin, older
        rows[0].employees_as_of = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        rows[1].employees_min = rows[1].employees_max = 5000  # Hamburg, newer
        rows[1].employees_as_of = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
        for r in rows:
            r.employees_source = "ad_text"
        await s.commit()
        (hit,) = await service.search_employers(s, employees=["51-150"])
    assert hit["headcount"]["min"] == 80


async def test_hits_carry_the_size_and_its_evidence() -> None:
    await _three_employers()
    async with SessionLocal() as s:
        (hit,) = await service.search_employers(s, employees=["4-10"])
    assert hit["headcount"]["min"] == 8 and hit["headcount"]["source"] == "ad_text"


async def test_the_route_reports_how_many_have_no_size() -> None:
    await _three_employers()
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/v1/hub/search", params=[("employees", "4-10"), ("employees", "51-150")])
        plain = await client.get("/api/v1/hub/search")
        bad = await client.get("/api/v1/hub/search", params={"employees": "7-9"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and body["unknown_size"] == 1
    assert plain.json()["unknown_size"] is None
    assert bad.status_code == 422


# --- coverage gate ------------------------------------------------------------------------------


async def test_coverage_gates_the_filter_at_thirty_percent() -> None:
    await _three_employers()  # 3 of 4 hiring employers sized
    async with SessionLocal() as s:
        cov = await headcount.coverage(s)
    assert (cov["known"], cov["employers"], cov["filter_available"]) == (3, 4, True)
    assert {b["value"]: b["count"] for b in cov["buckets"]}["301-650"] == 1

    await _sized("Mittel GmbH", None, None)
    await _sized("Gross AG", None, None)  # 1 of 4 = 25%
    async with SessionLocal() as s:
        cov = await headcount.coverage(s)
    assert cov["filter_available"] is False and cov["coverage"] == 0.25


async def test_facets_carry_the_coverage_from_the_snapshot() -> None:
    await _three_employers()
    async with SessionLocal() as s:
        await service.refresh_corpus_snapshots(s)
        facets = await service.corpus_facets(s)
    assert facets["headcount"]["filter_available"] is True


# --- machine-only -------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/v1/hub/headcount/backfill", "/api/v1/hub/headcount/wikidata"])
async def test_the_passes_are_operator_routes(path: str, monkeypatch) -> None:
    from app.main import app

    monkeypatch.setattr(settings, "ingest_token", "secret-token")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        anonymous = await client.post(path)
        machine = await client.post(
            path + "?limit=10", headers={"Authorization": "Bearer secret-token"}
        )
    assert anonymous.status_code in (401, 403)
    assert machine.status_code == 200, machine.text
