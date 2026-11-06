"""EURES — Austria and Switzerland (`adapters/eures.py`).

The fixture is eight real records captured 2026-11-06 (descriptions cut to
1,500 characters, translations removed): an AMS employer ad, an AMS ad whose
employer is "siehe Beschreibung", a staffing agency, an employer with a
website, a Bundesagentur ad relayed by EURES, an ad with no region, a Swiss
canton's own ad and a Swiss agency's.

What these tests pin, each measured against the live source:

* Two kinds of record are DROPPED and counted, never stored: an employer the
  source does not name (1,337 of 2,000 Vienna ads), and an ad relayed from the
  Bundesagentur (connection point 1), which BA already supplies.
* Agencies are sorted per ad by a deterministic rule; the plural "für unsere
  Kunden" is an employer talking about its customers and must not count.
* Region is the finest place there is, so it never merges two ads: the
  vacancy key is the ad itself.
* Gone is the portal's own 404 + `se.jv.error.notAvailable`, as for BA.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import agencies, liveness, service
from app.domain.hub.adapters import eures
from app.domain.hub.adapters.base import InvalidQuery, SourceQuery, SourceUnreachable
from app.domain.hub.models import HubCompany, HubJobPosting, HubObservation
from app.domain.hub.resolution import identity_key
from app.domain.hub.schemas import IngestRequest, source_detail_url

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "eures_search.json"
NOW = dt.datetime.now(dt.UTC)
NOT_FOUND = json.dumps({"errorType": "NOT_FOUND", "errorMessage": "se.jv.error.notAvailable"})


def _payload() -> dict:
    return json.loads(FIXTURE.read_text())


def _parse(location: str | None = "at13"):
    return eures.parse_response(_payload(), request_url="x", fetched_at=NOW, location=location)


def _by_name(result) -> dict:
    return {p.company.name: p for p in result.postings}


# --- parsing ------------------------------------------------------------------


def test_unnamed_employers_and_ba_relays_are_dropped_and_counted() -> None:
    result = _parse()
    names = _by_name(result)

    assert "siehe Beschreibung" not in names
    assert "Lars Zimmermann" not in names  # BA reference 10001-1003958088-S, point 1
    assert "Motel One Germany BetriebsGmbH" not in names  # BA reference 14153-…-S, point 1
    assert result.dropped == {"employer not named": 1, "relayed from the Bundesagentur": 2}
    assert len(result.postings) + sum(result.dropped.values()) == len(_payload()["jvs"])


def test_an_austrian_ad_carries_the_bundesland_as_ba_spells_it() -> None:
    spar = _by_name(_parse())["INTERSPAR"]

    assert spar.country == "OESTERREICH"
    assert spar.region == "WIEN"  # AT130 → at13
    assert spar.city is None and spar.postal_code is None  # EURES has neither
    assert spar.company.area == "region:oesterreich:wien"
    assert spar.segment == "employer"
    assert spar.posted_at is not None and spar.posted_at.tzinfo is not None
    assert spar.employment_type == "full_time"


def test_a_swiss_ad_carries_its_canton() -> None:
    canton = _by_name(_parse("ch04"))["Kantonale Verwaltung Zürich"]

    assert (canton.country, canton.region, canton.segment) == ("SCHWEIZ", "ZUERICH", "employer")


def test_an_ad_with_no_region_keeps_its_country() -> None:
    truck = _by_name(_parse("at-NS"))["Driveuro Group B.V."]

    assert (truck.country, truck.region) == ("OESTERREICH", None)
    assert truck.company.area == "region:oesterreich:-"


def test_agencies_go_to_the_agency_segment_with_the_reason() -> None:
    names = _by_name(_parse())
    trenkwalder, ipersonal = names["Trenkwalder Personaldienste"], names["iPersonal AG"]

    assert trenkwalder.segment == ipersonal.segment == "private_recruiter"
    assert trenkwalder.raw["staffing_signal"] == "brand"
    assert ipersonal.raw["staffing_signal"] == "name"


def test_the_stored_copy_leaves_out_the_text_it_already_holds() -> None:
    spar = _by_name(_parse())["INTERSPAR"]

    assert spar.description and spar.description.startswith("INTERSPAR")
    assert "description" not in spar.raw and "translations" not in spar.raw
    assert spar.raw["id"] == spar.external_id


@pytest.mark.parametrize(
    ("employer", "text", "signal"),
    [
        ("Kistler", "Messtechnik für unsere Kunden weltweit", None),  # plural: its customers
        ("Intrum AG", "im Auftrag unserer Auftraggeber", None),
        ("Senevita", "kein Personalverleih", None),
        ("Seestadt AG", "Für unseren Kunden suchen wir eine/n Dachdecker", "text"),
        ("Muster AG", "Unsere Auftraggeberin ist ein KMU", "text"),
        ("CETEO", "setzt unser Kunde Maßstäbe", "text"),
        ("iPersonal AG", "Wir suchen für einen Betrieb in Wallisellen", "name"),
        ("ManpowerGroup", None, "brand"),
        ("Kelly", None, "brand"),
        ("Kelly's Bar", None, None),
        ("Hayser Bau", None, None),
        ("Erste Group Bank AG", None, None),
        ("Arbeitskräfteüberlassung Sistek HR Consulting", None, "name"),
        ("Versicherungsvermittlung Huber", None, None),  # a broker, an employer
        ("Muster SA", "Pour notre client, une PME active", "text"),
        ("Muster SA", "Per un nostro cliente cerchiamo", "text"),
        ("Intérim Plus SA", None, "name"),
    ],
)
def test_the_staffing_rule(employer: str, text: str | None, signal: str | None) -> None:
    assert eures.staffing_signal(employer, text) == signal


def test_ad_text_is_unescaped_and_stripped_of_markup() -> None:
    raw = "---base:meta-keywords: x--- Analyst Digital Identity \\&amp;amp; Open Banking <b>(80\\-100%)</b>&nbsp;"
    assert eures.clean_text(raw) == "Analyst Digital Identity & Open Banking (80-100%)"


@pytest.mark.parametrize(
    ("nuts", "name"),
    [("AT130", "WIEN"), ("AT31", "OBEROESTERREICH"), ("AT323", "SALZBURG"),
     ("CH040", "ZUERICH"), ("CH07", "TESSIN"), ("CH02", None), ("DE30", None), (None, None)],
)
def test_region_names(nuts: str | None, name: str | None) -> None:
    assert eures.region_name(nuts) == name


# --- the question asked -------------------------------------------------------


def test_a_query_is_never_wider_than_austria_and_switzerland() -> None:
    body = eures.EuresAdapter().query_body(SourceQuery(published_since_days=1))

    assert body["locationCodes"] == ["at", "ch"]
    assert body["publicationPeriod"] == "LAST_DAY"
    assert body["resultsPerPage"] == 50  # the source's maximum


@pytest.mark.parametrize(
    "query",
    [
        SourceQuery(where="Berlin"),          # a place name, not a bucket
        SourceQuery(where="de1"),             # Germany is BA's
        SourceQuery(where="at31", sector="z"),
        SourceQuery(page=201),                # the source answers 400 past 200
        SourceQuery(published_since_days=14), # no such window: would be "everything"
        SourceQuery(segment="private_recruiter"),
    ],
)
def test_a_question_the_source_cannot_answer_is_refused(query: SourceQuery) -> None:
    with pytest.raises(InvalidQuery):
        eures.EuresAdapter().query_body(query)


def test_every_bucket_is_a_region_or_no_region() -> None:
    assert len(eures.REGIONS) == 18
    assert {"at-NS", "ch-NS", "at31", "ch04"} <= set(eures.REGIONS)


def test_the_listing_plans_from_our_two_countries_only() -> None:
    page = eures.parse_listing(_payload())

    assert page.total_available == 61804
    assert set(page.facets) == {"region", "sector"}
    assert page.facets["region"]["at31"] == 15401
    assert page.facets["region"]["ch-NS"] == 530
    assert not any(code.startswith("de") for code in page.facets["region"])
    assert sum(page.facets["sector"].values()) > 0
    assert len(page.external_ids) == page.records == 8  # relays too: liveness is per ad


@pytest.mark.parametrize(
    ("status", "body", "verdict"),
    [
        (200, "{}", "live"),
        (404, NOT_FOUND, "gone"),
        (404, '{"errorType":"NOT_FOUND","errorMessage":"other"}', "unknown"),
        (404, "<html>not found</html>", "unknown"),
        (404, "[]", "unknown"),
        (500, NOT_FOUND, "unknown"),
        (429, "", "unknown"),
    ],
)
def test_gone_needs_the_portals_own_not_found(status: int, body: str, verdict: str) -> None:
    assert eures.liveness_from_response(status, body) == verdict


def test_the_portal_link_is_derived_from_the_id() -> None:
    assert source_detail_url("eures", "MTc0MDExOTAgNDM") == (
        "https://europa.eu/eures/portal/jv-se/jv-details/MTc0MDExOTAgNDM?lang=de"
    )


# --- HTTP, against a fake source ----------------------------------------------


def _adapter(handler) -> eures.EuresAdapter:
    return eures.EuresAdapter(transport=httpx.MockTransport(handler))


async def test_fetch_posts_the_body_and_parses_the_answer() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_payload())

    result = await _adapter(handler).fetch(SourceQuery(where="at31", sector="c", page=3))

    assert seen[0]["locationCodes"] == ["at31"] and seen[0]["sectorCodes"] == ["c"]
    assert seen[0]["page"] == 3
    assert result.http_status == 200 and result.total_available == 61804
    assert result.dropped["employer not named"] == 1


async def test_check_live_asks_the_detail_page() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(404, text=NOT_FOUND)

    assert await _adapter(handler).check_live("MTc0MDExOTAgNDM") == "gone"
    assert urls == ["https://europa.eu/eures/api/jv-searchengine/public/jv/id/MTc0MDExOTAgNDM?lang=de"]


async def test_a_transport_error_is_unreachable_not_gone() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(SourceUnreachable):
        await _adapter(handler).check_live("x")


# --- into the corpus ----------------------------------------------------------


class _Fixed:
    name = "eures"

    def __init__(self, location: str = "at13") -> None:
        self.location = location

    async def fetch(self, query: SourceQuery):
        return eures.parse_response(
            _payload(), request_url="x", fetched_at=dt.datetime.now(dt.UTC), location=self.location
        )


async def _ingest():
    async with SessionLocal() as s:
        return await service.ingest(
            s, adapter=_Fixed(), request=IngestRequest(source="eures", where="at13", published_since_days=1)
        )


async def _eures_rows() -> list[tuple[HubJobPosting, HubCompany]]:
    async with SessionLocal() as s:
        return list((await s.execute(
            select(HubJobPosting, HubCompany)
            .join(HubCompany, HubCompany.id == HubJobPosting.hub_company_id)
            .where(HubJobPosting.source == "eures")
        )).all())


async def test_each_ad_lands_in_its_own_segment() -> None:
    summary = await _ingest()
    rows = {company.name: (posting, company) for posting, company in await _eures_rows()}

    assert summary.postings_created == 5
    assert summary.dropped == {"employer not named": 1, "relayed from the Bundesagentur": 2}
    spar, spar_co = rows["INTERSPAR"]
    agency, agency_co = rows["Trenkwalder Personaldienste"]
    assert (spar.segment, spar_co.kind) == ("employer", "employer")
    assert (agency.segment, agency_co.kind) == ("private_recruiter", "private_recruiter")
    assert agency_co.dedupe_key.startswith("pav:")  # never merges onto an employer
    assert spar_co.dedupe_key == "name_place:interspar:region:oesterreich:wien"
    assert spar_co.city is None


async def test_an_ad_with_no_place_counts_as_itself_from_the_start() -> None:
    await _ingest()
    for posting, _ in await _eures_rows():
        assert posting.vacancy_key == f"id:{posting.id.hex}"


async def test_a_second_run_creates_nothing() -> None:
    await _ingest()
    again = await _ingest()

    assert (again.postings_created, again.companies_created) == (0, 0)
    assert again.postings_updated == 5


async def test_agency_profiles_stay_bundesagentur_only() -> None:
    await _ingest()
    async with SessionLocal() as s:
        await agencies.refresh_profiles(s)
        await s.commit()
        from app.domain.hub.models import HubAgencyProfile

        names = (await s.execute(select(HubAgencyProfile.name))).scalars().all()
    assert not any("Trenkwalder" in n or "iPersonal" in n for n in names)


def test_identity_area_is_only_a_last_resort() -> None:
    assert identity_key(name="Spar", postal_code="1090", area="region:oesterreich:wien") == (
        "name_place", "name_place:spar:1090",
    )
    assert identity_key(name="Spar", area="region:oesterreich:wien") == (
        "name_place", "name_place:spar:region:oesterreich:wien",
    )
    assert identity_key(name="Spar") is None


# --- liveness, per source -----------------------------------------------------


class _Answers:
    def __init__(self, name: str, answers: dict[str, str]) -> None:
        self.name = name
        self.answers = answers
        self.calls: list[str] = []

    async def check_live(self, external_id: str) -> str:
        self.calls.append(external_id)
        return self.answers.get(external_id, "live")


async def _two_sources() -> None:
    """One due suspect and one control per source."""
    async with SessionLocal() as s:
        company = HubCompany(
            name="Test GmbH", normalized_name="test", dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place", source="bundesagentur",
            first_seen_at=NOW, last_seen_at=NOW, open_postings_count=0,
        )
        s.add(company)
        await s.flush()
        for source in ("bundesagentur", "eures"):
            for ext, due in ((f"{source}-gone", NOW - dt.timedelta(hours=1)), (f"{source}-control", None)):
                s.add(HubJobPosting(
                    hub_company_id=company.id, title="Koch", source=source, external_id=ext,
                    content_hash="x",
                    first_seen_at=NOW, last_seen_at=NOW, is_active=True, posted_at=NOW,
                    unlisted_at=due, check_due_at=due,
                ))
        await s.commit()


@pytest.fixture(autouse=True)
def _no_cached_control():
    liveness._control_cache.clear()
    yield
    liveness._control_cache.clear()


async def test_a_batch_checks_only_its_own_sources_queue() -> None:
    await _two_sources()
    source = _Answers("eures", {"eures-gone": "gone"})
    async with SessionLocal() as s:
        result = await liveness.check_batch(s, adapter=source, limit=10, delay=0)

    assert result["closed"] == 1 and result["checked"] == 1
    assert source.calls == ["eures-control", "eures-gone"]  # BA's ads never asked
    async with SessionLocal() as s:
        ba = await s.scalar(select(HubJobPosting).where(HubJobPosting.external_id == "bundesagentur-gone"))
        observation = await s.scalar(select(HubObservation).where(HubObservation.note.like("liveness:%")))
    assert ba.is_active and ba.check_due_at is not None
    assert observation.source == "eures"


async def test_marking_one_source_leaves_the_other_alone() -> None:
    await _two_sources()
    async with SessionLocal() as s:
        marked = await liveness.mark(
            s, segment="employer", unlisted=["bundesagentur-control", "eures-control"], listed=[],
            source="eures",
        )
    assert marked == {"unlisted": 1, "listed": 0}


# --- endpoints ----------------------------------------------------------------


async def _client() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize(
    ("source", "filters"),
    [("eures", {"berufsfeld": "Verkauf"}), ("bundesagentur", {"region": "at31"})],
)
async def test_a_listing_filter_of_the_other_source_is_refused(source: str, filters: dict) -> None:
    async with await _client() as client:
        r = await client.post(
            f"{settings.api_v1_prefix}/hub/liveness/listing",
            json={"source": source, "filters": filters, "page": 1},
        )
    assert r.status_code == 422


async def test_an_ingest_slice_for_an_unknown_bucket_is_refused_before_any_request() -> None:
    async with await _client() as client:
        r = await client.post(
            f"{settings.api_v1_prefix}/hub/ingest",
            json={"source": "eures", "where": "Wien", "published_since_days": 1},
        )
    assert r.status_code == 422
    assert "unknown EURES location" in r.text


@pytest.mark.parametrize(
    ("url", "kept"),
    [("http://www.motel-one.com", True), ("https://acme.jobs.personio.de/job/1", False),
     ("https://www.karriere.at/jobs/1", False), ("https://join.com/companies/x", False), (None, False)],
)
def test_a_host_many_employers_share_is_not_an_identity(url: str | None, kept: bool) -> None:
    assert (eures.employer_website(url) is not None) is kept


def test_a_multi_country_ad_has_one_identity_whichever_bucket_returns_it() -> None:
    payload = _payload()
    payload["jvs"][0]["locationMap"] = {"CH": ["CH040"], "AT": ["AT130"]}  # INTERSPAR
    seen = [
        eures.parse_response(payload, request_url="x", fetched_at=NOW, location=bucket).postings[0]
        for bucket in ("at13", "ch04")
    ]
    assert {(p.country, p.region, p.company.area) for p in seen} == {
        ("OESTERREICH", "WIEN", "region:oesterreich:wien")
    }


def test_a_placeholder_with_punctuation_is_still_unnamed() -> None:
    payload = _payload()
    payload["jvs"][0]["employer"]["name"] = "Siehe Beschreibung!"
    result = eures.parse_response(payload, request_url="x", fetched_at=NOW, location="at13")
    assert result.dropped["employer not named"] == 2


def test_section_v_can_be_asked_for() -> None:
    assert eures.build_body(location="at31", sector="v", window=None, page=1)["sectorCodes"] == ["v"]
    assert IngestRequest(source="eures", sector="v").sector == "v"
