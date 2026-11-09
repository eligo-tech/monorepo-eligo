"""Tech roles: `hub/families.py` and the Markt filter.

`fixtures/families/labelled_titles.csv` holds 120 real open-ad titles drawn
at random from production on 2026-11-09 — 60 the rule called tech, 60 it
called not tech but that carry a tech-looking word — each labelled by hand
(tech = software, data, ML/AI, IT operations and security, product and
design of digital products). It measures the rule; it was also used to tune
it, so it is a regression guard, not an independent benchmark.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import families, service
from app.domain.hub.adapters.base import FetchResult, SourcedCompany, SourcedPosting
from app.domain.hub.models import HubJobPosting

LABELLED = pathlib.Path(__file__).parent / "fixtures" / "families" / "labelled_titles.csv"


def test_the_rule_agrees_with_hand_labels() -> None:
    rows = list(csv.DictReader(LABELLED.open()))
    assert len(rows) == 120
    tp = fp = fn = 0
    for row in rows:
        said = families.job_family(row["title"], row["berufsfeld"] or None) == families.TECH
        truth = row["tech"] == "1"
        tp += said and truth
        fp += said and not truth
        fn += truth and not said
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    assert precision >= 0.97, (precision, fp)
    assert recall >= 0.97, (recall, fn)


@pytest.mark.parametrize(("title", "field", "tech"), [
    # decided 2026-11-09: product and design of digital products are tech
    ("Product Manager (m/w/d)", None, True),
    ("Product Owner (gn)", None, True),
    ("UX/UI Designer (m/w/d)", None, True),
    ("Senior Product Designer", None, True),
    ("Produktmanager Digital (m/w/d)", None, True),
    ("Produktmanager Lebensmittel (m/w/d)", None, False),
    ("Grafikdesigner (m/w/d)", None, False),
    # engineers: only with a tech qualifier
    ("Senior Software Engineer", None, True),
    ("Data Engineer (m/w/d)", None, True),
    ("Mechanical Engineer (m/w/d)", None, False),
    ("Sales Engineer (m/w/d)", None, False),
    ("Automation Engineer (m/f/d) PLC & Commissioning", None, False),
    ("Reliability Engineer Fertigung", None, False),
    # German compounds and domain words
    ("Softwareentwickler Maschinenbau (m/w/d)", None, True),
    ("Java-Entwickler (m/w/d)", None, True),
    ("Personalentwickler (m/w/d)", None, False),
    ("Business Developer (m/w/d)", None, False),
    ("Hardware Entwickler (m/w/d)", None, False),
    ("Fachinformatiker für Systemintegration", None, True),
    ("Architekt (m/w/d) Hochbau", None, False),
    ("Cloud Architect (m/w/d)", None, True),
    # "IT" only in capitals, and only as the role's domain
    ("IT-Systemadministrator (m/w/d)", None, True),
    ("Projektmanager Digitalisierung & IT (m/w/d)", None, True),
    ("Fit for it – Lagerhelfer (m/w/d)", None, False),
    ("Volljurist (m/w/d) IT-Recht", None, False),
    ("Bilanzbuchhalter (m/w/d) für ein IT-Unternehmen", None, False),
    ("Key Account Manager IT (m/w/d)", None, False),
    ("IT-Recruiter (m/w/d)", None, False),
    # the Bundesagentur's IT fields, unless the role is sales or the like
    ("Mitarbeiter (m/w/d)", "Informatik", True),
    ("Vertriebsmitarbeiter (m/w/d)", "IT-Systemanalyse, -Anwendungsberatung und -Vertrieb", False),
    ("Programmierer CNC-Drehmaschinen", "Softwareentwicklung und Programmierung", False),
    ("", None, False),
])
def test_tech_is_decided_by_rules(title, field, tech) -> None:
    assert (families.job_family(title, field) == families.TECH) is tech


# --- ingest, backfill, search -------------------------------------------------------


def _result(*titles: str) -> FetchResult:
    now = dt.datetime.now(dt.UTC)
    return FetchResult(
        source="greenhouse", request_url="https://example.test/feed", fetched_at=now, http_status=200,
        robots_allowed=True, total_available=len(titles), content_hash=None,
        postings=[
            SourcedPosting(
                external_id=f"acme:{i}", title=title, company=SourcedCompany(
                    name="Acme Software GmbH", postal_code="10115", city="Berlin", country="DEUTSCHLAND"),
                postal_code="10115", city="Berlin", country="DEUTSCHLAND", raw={},
            )
            for i, title in enumerate(titles)
        ],
    )


async def test_an_ad_is_classified_when_it_comes_in_and_when_its_title_changes() -> None:
    async with SessionLocal() as s:
        await service.merge_fetch(s, result=_result("Senior Software Engineer", "Office Manager"), key="t")
    async with SessionLocal() as s:
        got = dict((await s.execute(select(HubJobPosting.title, HubJobPosting.job_family))).all())
    assert got == {"Senior Software Engineer": "tech", "Office Manager": "other"}

    async with SessionLocal() as s:
        await service.merge_fetch(s, result=_result("Senior Software Engineer", "IT-Systemadministrator"), key="t")
    async with SessionLocal() as s:
        row = await s.scalar(select(HubJobPosting).where(HubJobPosting.external_id == "acme:1"))
    assert (row.title, row.job_family) == ("IT-Systemadministrator", "tech")


async def test_the_backfill_classifies_older_ads_in_batches() -> None:
    async with SessionLocal() as s:
        await service.merge_fetch(s, result=_result("Data Scientist", "Koch (m/w/d)", "UX Designer"), key="t")
        await s.execute(HubJobPosting.__table__.update().values(job_family=None))
        await s.commit()
    async with SessionLocal() as s:
        first = await families.backfill(s, limit=2)
    assert first == {"classified": 2, "remaining": 1}
    async with SessionLocal() as s:
        second = await families.backfill(s, limit=2)
        got = dict((await s.execute(select(HubJobPosting.title, HubJobPosting.job_family))).all())
    assert second == {"classified": 1, "remaining": 0}
    assert got == {"Data Scientist": "tech", "Koch (m/w/d)": "other", "UX Designer": "tech"}


async def test_the_tech_filter_keeps_employers_with_a_tech_role_and_shows_only_those_roles() -> None:
    async with SessionLocal() as s:
        await service.merge_fetch(s, result=_result("Senior Software Engineer", "Office Manager"), key="t")
        other = _result("Koch (m/w/d)")
        other.postings[0].company.name, other.postings[0].external_id = "Gasthaus Krone", "krone:1"
        await service.merge_fetch(s, result=other, key="t2")
    async with SessionLocal() as s:
        hits = await service.search_employers(s, families=["tech"])
        total = await service.count_employers(s, families=["tech"])
    assert total == 1 and [h["name"] for h in hits] == ["Acme Software GmbH"]
    assert hits[0]["open_roles"] == 1  # the office manager is not counted
    assert [r.title for r in hits[0]["matching_roles"]] == ["Senior Software Engineer"]


async def test_the_search_route_takes_the_tech_filter() -> None:
    from app.core.auth import get_current_tenant
    from app.main import app

    app.dependency_overrides[get_current_tenant] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            ok = await client.get(f"{settings.api_v1_prefix}/hub/search", params={"family": "tech"})
            refused = await client.get(f"{settings.api_v1_prefix}/hub/search", params={"family": "nursing"})
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
    assert ok.status_code == 200, ok.text
    assert refused.status_code == 422


async def test_stats_count_tech_roles() -> None:
    async with SessionLocal() as s:
        await service.merge_fetch(s, result=_result("Senior Software Engineer", "Office Manager"), key="t")
    async with SessionLocal() as s:
        facets = await service.corpus_facets(s)
    assert {"value": "tech", "count": 1} in facets["families"]
    assert facets["families_pending"] == 0
    async with SessionLocal() as s:
        await s.execute(HubJobPosting.__table__.update().values(job_family=None))
        await s.commit()
        service._corpus_cache.clear()  # facets are cached for minutes by design
        assert (await service.corpus_facets(s))["families_pending"] == 2
