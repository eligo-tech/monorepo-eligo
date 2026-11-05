"""One vacancy, counted once — `hub/vacancy.py`.

Measured 2026-11-05 on 1,219 live Bundesagentur ads: 59 (4.8%) repeated an
ad already in the sample — same employer, same title once "(m/w/d)" is
stripped, same place, a different reference. Mostly job boards relaying one
vacancy several times (studyflix 7×, jobware, heyjobs). Across sources it is
worse by construction: Bosch has 1,049 ads at the Bundesagentur and 763 on
its own SmartRecruiters board, most of them the same roles.

Identity is deterministic (ARCHITECTURE.md RULE 5): same employer + same
normalized title + same place. Near-matches are NOT merged.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.hub import service, vacancy
from app.domain.hub.models import HubCompany, HubJobPosting
from app.domain.hub.resolution import normalize_company_name
from app.domain.hub.vacancy import normalize_title, vacancy_key

NOW = dt.datetime.now(dt.UTC)


# --- the key, pure ------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        ("Pflegefachkraft (m/w/d)", "Pflegefachkraft"),
        ("Pflegefachkraft (w/m/d)", "pflegefachkraft (d/m/w)"),
        ("Mechatroniker*in", "Mechatroniker (m/w/d)"),
        ("Verkäufer/in", "Verkäufer (m/w/x)"),
        ("Kaufmann/-frau im Einzelhandel", "Kaufmann/-frau im Einzelhandel (all genders)"),
        ("Softwareentwickler:in Java", "Softwareentwickler Java (gn)"),
        ("Elektriker – Gebäudetechnik", "Elektriker - Gebäudetechnik"),
        ("Data Engineer (m/f/d)", "Data Engineer (f/m/d)"),
    ],
)
def test_gender_tags_and_punctuation_do_not_make_a_new_vacancy(a: str, b: str) -> None:
    assert normalize_title(a) == normalize_title(b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Senior Developer", "Developer"),           # a different role
        ("Pflegefachkraft Nachtdienst", "Pflegefachkraft"),
        ("Werkstudent Marketing", "Praktikum Marketing"),
    ],
)
def test_a_near_match_is_not_the_same_vacancy(a: str, b: str) -> None:
    assert normalize_title(a) != normalize_title(b)


def test_same_employer_title_and_place_is_one_key() -> None:
    k = vacancy_key("bosch", "Mechatroniker (m/w/d)", postal_code="70839", city="Gerlingen")
    assert k == vacancy_key("bosch", "Mechatroniker*in", postal_code="70839", city="gerlingen")
    assert k != vacancy_key("bosch", "Mechatroniker*in", postal_code="70469", city="Stuttgart")
    assert k != vacancy_key("siemens", "Mechatroniker*in", postal_code="70839", city="Gerlingen")


def test_the_postcode_wins_over_the_city_and_the_city_stands_in_without_one() -> None:
    # A feed that names the same postcode with a district spelling is one place…
    assert vacancy_key("x", "Koch", postal_code="80331", city="München") == vacancy_key(
        "x", "Koch", postal_code="80331", city="München-Altstadt"
    )
    # …and without a postcode the city is the place.
    assert vacancy_key("x", "Koch", postal_code=None, city="München") == vacancy_key(
        "x", "Koch", postal_code="", city=" münchen "
    )


def test_no_key_without_a_title_or_an_employer() -> None:
    assert vacancy_key("x", "", postal_code="1", city="a") is None
    assert vacancy_key("x", "(m/w/d)", postal_code="1", city="a") is None
    assert vacancy_key("", "Koch", postal_code="1", city="a") is None


# --- in the corpus ------------------------------------------------------------


async def _company(s, name: str, city: str = "Gerlingen") -> HubCompany:
    row = HubCompany(
        name=name, normalized_name=normalize_company_name(name), dedupe_key=f"k-{uuid.uuid4()}",
        resolution_basis="name_place", city=city, source="test",
        first_seen_at=NOW, last_seen_at=NOW, open_postings_count=0,
    )
    s.add(row)
    await s.flush()
    return row


def _posting(company: HubCompany, title: str, ext: str, *, source: str = "bundesagentur", plz: str = "70839", keyed: bool = True, active: bool = True) -> HubJobPosting:
    return HubJobPosting(
        hub_company_id=company.id, title=title, source=source, external_id=ext, content_hash=ext,
        postal_code=plz, city=company.city, first_seen_at=NOW, last_seen_at=NOW, is_active=active,
        posted_at=NOW,
        vacancy_key=vacancy_key(company.normalized_name, title, postal_code=plz, city=company.city) if keyed else None,
    )


async def test_search_counts_a_relayed_vacancy_once_and_names_its_sources() -> None:
    async with SessionLocal() as s:
        bosch = await _company(s, "Robert Bosch GmbH")
        s.add_all([
            _posting(bosch, "Mechatroniker (m/w/d)", "ba-1"),
            _posting(bosch, "Mechatroniker*in", "ba-2"),                     # relayed by a board
            _posting(bosch, "Mechatroniker (m/w/d)", "sr-1", source="smartrecruiters"),
            _posting(bosch, "Mechatroniker (m/w/d)", "ba-3", plz="70469"),   # another site
        ])
        await s.commit()
    async with SessionLocal() as s:
        hits = await service.search_employers(s, q="mechatroniker")

    assert len(hits) == 1
    assert hits[0]["open_roles"] == 2
    roles = hits[0]["matching_roles"]
    assert len(roles) == 2
    relayed = next(r for r in roles if r.postal_code == "70839")
    assert relayed.copies == 3
    assert relayed.sources == ["bundesagentur", "smartrecruiters"]


async def test_an_ad_without_a_key_yet_still_counts_as_itself() -> None:
    """The backfill runs over nights; until then nothing may vanish."""
    async with SessionLocal() as s:
        firm = await _company(s, "Muster GmbH")
        s.add_all([
            _posting(firm, "Koch", "a", keyed=False),
            _posting(firm, "Koch", "b", keyed=False),
        ])
        await s.commit()
    async with SessionLocal() as s:
        hits = await service.search_employers(s, q="koch")
    assert hits[0]["open_roles"] == 2


async def test_the_companys_open_roles_count_vacancies_not_ads() -> None:
    from tests.test_hub_ingest import StubAdapter, _fetch_result
    from app.domain.hub.schemas import IngestRequest

    result = _fetch_result()
    first = result.postings[0]
    twin = type(first)(**{**first.__dict__, "external_id": first.external_id + "-relay"})
    result.postings.append(twin)
    async with SessionLocal() as s:
        await service.ingest(s, adapter=StubAdapter(result), request=IngestRequest(where="Berlin"))

    async with SessionLocal() as s:
        rows = (await s.execute(
            select(HubJobPosting).where(HubJobPosting.external_id.in_([first.external_id, twin.external_id]))
        )).scalars().all()
        assert len(rows) == 2 and rows[0].vacancy_key and rows[0].vacancy_key == rows[1].vacancy_key
        company = await s.get(HubCompany, rows[0].hub_company_id)
        ads = (await s.execute(
            select(HubJobPosting).where(HubJobPosting.hub_company_id == company.id, HubJobPosting.is_active)
        )).scalars().all()
    assert company.open_postings_count == len({p.vacancy_key for p in ads})
    assert company.open_postings_count == len(ads) - 1


async def test_corpus_stats_count_vacancies() -> None:
    async with SessionLocal() as s:
        firm = await _company(s, "Muster GmbH")
        s.add_all([_posting(firm, "Koch", "a"), _posting(firm, "Koch (m/w/d)", "b"), _posting(firm, "Kellner", "c")])
        await s.commit()
    async with SessionLocal() as s:
        stats = await service.corpus_stats(s)
    assert stats["open_postings"] == 2


# --- the backfill -------------------------------------------------------------


async def test_the_backfill_keys_open_ads_in_bounded_batches() -> None:
    async with SessionLocal() as s:
        firm = await _company(s, "Muster GmbH")
        s.add_all([_posting(firm, f"Koch {i}", f"k{i}", keyed=False) for i in range(5)])
        s.add(_posting(firm, "Closed", "closed", keyed=False, active=False))
        await s.commit()

    async with SessionLocal() as s:
        first = await vacancy.backfill(s, limit=3)
    async with SessionLocal() as s:
        second = await vacancy.backfill(s, limit=3)
    assert (first["keyed"], first["remaining"]) == (3, 2)
    assert (second["keyed"], second["remaining"]) == (2, 0)

    async with SessionLocal() as s:
        rows = {p.external_id: p for p in (await s.execute(select(HubJobPosting))).scalars()}
    assert all(rows[f"k{i}"].vacancy_key for i in range(5))
    assert rows["closed"].vacancy_key is None  # closed ads are not worth the write


async def test_the_backfill_endpoint_is_machine_only() -> None:
    from tests.test_operator_endpoints import DECLARED_OPERATOR_ROUTES

    assert ("POST", "/hub/vacancy-keys/backfill") in DECLARED_OPERATOR_ROUTES


async def test_the_nightly_job_drains_the_backlog_in_batches_and_stops_when_done() -> None:
    import httpx

    from scripts.hub_daily import _key_vacancies

    asked: list[int] = []
    left = {"n": 12_000}

    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params["limit"])
        asked.append(n)
        keyed = min(n, left["n"])
        left["n"] -= keyed
        return httpx.Response(200, json={"keyed": keyed, "remaining": left["n"]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://api") as client:
        assert await _key_vacancies(client, budget=50_000) == {"keyed": 12_000, "remaining": 0}
        assert asked == [5_000, 5_000, 5_000]
        asked.clear()
        left["n"] = 100_000
        assert (await _key_vacancies(client, budget=7_000))["keyed"] == 7_000
        assert asked == [5_000, 2_000]
