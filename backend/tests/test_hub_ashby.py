"""Ashby boards → the shared corpus (`adapters/ashby.py`, `hub/ats.py`).

Fixtures are real answers captured 2026-11-08, ad text cut to 500 chars:
`board.json` holds two Berlin jobs and a London job from n8n's board and a
country-only "Germany" job from molecule's; `n8n_board_page.html` is the
first 3 KB of n8n's board page.
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
from app.domain.hub.adapters import ashby
from app.domain.hub.adapters.base import SourceUnreachable
from app.domain.hub.adapters.boards import FeedAnswer, FeedUnreadable
from app.domain.hub.models import HubAtsBoard, HubJobPosting
from app.domain.hub.schemas import source_detail_url
from scripts import hub_ats

FIX = pathlib.Path(__file__).parent / "fixtures" / "ashby"
BERLIN_1 = "49e569f0-503e-4e42-a1ba-7e63684e90d3"


def _board_json() -> dict:
    return json.loads((FIX / "board.json").read_text())


# --- parsing --------------------------------------------------------------------


def test_a_job_counts_where_its_primary_location_is() -> None:
    by_title = {p.title: p for p in ashby.parse_feed(json.dumps(_board_json()))}
    berlin = by_title["Sr Security Engineer | Remote | Europe"]
    assert berlin.place["country"] == "DEUTSCHLAND" and berlin.place["city"] == "Berlin"
    assert by_title["Sales Development Representative - North EMEA"].place is None  # London
    germany_only = by_title["Pharmacist"]
    assert germany_only.place["country"] == "DEUTSCHLAND" and germany_only.place["city"] is None
    assert berlin.text and berlin.created_at is not None


def test_dach_in_a_remote_country_list_is_not_a_dach_job() -> None:
    london = next(j for j in _board_json()["jobs"] if j["location"] == "London Office")
    remote = copy.deepcopy(london)
    remote["secondaryLocations"] = [
        {"location": "Germany", "address": {"postalAddress": {"addressCountry": "Germany"}}},
    ]
    assert ashby.dach_place(remote) is None
    office = copy.deepcopy(london)
    office["secondaryLocations"] = [{"location": "Munich", "address": {"postalAddress": {
        "addressCountry": "Germany", "addressLocality": "München", "postalCode": "80331"}}}]
    assert ashby.dach_place(office)["postal_code"] == "80331"


def test_an_unlisted_job_is_not_on_the_board() -> None:
    data = _board_json()
    data["jobs"][0]["isListed"] = False
    assert data["jobs"][0]["id"] not in {p.job_id for p in ashby.parse_feed(json.dumps(data))}


@pytest.mark.parametrize("body", [b"<html>Wartung</html>", b'{"error": "x"}', b"[]", b""])
def test_a_broken_answer_is_unreadable_not_empty(body: bytes) -> None:
    with pytest.raises(FeedUnreadable):
        ashby.parse_feed(body)


def test_the_company_name_comes_from_the_board_page_title() -> None:
    assert ashby.parse_company_name((FIX / "n8n_board_page.html").read_text()) == "n8n"
    assert ashby.parse_company_name("<html><title>Something else</title></html>") is None


def test_the_snapshot_keeps_dach_jobs_and_names_the_place() -> None:
    positions = ashby.parse_feed(json.dumps(_board_json()))
    now = dt.datetime.now(dt.UTC)
    result, listed = ashby.to_result(slug="n8n", positions=positions, offices={}, fetched_at=now,
                                     company_name="n8n")
    assert len(listed) == 3 and len(result.postings) == 3
    assert result.dropped == {"not in DACH": 1}
    by_title = {p.title: p for p in result.postings}
    berlin = by_title["Sr Security Engineer | Remote | Europe"]
    assert (berlin.city, berlin.country, berlin.company.area) == ("Berlin", "DEUTSCHLAND", None)
    assert by_title["Pharmacist"].company.area == "country:deutschland"
    # Unnamed: listed (the diff base) but not stored.
    unnamed, listed_again = ashby.to_result(slug="n8n", positions=positions, offices={}, fetched_at=now)
    assert listed_again == listed and unnamed.dropped["employer not named"] == 3


def test_the_link_opens_the_job_on_the_employers_board() -> None:
    assert source_detail_url("ashby", f"n8n:{BERLIN_1}") == f"https://jobs.ashbyhq.com/n8n/{BERLIN_1}"


# --- sync -------------------------------------------------------------------------


class _AshbyBoard:
    name = "ashby"

    def __init__(self, data: dict | None = None, status: int = 200, company: str | None = "n8n") -> None:
        self.body = json.dumps(data).encode() if data is not None else b""
        self.status = status
        self.company = company
        self.name_reads = 0

    async def fetch_feed(self, slug: str) -> FeedAnswer:
        return FeedAnswer(self.status, self.body)

    async def fetch_company_name(self, slug: str) -> str | None:
        self.name_reads += 1
        if self.company == "down":
            raise SourceUnreachable("ConnectError")
        return self.company


async def _sync(source: _AshbyBoard, slug: str = "n8n") -> dict:
    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard).where(HubAtsBoard.ats == "ashby", HubAtsBoard.slug == slug))
        return await ats.sync_board(s, adapter=source, board=board)


async def test_a_board_syncs_and_closes_what_it_drops() -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="ashby", slugs=["n8n"], discovered_via="test")
    source = _AshbyBoard(_board_json())
    first = await _sync(source)
    assert first["created"] == 3 and source.name_reads == 1

    data = _board_json()
    data["jobs"] = [j for j in data["jobs"] if j["title"] != "Pharmacist"]
    second = await _sync(_AshbyBoard(data))
    assert second["closed"] == 1
    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard).where(HubAtsBoard.ats == "ashby"))
        open_titles = set((await s.execute(select(HubJobPosting.title).where(
            HubJobPosting.source == "ashby", HubJobPosting.is_active))).scalars())
    assert board.status == "active" and board.company_name == "n8n"
    assert "Pharmacist" not in open_titles and len(open_titles) == 2


async def test_a_board_with_no_dach_job_is_looked_at_monthly_and_never_named() -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="ashby", slugs=["london-only"], discovered_via="test")
    data = _board_json()
    data["jobs"] = [j for j in data["jobs"] if j["location"] == "London Office"]
    source = _AshbyBoard(data)
    await _sync(source, "london-only")
    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard).where(HubAtsBoard.slug == "london-only"))
    due = board.next_fetch_at if board.next_fetch_at.tzinfo else board.next_fetch_at.replace(tzinfo=dt.UTC)
    assert board.status == "elsewhere" and source.name_reads == 0
    assert due - dt.datetime.now(dt.UTC) > dt.timedelta(days=29)


async def _ashby_board(slug: str = "n8n") -> HubAtsBoard:
    async with SessionLocal() as s:
        return await s.scalar(select(HubAtsBoard).where(HubAtsBoard.ats == "ashby", HubAtsBoard.slug == slug))


@pytest.mark.parametrize("company", [None, "down"])
async def test_a_board_without_a_name_is_marked_and_asked_weekly(company) -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="ashby", slugs=["n8n"], discovered_via="test")
    first = await _sync(_AshbyBoard(_board_json(), company=company))
    board = await _ashby_board()
    due = board.next_fetch_at if board.next_fetch_at.tzinfo else board.next_fetch_at.replace(tzinfo=dt.UTC)
    assert first["created"] == 0 and first.get("unnamed") is True
    assert board.status == "unnamed" and due - dt.datetime.now(dt.UTC) > dt.timedelta(days=6)
    # Named on a later read: its jobs are stored then.
    later = await _sync(_AshbyBoard(_board_json()))
    assert later["created"] == 3 and (await _ashby_board()).status == "active"


async def test_a_talent_pool_alone_does_not_cost_a_name_lookup() -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="ashby", slugs=["pool-only"], discovered_via="test")
    data = _board_json()
    data["jobs"] = [dict(data["jobs"][0], title="Engineering Talent Pool")]
    source = _AshbyBoard(data)
    await _sync(source, "pool-only")
    assert source.name_reads == 0


async def test_an_empty_ashby_board_closes_only_on_the_second_answer() -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="ashby", slugs=["n8n"], discovered_via="test")
    await _sync(_AshbyBoard(_board_json()))
    once = await _sync(_AshbyBoard({"apiVersion": "1", "jobs": []}))
    assert once["closed"] == 0
    twice = await _sync(_AshbyBoard({"apiVersion": "1", "jobs": []}))
    assert twice["closed"] == 3


@pytest.mark.parametrize("answer", [_AshbyBoard(None, status=503), _AshbyBoard(None, status=429),
                                    _AshbyBoard(None, status=599)])
async def test_a_failed_ashby_answer_closes_nothing(answer) -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="ashby", slugs=["n8n"], discovered_via="test")
    await _sync(_AshbyBoard(_board_json()))
    outcome = await _sync(answer)
    assert outcome["closed"] == 0 and outcome["error"].startswith("HTTP")


async def test_ashby_and_personio_boards_are_leased_apart() -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="ashby", slugs=["n8n"], discovered_via="t")
        await ats.add_boards(s, ats="personio", slugs=["viu-ventures"], discovered_via="t")
    async with SessionLocal() as s:
        totals = await ats.sync_due(s, adapter=_AshbyBoard(_board_json()), limit=10, delay=0)
    assert totals["boards"] == 1
    async with SessionLocal() as s:
        personio_board = await s.scalar(select(HubAtsBoard).where(HubAtsBoard.ats == "personio"))
    assert personio_board.next_fetch_at is None  # untouched


async def test_discovery_accepts_ashby_slugs() -> None:
    async with SessionLocal() as s:
        result = await ats.add_boards(s, ats="ashby", slugs=["Sanity.io", "n8n", "../x", ""], discovered_via="t")
    assert result == {"added": 2, "known": 0, "invalid": 2}


# --- routes and the job -------------------------------------------------------------


async def test_the_routes_take_ashby(monkeypatch) -> None:
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
            added = await client.post(f"{settings.api_v1_prefix}/hub/ats/boards",
                                      json={"ats": "ashby", "slugs": ["n8n"], "discovered_via": "t"})
            synced = await client.post(f"{settings.api_v1_prefix}/hub/ats/sync", params={"ats": "ashby"})
            refused = await client.post(f"{settings.api_v1_prefix}/hub/ats/sync", params={"ats": "workday"})
    finally:
        app.dependency_overrides.pop(get_ingest_tenant, None)
    assert added.status_code == 200 and added.json()["added"] == 1
    assert synced.status_code == 200 and seen == ["ashby"]
    assert refused.status_code == 422


def test_ashby_board_slugs_come_from_wayback_paths() -> None:
    lines = [
        "https://jobs.ashbyhq.com/n8n/49e569f0-bc49-4b0a-9b4d-1b4f0e8e4b39",
        "http://jobs.ashbyhq.com:80/Sanity.io?utm=x",
        "https://jobs.ashbyhq.com/api/non-user-graphql",
        "https://jobs.ashbyhq.com/b/whatever",
        "https://evil.example.com/jobs.ashbyhq.com/x",
        "garbage",
    ]
    assert hub_ats.ashby_slugs(lines) == {"n8n", "sanity.io"}
