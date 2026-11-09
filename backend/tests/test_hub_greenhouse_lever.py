"""Greenhouse and Lever boards → the shared corpus.

Fixtures are real answers captured 2026-11-09, ad text cut short:
`greenhouse/board.json` — four jobs from Agile Robots SE's EU-hosted board
(Munich, Fürstenfeldbruck, Kaufbeuren, and a "General Application" placed at
"Agile Robots SE"); `lever/board.json` — two Graz jobs from Blackshark.ai's
EU-hosted board; `lever/blackshark_board_page.html` — the first 2 KB of its
board page.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import ats
from app.domain.hub.adapters import greenhouse, lever, places
from app.domain.hub.adapters.boards import FeedAnswer, FeedUnreadable
from app.domain.hub.models import HubAtsBoard, HubJobPosting
from app.domain.hub.schemas import source_detail_url
from scripts import hub_ats

FIX = pathlib.Path(__file__).parent / "fixtures"
GH_MUNICH = "4964865101"
LV_GRAZ = "d425eda5-52ca-4e5c-a03d-b506b3ef6d3f"


def _gh() -> dict:
    return json.loads((FIX / "greenhouse" / "board.json").read_text())


def _lv() -> list:
    return json.loads((FIX / "lever" / "board.json").read_text())


# --- free-text locations ---------------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [
    ("Munich, Bavaria, Germany", ("DEUTSCHLAND", "Munich", None)),
    ("Revaler Straße 28-31, 10245 Berlin", ("DEUTSCHLAND", "Berlin", "10245")),
    ("Munich Hybrid (NavVis GmbH)", ("DEUTSCHLAND", "Munich", None)),
    ("AT-Vienna", ("OESTERREICH", "Vienna", None)),
    ("Germany - Düsseldorf", ("DEUTSCHLAND", "Düsseldorf", None)),
    ("Germany - Remote", ("DEUTSCHLAND", None, None)),
    ("Zug", ("SCHWEIZ", "Zug", None)),
    ("London; Berlin, Germany", ("DEUTSCHLAND", "Berlin", None)),
    ("Berlin OR Remote (Europe)", ("DEUTSCHLAND", "Berlin", None)),
    ("Hamburg, NY", None),
    ("Basel, Germany", None),
    ("Remote, US", None),
    ("Remote", None),
    ("Agile Robots SE", None),
])
def test_a_location_text_is_read_as_a_dach_place_or_not_at_all(text, expected) -> None:
    place = places.dach_place(text)
    assert (place and (place["country"], place["city"], place["postal_code"])) == expected


# --- Greenhouse ------------------------------------------------------------------


def test_greenhouse_jobs_carry_their_company_and_place() -> None:
    by_id = {p.job_id: p for p in greenhouse.parse_feed(json.dumps(_gh()))}
    munich = by_id[GH_MUNICH]
    assert munich.place["city"] == "Munich" and munich.company == "Agile Robots SE"
    assert "&lt;" not in munich.text and "<" not in munich.text  # escaped HTML, cleaned
    assert munich.created_at is not None
    general = next(p for p in by_id.values() if p.title.startswith("General Application"))
    assert general.place is None


def test_greenhouse_snapshot_drops_open_applications() -> None:
    positions = greenhouse.parse_feed(json.dumps(_gh()))
    result, listed = greenhouse.to_result(slug="agilerobotsse", positions=positions, offices={},
                                          fetched_at=dt.datetime.now(dt.UTC))
    assert len(listed) == 3 and len(result.postings) == 3
    assert result.dropped == {"not a vacancy (open application)": 1}
    assert {p.city for p in result.postings} == {"Munich", "Fürstenfeldbruck", "Kaufbeuren"}


@pytest.mark.parametrize("body", [b"<html/>", b"[]", b'{"error": 1}', b""])
def test_a_broken_greenhouse_answer_is_unreadable(body) -> None:
    with pytest.raises(FeedUnreadable):
        greenhouse.parse_feed(body)


# --- Lever -----------------------------------------------------------------------


def test_lever_jobs_take_their_country_code_and_full_text() -> None:
    by_id = {p.job_id: p for p in lever.parse_feed(json.dumps(_lv()))}
    graz = by_id[LV_GRAZ]
    assert (graz.place["country"], graz.place["city"]) == ("OESTERREICH", "Graz")
    assert graz.employment_type == "full_time" and graz.created_at is not None
    assert "What you'll do" in graz.text  # the lists are part of the ad


def test_a_lever_job_elsewhere_counts_only_with_a_dach_town() -> None:
    job = copy.deepcopy(_lv()[0])
    job["country"], job["categories"]["location"] = "GB", "London"
    job["categories"]["allLocations"] = ["London", "Germany"]
    assert lever.dach_place(job) is None
    job["categories"]["allLocations"] = ["London", "Berlin"]
    assert lever.dach_place(job)["city"] == "Berlin"


@pytest.mark.parametrize("body", [b"<html/>", b'{"ok": false}', b""])
def test_a_broken_lever_answer_is_unreadable(body) -> None:
    with pytest.raises(FeedUnreadable):
        lever.parse_feed(body)


def test_lever_company_name_comes_from_the_board_page() -> None:
    page = (FIX / "lever" / "blackshark_board_page.html").read_text()
    assert lever.parse_company_name(page) == "Blackshark.ai"


def test_each_job_links_to_its_own_instance() -> None:
    assert source_detail_url("greenhouse", f"agilerobotsse:{GH_MUNICH}") == (
        f"https://job-boards.greenhouse.io/agilerobotsse/jobs/{GH_MUNICH}")
    assert lever.EU.external_id("blackshark", LV_GRAZ) == f"eu:blackshark:{LV_GRAZ}"
    assert source_detail_url("lever", f"eu:blackshark:{LV_GRAZ}") == (
        f"https://jobs.eu.lever.co/blackshark/{LV_GRAZ}")
    assert source_detail_url("lever", f"acme:{LV_GRAZ}") == f"https://jobs.lever.co/acme/{LV_GRAZ}"


# --- sync -------------------------------------------------------------------------


class _Feed:
    def __init__(self, name: str, data, company: str | None = None) -> None:
        self.name, self.body, self.company, self.name_reads = name, json.dumps(data).encode(), company, 0

    async def fetch_feed(self, slug: str) -> FeedAnswer:
        return FeedAnswer(200, self.body)


class _LeverFeed(_Feed):
    async def fetch_company_name(self, slug: str) -> str | None:
        self.name_reads += 1
        return self.company


async def _sync(source, ats_name: str, slug: str) -> dict:
    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard).where(HubAtsBoard.ats == ats_name, HubAtsBoard.slug == slug))
        return await ats.sync_board(s, adapter=source, board=board)


async def test_a_greenhouse_board_syncs_and_closes_what_it_drops() -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="greenhouse", slugs=["agilerobotsse"], discovered_via="t")
    first = await _sync(_Feed("greenhouse", _gh()), "greenhouse", "agilerobotsse")
    assert first["created"] == 3
    data = _gh()
    data["jobs"] = [j for j in data["jobs"] if str(j["id"]) != GH_MUNICH]
    assert (await _sync(_Feed("greenhouse", data), "greenhouse", "agilerobotsse"))["closed"] == 1
    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard).where(HubAtsBoard.ats == "greenhouse"))
    assert board.company_name == "Agile Robots SE" and board.status == "active"


async def test_a_lever_eu_board_stores_its_jobs_under_lever_with_the_eu_reference() -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="lever-eu", slugs=["blackshark"], discovered_via="t")
    source = _LeverFeed("lever-eu", _lv(), company="Blackshark.ai")
    outcome = await _sync(source, "lever-eu", "blackshark")
    assert outcome["created"] == 2 and source.name_reads == 1
    async with SessionLocal() as s:
        refs = set((await s.execute(select(HubJobPosting.external_id).where(
            HubJobPosting.source == "lever"))).scalars())
    assert f"eu:blackshark:{LV_GRAZ}" in refs


async def test_new_boards_are_read_in_the_order_they_were_found() -> None:
    """Discovery sends EU-hosted boards first; the first fill reads them first."""
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="greenhouse", slugs=["zz-eu-board"], discovered_via="wayback")
        await ats.add_boards(s, ats="greenhouse", slugs=["aa-main-board"], discovered_via="wayback")
        eu = await s.scalar(select(HubAtsBoard).where(HubAtsBoard.slug == "zz-eu-board"))
        eu.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
        await s.commit()
    async with SessionLocal() as s:
        leased = await ats._lease(s, 1, dt.datetime.now(dt.UTC), "greenhouse")
    assert [b.slug for b in leased] == ["zz-eu-board"]


# --- routes and the job -------------------------------------------------------------


async def test_the_routes_take_greenhouse_and_both_levers(monkeypatch) -> None:
    from app.core.auth import get_ingest_tenant
    from app.main import app

    seen: list[str] = []

    async def fake_sync_due(session, *, adapter, limit, **_):
        seen.append(adapter.name)
        return {"boards": 0}

    monkeypatch.setattr(ats, "sync_due", fake_sync_due)
    app.dependency_overrides[get_ingest_tenant] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            for name in ("greenhouse", "lever", "lever-eu"):
                added = await client.post(f"{settings.api_v1_prefix}/hub/ats/boards",
                                          json={"ats": name, "slugs": ["acme"], "discovered_via": "t"})
                assert added.status_code == 200, added.text
                synced = await client.post(f"{settings.api_v1_prefix}/hub/ats/sync", params={"ats": name})
                assert synced.status_code == 200
    finally:
        app.dependency_overrides.pop(get_ingest_tenant, None)
    assert seen == ["greenhouse", "lever", "lever-eu"]


def test_board_slugs_come_from_wayback_paths() -> None:
    gh = hub_ats.path_slugs("boards.greenhouse.io", [
        "https://boards.greenhouse.io/acme/jobs/123",
        "https://boards.greenhouse.io/embed/job_board?for=Widgets&b=x",
        "https://boards.greenhouse.io/embed/job_app?token=1",
        "https://boards.greenhouse.io/v1/boards/x",
        "https://evil.example.com/boards.greenhouse.io/x",
    ])
    assert gh == {"acme", "widgets"}
    assert hub_ats.path_slugs("jobs.eu.lever.co", [
        f"https://jobs.eu.lever.co/blackshark/{LV_GRAZ}", "http://jobs.eu.lever.co:80/Zoi?lever-source=x",
    ]) == {"blackshark", "zoi"}
