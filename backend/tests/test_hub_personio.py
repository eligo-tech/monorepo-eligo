"""Employers' own Personio boards (`adapters/personio.py`, `hub/ats.py`).

Fixtures are real captures from 2026-11-06, ad text cut to 800 characters:
two positions of BUND (Berlin), two of VIU (Salzburg, Berlin), and the
schema.org JobPosting block of one job page each.

What these tests pin:

* The feed is a full snapshot: a DACH job it stops listing is CLOSED, with
  evidence — but one empty or unreadable answer closes nothing.
* The office's postcode comes from ONE job page per office, cached, so the
  same job on BA is the same company and the same vacancy.
* Offices outside DACH, offices without an address and open applications are
  dropped and counted.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import ats, service
from app.domain.hub.adapters import personio
from app.domain.hub.adapters.base import FetchResult, SourcedCompany, SourcedPosting, SourceUnreachable
from app.domain.hub.models import HubAtsBoard, HubJobPosting, HubObservation, HubPostingPayload
from app.domain.hub.schemas import source_detail_url
from app.domain.hub.vacancy import vacancy_count
from scripts import hub_ats

FIX = pathlib.Path(__file__).parent / "fixtures" / "personio"
NOW = dt.datetime.now(dt.UTC)


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# Both fixtures are schema.org-only pages: one address, no office name ("").
BERLIN = personio.parse_job_page(_read("bund_job.html"))["offices"][""]
SALZBURG = personio.parse_job_page(_read("viu_salzburg_job.html"))["offices"][""]


# --- parsing ------------------------------------------------------------------


def test_the_feed_yields_every_position_with_its_full_text() -> None:
    positions = personio.parse_feed(_read("bund_feed.xml").encode())

    assert len(positions) == 2
    first = positions[0]
    assert first.job_id == "2834557" and first.office == "Berlin"
    assert first.company == "Bund für Umwelt und Naturschutz Deutschland e.V. (BUND)"
    assert first.text and "<" not in first.text and "Rahmen" in first.text
    assert first.created_at is not None and first.created_at.tzinfo is not None


@pytest.mark.parametrize("body", [b"<html><body>Wartung</body></html>", b"<workzag-jobs><position>", b""])
def test_a_200_that_is_not_the_feed_is_unreadable_not_empty(body: bytes) -> None:
    with pytest.raises(personio.FeedUnreadable):
        personio.parse_feed(body)


def test_an_empty_feed_is_no_jobs() -> None:
    assert personio.parse_feed(b'<?xml version="1.0"?><workzag-jobs></workzag-jobs>') == []


def test_a_job_page_gives_the_offices_postal_address() -> None:
    assert BERLIN["postal_code"] == "10553" and BERLIN["country"] == "DE"
    assert BERLIN["region"] == "Berlin" and BERLIN["street"] == "Kaiserin-Augusta-Allee 5"
    assert SALZBURG["city"] == "Salzburg"  # the page says " Salzburg"
    assert SALZBURG["country"] == "AT" and SALZBURG["postal_code"] == "5020"
    assert personio.parse_job_page("<html>no structured data</html>") == {"offices": {}, "employer": None}


def test_a_page_without_schema_org_still_names_its_offices() -> None:
    """Newer page templates carry no JSON-LD; the page's app data still lists
    every office with its address (Mynaric — the whole page, captured 2026-11-06)."""
    page = personio.parse_job_page(_read("mynaric_job.html"))

    assert page["offices"]["München"]["postal_code"] == "81249"
    assert page["offices"]["München"]["country"] == "DE"
    assert page["employer"] == "Mynaric"


@pytest.mark.parametrize(
    ("region", "code"),
    [("Baden-Württemberg", "BADEN_WUERTTEMBERG"), ("Berlin", "BERLIN"), ("Thüringen", "THUERINGEN"), (None, None)],
)
def test_regions_are_spelled_as_the_bundesagentur_spells_them(region, code) -> None:
    assert personio.region_code(region) == code


def _positions() -> list[personio.Position]:
    return personio.parse_feed(_read("viu_feed.xml").encode())


def test_a_snapshot_keeps_dach_offices_and_counts_the_rest() -> None:
    positions = _positions() + [
        personio.Position("9", "Initiativbewerbung (m/w/d)", "Berlin", "VIU Deutschland GmbH", None, None, None),
        personio.Position("10", "Optician", "London", "VIU UK", None, None, None),
        personio.Position("11", "Optiker", "Graz", "VIU AT GmbH", None, None, None),  # not resolved yet
    ]
    offices = {"Berlin": BERLIN, "Salzburg": SALZBURG, "London": {"country": "GB", "city": "London"}}
    result, listed = personio.to_result(slug="viu-ventures", positions=positions, offices=offices, fetched_at=NOW)

    by_office = {p.raw["office"]: p for p in result.postings}
    assert set(by_office) == {"Berlin", "Salzburg"}
    assert result.dropped == {"not a vacancy (open application)": 1, "office outside DACH or without an address": 2}
    assert listed == [p.external_id for p in result.postings]
    berlin, salzburg = by_office["Berlin"], by_office["Salzburg"]
    assert (berlin.country, berlin.postal_code, berlin.region) == ("DEUTSCHLAND", "10553", "BERLIN")
    assert (salzburg.country, salzburg.postal_code) == ("OESTERREICH", "5020")
    assert berlin.company.name == "VIU Deutschland GmbH" and berlin.company.postal_code == "10553"
    assert berlin.external_id == "viu-ventures:2703024"
    assert berlin.source_url is None  # the partner-page fetcher must not crawl it
    assert berlin.segment == "employer"


def test_the_link_opens_the_employers_own_ad() -> None:
    assert source_detail_url("personio", "viu-ventures:2703024") == (
        "https://viu-ventures.jobs.personio.de/job/2703024?language=de"
    )


# --- into the corpus: one vacancy across sources ------------------------------


async def test_the_same_job_on_ba_and_on_the_board_is_one_vacancy() -> None:
    """Same employer, same title, same postcode: BA's ad and the board's are one."""
    def posting(source_id: str) -> SourcedPosting:
        return SourcedPosting(
            external_id=source_id, title="Augenoptiker:in (m/w/d)",
            company=SourcedCompany(name="VIU Deutschland GmbH", postal_code="10553", city="Berlin",
                                   country="DEUTSCHLAND"),
            postal_code="10553", city="Berlin", country="DEUTSCHLAND",
        )

    async with SessionLocal() as s:
        for source, ext in (("bundesagentur", "10000-1-S"), ("personio", "viu-ventures:1")):
            await service.merge_fetch(s, result=FetchResult(
                source=source, request_url="x", fetched_at=NOW, http_status=200, postings=[posting(ext)],
            ), key=f"t-{source}")
        rows = (await s.execute(select(HubJobPosting.hub_company_id))).scalars().all()
        assert len(rows) == 2 and len(set(rows)) == 1  # one company: the same identity rung
        assert await s.scalar(select(vacancy_count())) == 1


# --- sync: a fake board -------------------------------------------------------


class _Board:
    """A board that answers what the test sets."""

    name = "personio"

    def __init__(self, feed: bytes, status: int = 200) -> None:
        self.feed, self.status = feed, status
        self.pages: list[str] = []
        self.down = False

    async def fetch_feed(self, slug: str) -> personio.FeedAnswer:
        if self.down:
            raise SourceUnreachable("ConnectError")
        return personio.FeedAnswer(self.status, self.feed)

    async def fetch_job_page(self, slug: str, job_id: str) -> str | None:
        self.pages.append(job_id)
        office = next(p.office for p in personio.parse_feed(self.feed) if p.job_id == job_id)
        return _read("viu_salzburg_job.html" if office == "Salzburg" else "bund_job.html")


def _feed_without(job_id: str) -> bytes:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(_read("viu_feed.xml").encode())
    for pos in root.findall("position"):
        if pos.findtext("id") == job_id:
            root.remove(pos)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


EMPTY = b'<?xml version="1.0"?><workzag-jobs></workzag-jobs>'


async def _board() -> HubAtsBoard:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="personio", slugs=["viu-ventures"], discovered_via="test")
        return await s.scalar(select(HubAtsBoard))


async def _sync(source: _Board) -> dict:
    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard).where(HubAtsBoard.slug == "viu-ventures"))
        return await ats.sync_board(s, adapter=source, board=board)


async def _open() -> set[str]:
    async with SessionLocal() as s:
        return set((await s.execute(
            select(HubJobPosting.external_id).where(HubJobPosting.source == "personio", HubJobPosting.is_active)
        )).scalars())


async def test_a_first_sync_stores_the_dach_jobs_and_reads_each_office_once() -> None:
    await _board()
    source = _Board(_read("viu_feed.xml").encode())
    first = await _sync(source)
    again = await _sync(source)

    assert first["created"] == 2 and again["created"] == 0 and again["updated"] == 2
    assert len(source.pages) == 2  # Salzburg and Berlin, once each, never again
    assert await _open() == {"viu-ventures:2807896", "viu-ventures:2703024"}
    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard))
        text = await s.scalar(select(func.count(HubPostingPayload.hub_job_posting_id)).where(
            HubPostingPayload.description.is_not(None)))
    assert (board.status, board.jobs_dach, board.company_name) == ("active", 2, "VIU Eyewear")
    assert set(board.offices) == {"Salzburg", "Berlin"}
    assert text == 2


async def test_a_job_the_feed_stops_listing_is_closed_with_evidence() -> None:
    await _board()
    await _sync(_Board(_read("viu_feed.xml").encode()))
    outcome = await _sync(_Board(_feed_without("2807896")))

    assert outcome["closed"] == 1
    assert await _open() == {"viu-ventures:2703024"}
    async with SessionLocal() as s:
        row = await s.scalar(select(HubJobPosting).where(HubJobPosting.external_id == "viu-ventures:2807896"))
        payload = await s.scalar(select(HubPostingPayload).where(HubPostingPayload.hub_job_posting_id == row.id))
        evidence = await s.scalar(select(HubObservation).where(HubObservation.note.like("ats:%")))
    assert row.closed_at is not None and payload is None
    assert evidence.payload["closed"] == ["viu-ventures:2807896"]


async def test_one_empty_feed_closes_nothing_two_in_a_row_close_the_board() -> None:
    await _board()
    await _sync(_Board(_read("viu_feed.xml").encode()))

    once = await _sync(_Board(EMPTY))
    assert once["closed"] == 0 and len(await _open()) == 2
    twice = await _sync(_Board(EMPTY))
    assert twice["closed"] == 2 and await _open() == set()


@pytest.mark.parametrize(
    "answer",
    [_Board(b"<html>Wartungsarbeiten</html>"), _Board(b"", status=503), _Board(b"", status=429)],
)
async def test_a_broken_answer_closes_nothing_and_retries(answer: _Board) -> None:
    await _board()
    await _sync(_Board(_read("viu_feed.xml").encode()))
    outcome = await _sync(answer)

    assert outcome.get("error") and outcome["closed"] == 0
    assert len(await _open()) == 2
    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard))
    assert board.failures == 1 and board.status == "active"


async def test_a_switched_off_feed_retires_the_board_after_two_answers() -> None:
    await _board()
    await _sync(_Board(_read("viu_feed.xml").encode()))
    once = await _sync(_Board(b"", status=404))
    assert once["closed"] == 0 and len(await _open()) == 2  # an incident's 404 burst closes nothing
    outcome = await _sync(_Board(b"", status=404))

    assert outcome["closed"] == 2 and await _open() == set()
    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard))
    due = board.next_fetch_at if board.next_fetch_at.tzinfo else board.next_fetch_at.replace(tzinfo=dt.UTC)
    assert board.status == "gone" and due > NOW + dt.timedelta(days=20)


async def test_a_board_published_again_reopens_its_jobs() -> None:
    await _board()
    await _sync(_Board(_read("viu_feed.xml").encode()))
    for _ in range(2):
        await _sync(_Board(b"", status=404))
    await _sync(_Board(_read("viu_feed.xml").encode()))

    assert len(await _open()) == 2


async def test_discovery_adds_each_board_once_and_refuses_junk() -> None:
    async with SessionLocal() as s:
        first = await ats.add_boards(s, ats="personio", slugs=["viu-ventures", "Bund", "../etc", ""], discovered_via="t")
        second = await ats.add_boards(s, ats="personio", slugs=["bund", "timify"], discovered_via="t")
    assert first == {"added": 2, "known": 0, "invalid": 2}
    assert second == {"added": 1, "known": 1, "invalid": 0}


async def test_a_batch_leases_its_boards_and_hands_back_what_it_did_not_reach(monkeypatch) -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="personio", slugs=["a1", "a2", "a3"], discovered_via="t")
    ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(ats, "_clock", lambda: next(ticks))
    async with SessionLocal() as s:
        totals = await ats.sync_due(s, adapter=_Board(EMPTY), limit=3, delay=0, time_budget=60)

    assert totals["boards"] == 1 and totals["more_due"] is True
    async with SessionLocal() as s:
        due = (await s.execute(select(HubAtsBoard.slug).where(
            HubAtsBoard.next_fetch_at <= dt.datetime.now(dt.UTC)))).scalars().all()
    assert len(due) == 2  # the two it never reached, due again now


async def test_the_source_down_stops_the_batch() -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="personio", slugs=[f"b{i}" for i in range(5)], discovered_via="t")
    down = _Board(EMPTY)
    down.down = True
    async with SessionLocal() as s:
        totals = await ats.sync_due(s, adapter=down, limit=5, delay=0)
    assert totals["boards"] == 3 and totals["source_unreachable"] is True


# --- endpoints and the job ----------------------------------------------------


async def test_discovery_is_bounded() -> None:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post(f"{settings.api_v1_prefix}/hub/ats/boards",
                              json={"slugs": [f"s{i}" for i in range(5_001)]})
    assert r.status_code == 422


def test_board_slugs_come_from_the_index_answer() -> None:
    lines = [json.dumps({"url": u}) for u in (
        "https://viu-ventures.jobs.personio.de/job/1?language=de",
        "https://Timify.jobs.personio.com/",
        "https://www.jobs.personio.de/",
        "https://jobs.personio.de/xml",
        "https://evil.example.com/?x=.jobs.personio.de",
    )] + ["not json"]
    assert hub_ats.slugs_from_index(lines) == {"viu-ventures", "timify"}


def _discovery_world(*, wayback: httpx.Response | None):
    """Common Crawl knows one board; the Wayback Machine knows it plus two more."""
    sent: list[dict] = []

    def source(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("collinfo.json"):
            return httpx.Response(200, json=[{"id": "CC-1"}])
        if "showNumPages" in url:
            return httpx.Response(200, json={"pages": 1})
        if "index.commoncrawl.org" in url:
            return httpx.Response(200, text=json.dumps({"url": "https://viu-ventures.jobs.personio.de/"}))
        if "web.archive.org" in url:
            assert "jobs.personio.de" in url
            return wayback or httpx.Response(200, text=(
                "https://viu-ventures.jobs.personio.de/job/1\n"
                "http://Timify.jobs.personio.de:80/\n"
                "https://acme-gmbh.jobs.personio.de/xml?language=de\n"
                "https://www.jobs.personio.de/\n"
            ))
        raise AssertionError(url)

    def backend(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, json={"added": len(body["slugs"])})

    from scripts.hub_liveness import Api

    api = Api(httpx.AsyncClient(transport=httpx.MockTransport(backend), base_url="http://t"))
    return api, httpx.AsyncClient(transport=httpx.MockTransport(source)), sent


async def test_discovery_also_reads_the_wayback_machine(monkeypatch) -> None:
    async def no_wait(_s: float) -> None:
        return None

    monkeypatch.setattr(hub_ats.asyncio, "sleep", no_wait)
    api, cc, sent = _discovery_world(wayback=None)
    assert await hub_ats.discover(api, cc) == 3
    # Each board is labelled with the source that found it first.
    assert [(b["discovered_via"], b["slugs"]) for b in sent] == [
        ("commoncrawl", ["viu-ventures"]),
        ("wayback", ["acme-gmbh", "timify"]),
    ]


async def test_a_wayback_outage_keeps_what_common_crawl_found(monkeypatch) -> None:
    async def no_wait(_s: float) -> None:
        return None

    monkeypatch.setattr(hub_ats.asyncio, "sleep", no_wait)
    api, cc, sent = _discovery_world(wayback=httpx.Response(503))
    assert await hub_ats.discover(api, cc) == 1
    assert [(b["discovered_via"], b["slugs"]) for b in sent] == [("commoncrawl", ["viu-ventures"])]


async def test_the_job_syncs_until_nothing_is_due() -> None:
    answers = iter([{"boards": 20, "created": 5, "more_due": True}, {"boards": 7, "closed": 1, "more_due": False}])
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=next(answers))

    from scripts.hub_liveness import Api

    api = Api(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t"))
    assert await hub_ats.sync(api, minutes=5) == 0
    assert len(calls) == 2


async def test_the_job_fails_when_most_boards_fail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"boards": 20, "failed": 15, "more_due": False})

    from scripts.hub_liveness import Api

    api = Api(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t"))
    assert await hub_ats.sync(api, minutes=5) == 1


# --- review findings: never close a live job for our own reasons -------------


class _Flaky(_Board):
    """Answers the first job page, then the network drops."""

    async def fetch_job_page(self, slug: str, job_id: str) -> str | None:
        if self.pages:
            raise SourceUnreachable("ConnectError")
        return await super().fetch_job_page(slug, job_id)


async def test_offices_read_before_an_outage_are_kept() -> None:
    await _board()
    source = _Flaky(_read("viu_feed.xml").encode())
    await _sync(source)

    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard))
    assert list(board.offices) == ["Salzburg"]  # the one answer that came back
    assert await _open() == {"viu-ventures:2807896"}


async def test_a_listed_job_whose_office_is_unresolved_is_not_closed() -> None:
    await _board()
    await _sync(_Board(_read("viu_feed.xml").encode()))
    async with SessionLocal() as s:  # the employer renames its office; the page will not answer
        board = await s.scalar(select(HubAtsBoard))
        board.offices = {"Salzburg": board.offices["Salzburg"]}
        await s.commit()

    class _Silent(_Board):
        async def fetch_job_page(self, slug, job_id):
            return None

    outcome = await _sync(_Silent(_read("viu_feed.xml").encode()))
    assert outcome["closed"] == 0
    assert await _open() == {"viu-ventures:2807896", "viu-ventures:2703024"}


async def test_a_page_with_one_address_resolves_the_office_whatever_it_is_called() -> None:
    await _board()
    feed = _read("viu_feed.xml").replace("<office>Berlin</office>", "<office>Berlin HQ</office>").encode()
    await _sync(_Board(feed))

    async with SessionLocal() as s:
        board = await s.scalar(select(HubAtsBoard))
    assert board.offices["Berlin HQ"]["postal_code"] == "10553"


def test_a_repeated_or_malformed_id_is_one_row_or_none() -> None:
    feed = (
        '<?xml version="1.0"?><workzag-jobs>'
        "<position><id>7</id><name>Koch</name></position>"
        "<position><id>7</id><name>Koch</name></position>"
        f"<position><id>{'9' * 30}</id><name>Kellner</name></position>"
        "<position><id>x/../1</id><name>Kellner</name></position>"
        "</workzag-jobs>"
    )
    assert [p.job_id for p in personio.parse_feed(feed.encode())] == ["7"]


async def test_one_board_failing_costs_that_board_not_the_batch(monkeypatch) -> None:
    async with SessionLocal() as s:
        await ats.add_boards(s, ats="personio", slugs=["good-1", "bad", "good-2"], discovered_via="t")
    real = ats.sync_board

    async def flaky(session, *, adapter, board, deadline=None):
        if board.slug == "bad":
            raise RuntimeError("integrity error")
        return await real(session, adapter=adapter, board=board, deadline=deadline)

    monkeypatch.setattr(ats, "sync_board", flaky)
    async with SessionLocal() as s:
        totals = await ats.sync_due(s, adapter=_Board(EMPTY), limit=3, delay=0)
        bad = await s.scalar(select(HubAtsBoard).where(HubAtsBoard.slug == "bad"))
    assert totals["boards"] == 3 and totals["failed"] == 1
    assert bad.failures == 1


def test_the_office_list_survives_brackets_inside_values() -> None:
    # Escaped exactly as in a real page's flight data: \" around every string.
    page = ('x\\"office_addresses\\":[{\\"name\\":\\"Haus [B]\\",\\"zip_code\\":\\"10115\\",'
            '\\"country\\":\\"DE\\",\\"tags\\":[1,[2]]}],\\"offices\\":[]')
    assert '\\"office_addresses\\"' in page and "\\\\" not in page
    assert personio.parse_job_page(page)["offices"]["Haus [B]"]["postal_code"] == "10115"
