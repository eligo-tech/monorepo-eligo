"""Closing ads the source took down — `hub/liveness.py`.

Measured 2026-11-05 against production: all 648,451 postings were marked open,
none had ever been closed, and of 300 sampled at the Bundesagentur 125 answered
404 — about 40% of what Markt showed as open no longer existed.

The rules these tests pin:

* **Only the source's own "not found" closes an ad**: a 404 whose body carries
  `STELLENANGEBOT_NICHT_GEFUNDEN`. Measured the same day: 160 of 160 ads on the
  live listing answered 200, and a made-up reference answered 404 with that
  code. A bare 404 (a CDN, a renamed path) is no evidence.
* **A known-live control is asked first, every batch.** If it does not answer
  200, nothing in the batch is closed — a systematic 404 cannot empty the corpus.
* Missing from the weekly listing makes an ad a SUSPECT, nothing more: the
  listing reaches ~82% of the source.
* The queue is one due date (`check_due_at`): FIFO, and an ad answered live or
  not at all waits its turn instead of jamming the front.
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
from app.domain.hub import liveness
from app.domain.hub.adapters.bundesagentur import (
    BundesagenturAdapter,
    SourceUnreachable,
    liveness_from_response,
    parse_listing,
)
from app.domain.hub.models import HubCompany, HubJobPosting, HubObservation, HubPostingPayload

NOW = dt.datetime.now(dt.UTC)
NOT_FOUND = json.dumps({"messages": [{"code": "STELLENANGEBOT_NICHT_GEFUNDEN"}]})


class _Adapter:
    """Answers each ad the way the source would: live, gone, unknown, or down."""

    name = "bundesagentur"

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    async def check_live(self, external_id: str) -> str:
        self.calls.append(external_id)
        answer = self.answers.get(external_id, "live")
        if answer == "down":
            raise SourceUnreachable("ConnectError")
        return answer


async def _postings(rows: dict[str, dict], *, control: bool = True) -> uuid.UUID:
    """One company; one posting per key, each with ad text in the cold table.

    Every row is a due suspect unless overridden. `control` adds a listed,
    recently published ad — the batch's known-live reference.
    """
    async with SessionLocal() as s:
        company = HubCompany(
            name="Test GmbH", normalized_name="test", dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place", source="bundesagentur",
            first_seen_at=NOW, last_seen_at=NOW, open_postings_count=0,
        )
        s.add(company)
        await s.flush()
        if control:
            rows = {**rows, "control": {"unlisted_at": None, "check_due_at": None, "posted_at": NOW}}
        for ext, extra in rows.items():
            s.add(HubJobPosting(
                hub_company_id=company.id, title=f"Role {ext}", source="bundesagentur",
                external_id=ext, content_hash=ext, first_seen_at=NOW, last_seen_at=NOW,
                is_active=True, description_fetched_at=NOW, source_page_fetched_at=NOW,
                payload=HubPostingPayload(raw={"r": ext}, description=f"text {ext}"),
                **{
                    "posted_at": NOW - dt.timedelta(days=30),
                    "unlisted_at": NOW - dt.timedelta(days=1),
                    "check_due_at": NOW - dt.timedelta(days=1),
                    **extra,
                },
            ))
        company.open_postings_count = len(rows)
        await s.commit()
        return company.id


async def _row(ext: str) -> HubJobPosting:
    async with SessionLocal() as s:
        return (await s.execute(select(HubJobPosting).where(HubJobPosting.external_id == ext))).scalar_one()


async def _payload(ext: str) -> HubPostingPayload | None:
    row = await _row(ext)
    async with SessionLocal() as s:
        return await s.get(HubPostingPayload, row.id)


@pytest.fixture(autouse=True)
def _no_cached_control():
    liveness._control_cache.clear()
    yield
    liveness._control_cache.clear()


async def _check(adapter, **kw) -> dict:
    async with SessionLocal() as s:
        return await liveness.check_batch(s, adapter=adapter, delay=0, **kw)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    return value.replace(tzinfo=dt.UTC) if value is not None and value.tzinfo is None else value


# --- the decision: only the source's own "not found" closes -----------------


async def test_only_the_sources_not_found_closes_an_ad() -> None:
    await _postings({"gone": {}, "live": {}, "unclear": {}})
    result = await _check(_Adapter({"gone": "gone", "live": "live", "unclear": "unknown"}), limit=10)

    assert {k: result[k] for k in ("checked", "closed", "live", "unknown")} == {
        "checked": 3, "closed": 1, "live": 1, "unknown": 1,
    }
    gone, live, unclear = await _row("gone"), await _row("live"), await _row("unclear")
    assert (gone.is_active, gone.closed_at is not None, gone.check_due_at) == (False, True, None)
    assert (live.is_active, live.live_checked_at is not None) == (True, True)
    assert (unclear.is_active, unclear.live_checked_at, unclear.closed_at) == (True, None, None)


@pytest.mark.parametrize(
    "status, body, verdict",
    [
        (200, "{}", "live"),
        (404, NOT_FOUND, "gone"),
        (404, "<html>Not Found</html>", "unknown"),           # a CDN, a renamed path
        (404, json.dumps({"messages": [{"code": "OTHER"}]}), "unknown"),
        (410, "", "unknown"),
        (500, "", "unknown"), (503, "", "unknown"), (429, "", "unknown"), (403, "", "unknown"),
    ],
)
def test_gone_needs_a_404_carrying_the_sources_not_found_code(status, body, verdict) -> None:
    assert liveness_from_response(status, body) == verdict


async def test_a_failed_control_closes_nothing() -> None:
    """A systematic 404 — path retired, key changed — answers for the control too."""
    await _postings({"a": {}, "b": {}})
    result = await _check(_Adapter({"control": "gone", "a": "gone", "b": "gone"}), limit=10)

    assert result["control_failed"] is True and result["checked"] == 0
    assert (await _row("a")).is_active and (await _row("b")).is_active
    assert (await _payload("a")) is not None


async def test_without_a_control_reference_nothing_is_checked() -> None:
    await _postings({"a": {}}, control=False)
    adapter = _Adapter({"a": "gone"})
    result = await _check(adapter, limit=10)
    assert result["control_failed"] is True and adapter.calls == []


async def test_a_closed_ads_text_is_deleted_but_the_role_is_kept() -> None:
    await _postings({"gone": {}, "live": {}})
    await _check(_Adapter({"gone": "gone", "live": "live"}), limit=10)

    assert await _payload("gone") is None
    assert (await _payload("live")).description == "text live"
    row = await _row("gone")
    assert row.title == "Role gone" and row.is_active is False


async def test_a_closure_is_recorded_as_evidence() -> None:
    await _postings({"g1": {}, "g2": {}, "live": {}})
    await _check(_Adapter({"g1": "gone", "g2": "gone", "live": "live"}), limit=10)

    gone = await _row("g1")
    async with SessionLocal() as s:
        obs = await s.get(HubObservation, gone.observation_id)
    assert obs.http_status == 404 and obs.record_count == 2
    assert sorted(obs.payload["closed"]) == ["g1", "g2"] and obs.payload["control"] == "control"


async def test_closing_recounts_the_companys_open_roles() -> None:
    company_id = await _postings({"a": {}, "b": {}, "c": {}})
    await _check(_Adapter({"a": "gone", "b": "gone", "c": "live"}), limit=10)
    async with SessionLocal() as s:
        # c and the control remain open.
        assert (await s.get(HubCompany, company_id)).open_postings_count == 2


# --- outages and non-answers -------------------------------------------------


async def test_one_timeout_is_an_unknown_not_an_outage() -> None:
    await _postings({"a": {}, "b": {}, "c": {}})
    result = await _check(_Adapter({"a": "down", "b": "gone", "c": "live"}), limit=10)
    assert result["source_unreachable"] is False
    assert (result["unknown"], result["closed"], result["live"]) == (1, 1, 1)


async def test_three_failures_in_a_row_stop_the_batch_and_close_nothing_more() -> None:
    await _postings({f"x{i}": {"check_due_at": NOW - dt.timedelta(days=10 - i)} for i in range(5)})
    adapter = _Adapter({"x0": "gone", "x1": "down", "x2": "down", "x3": "down", "x4": "gone"})
    result = await _check(adapter, limit=10)

    assert result["source_unreachable"] is True
    assert "x4" not in adapter.calls
    assert (await _row("x0")).is_active is False  # answered before the outage
    assert (await _row("x4")).is_active is True


async def test_an_unanswered_ad_waits_a_day_instead_of_jamming_the_queue() -> None:
    await _postings({"stuck": {}, "next": {"check_due_at": NOW - dt.timedelta(hours=1)}})
    await _check(_Adapter({"stuck": "unknown", "next": "live"}), limit=1)
    stuck = await _row("stuck")
    assert stuck.is_active and _aware(stuck.check_due_at) > NOW + dt.timedelta(hours=20)

    adapter = _Adapter({"next": "live"})
    await _check(adapter, limit=1)
    assert adapter.calls == ["control", "next"]


async def test_a_batch_stops_at_its_time_budget(monkeypatch) -> None:
    await _postings({f"t{i}": {} for i in range(5)})
    # control cache lookup, cache stamp, start, then one tick per ad
    ticks = iter([0, 0, 0, 0, 10, 20, 70, 80, 90, 100])
    monkeypatch.setattr(liveness, "_clock", lambda: next(ticks))
    result = await _check(_Adapter({}), limit=10, time_budget=60)
    assert result["checked"] < 5


# --- who gets checked ---------------------------------------------------------


async def test_only_due_suspects_are_checked_oldest_due_first() -> None:
    await _postings({
        "listed": {"unlisted_at": None, "check_due_at": None},
        "later": {"check_due_at": NOW + dt.timedelta(days=3)},
        "old": {"check_due_at": NOW - dt.timedelta(days=6)},
        "mid": {"check_due_at": NOW - dt.timedelta(days=3)},
    })
    adapter = _Adapter({})
    await _check(adapter, limit=10)
    assert adapter.calls == ["control", "old", "mid"]


async def test_a_confirmed_live_ad_waits_longer_each_time() -> None:
    await _postings({"first": {}, "again": {"live_checked_at": NOW - dt.timedelta(days=15)}})
    await _check(_Adapter({}), limit=10)
    first, again = await _row("first"), await _row("again")
    assert dt.timedelta(days=13) < _aware(first.check_due_at) - NOW < dt.timedelta(days=15)
    assert dt.timedelta(days=29) < _aware(again.check_due_at) - NOW < dt.timedelta(days=31)


async def test_closed_ads_are_not_checked_again() -> None:
    await _postings({"a": {}})
    await _check(_Adapter({"a": "gone"}), limit=10)
    adapter = _Adapter({})
    assert (await _check(adapter, limit=10))["checked"] == 0


# --- marking suspects from the listing ----------------------------------------


async def test_mark_queues_the_missing_and_clears_the_relisted() -> None:
    await _postings({
        "was_missing": {},
        "missing_now": {"unlisted_at": None, "check_due_at": None},
        "steady": {"unlisted_at": None, "check_due_at": None},
    })
    async with SessionLocal() as s:
        result = await liveness.mark(s, segment="employer", unlisted=["missing_now"], listed=["was_missing"])
    assert result == {"unlisted": 1, "listed": 1}
    missing = await _row("missing_now")
    assert missing.unlisted_at is not None and missing.check_due_at is not None
    relisted = await _row("was_missing")
    assert (relisted.unlisted_at, relisted.check_due_at) == (None, None)
    assert (await _row("steady")).unlisted_at is None


async def test_marking_again_keeps_the_first_time_and_the_queue_position() -> None:
    first = NOW - dt.timedelta(days=7)
    due = NOW + dt.timedelta(days=9)
    await _postings({"a": {"unlisted_at": first, "check_due_at": due}})
    async with SessionLocal() as s:
        await liveness.mark(s, segment="employer", unlisted=["a"], listed=[])
    row = await _row("a")
    assert (_aware(row.unlisted_at), _aware(row.check_due_at)) == (first, due)


async def test_active_ids_page_by_key_with_the_suspect_flag() -> None:
    await _postings({"c": {"unlisted_at": None}, "a": {}, "b": {"unlisted_at": None}}, control=False)
    async with SessionLocal() as s:
        first = await liveness.active_ids(s, segment="employer", after=None, limit=2)
        rest = await liveness.active_ids(s, segment="employer", after=first[-1][0], limit=2)
    assert first == [("a", True), ("b", False)]
    assert rest == [("c", False)]


# --- a reference published again ----------------------------------------------


async def test_a_closed_ad_published_again_reopens_with_its_data() -> None:
    """The ingest touch path reopens it and restores what closure deleted:
    the raw copy, and fresh attempts at the ad text and the partner page."""
    from app.domain.hub import service
    from app.domain.hub.schemas import IngestRequest
    from tests.test_hub_ingest import StubAdapter, _fetch_result

    ext = _fetch_result().postings[0].external_id
    async with SessionLocal() as s:
        await service.ingest(s, adapter=StubAdapter(_fetch_result()), request=IngestRequest(where="Berlin"))
        await s.commit()
    await _postings({}, control=True)
    async with SessionLocal() as s:
        row = (await s.execute(select(HubJobPosting).where(HubJobPosting.external_id == ext))).scalar_one()
        row.unlisted_at = row.check_due_at = NOW - dt.timedelta(days=1)
        row.description_fetched_at = row.source_page_fetched_at = NOW
        await s.commit()
    await _check(_Adapter({ext: "gone"}), limit=5)
    assert (await _row(ext)).is_active is False and await _payload(ext) is None

    async with SessionLocal() as s:
        await service.ingest(s, adapter=StubAdapter(_fetch_result()), request=IngestRequest(where="Berlin"))
    row = await _row(ext)
    assert row.is_active is True
    assert (row.closed_at, row.unlisted_at, row.check_due_at) == (None, None, None)
    assert (row.description_fetched_at, row.source_page_fetched_at) == (None, None)
    payload = await _payload(ext)
    assert payload is not None and payload.raw.get("referenznummer") == ext


# --- the source, through a fake transport ------------------------------------


def _ba(handler) -> BundesagenturAdapter:
    return BundesagenturAdapter(base_url="https://ba.test", transport=httpx.MockTransport(handler))


async def test_check_live_asks_the_detail_page_by_base64_reference() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(404, text=NOT_FOUND)

    assert await _ba(handler).check_live("10001-1003967705-S") == "gone"
    assert seen == ["/pc/v4/jobdetails/MTAwMDEtMTAwMzk2NzcwNS1T"]


async def test_a_transport_error_is_unreachable_not_gone() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(SourceUnreachable):
        await _ba(handler).check_live("x")


async def test_the_listing_asks_for_everything_not_a_window() -> None:
    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json={"ergebnisliste": [{"referenznummer": "r1"}], "maxErgebnisse": 1, "facetten": {}})

    page = await _ba(handler).fetch_listing(segment="private_recruiter", filters={"befristung": "2"}, page=3)
    assert page.external_ids == ["r1"] and page.records == 1
    params = seen[0]
    assert "veroeffentlichtseit" not in params
    assert (params["pav"], params["zeitarbeit"], params["befristung"], params["page"]) == ("true", "false", "2", "3")


def test_the_listing_yields_every_reference_and_the_split_facets() -> None:
    fixture = pathlib.Path(__file__).parent / "fixtures" / "bundesagentur_jobs.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["facetten"] = {
        "befristung": {"counts": {"1": 3, "2": 30, "3": 7}},
        "berufsfeld": {"counts": {"Informatik": 40}},
        "arbeitsort_plz": {"counts": {"10115": 9}},  # not a split dimension
    }
    payload["ergebnisliste"].append({"titel": "no reference"})
    page = parse_listing(payload)
    refs = [r["referenznummer"] for r in payload["ergebnisliste"] if "referenznummer" in r]
    assert page.external_ids == refs
    # The page's RECORD count drives paging, not the references kept.
    assert page.records == len(refs) + 1
    assert page.total_available == payload["maxErgebnisse"]
    assert set(page.facets) == {"befristung", "berufsfeld"}


# --- endpoints: bounded -------------------------------------------------------


async def _client():
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_a_listing_filter_outside_the_split_dimensions_is_refused() -> None:
    async with await _client() as client:
        r = await client.post(
            f"{settings.api_v1_prefix}/hub/liveness/listing",
            json={"segment": "employer", "filters": {"wo": "Berlin"}, "page": 1},
        )
    assert r.status_code == 422


async def test_marking_more_than_a_bounded_batch_is_refused() -> None:
    async with await _client() as client:
        r = await client.post(
            f"{settings.api_v1_prefix}/hub/liveness/mark",
            json={"segment": "employer", "unlisted": [str(i) for i in range(10_001)], "listed": []},
        )
    assert r.status_code == 422
