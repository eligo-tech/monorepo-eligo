"""Closing ads the source took down — `hub/liveness.py`.

Measured 2026-11-05 against production: all 648,451 postings were marked open,
none had ever been closed, and of 300 sampled at the Bundesagentur 125 answered
404 — about 40% of what Markt showed as open no longer existed.

The rule these tests pin: **only a 404 on that ad's own detail page closes it.**
Missing from the weekly listing makes an ad a SUSPECT, nothing more — the
listing reaches ~82% of the source (shards over the 10,000 cap cannot be read
whole), so absence alone would close live roles. A timeout, a 5xx or an outage
closes nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import liveness
from app.domain.hub.adapters.bundesagentur import (
    SourceUnreachable,
    liveness_from_status,
    parse_listing,
)
from app.domain.hub.models import HubCompany, HubJobPosting, HubPostingPayload

NOW = dt.datetime.now(dt.UTC)


class _Adapter:
    """Answers each ad the way the source would: live, gone, or unclear."""

    name = "bundesagentur"

    def __init__(self, answers: dict[str, str], down_after: int | None = None) -> None:
        self.answers = answers
        self.down_after = down_after
        self.calls: list[str] = []

    async def check_live(self, external_id: str) -> str:
        if self.down_after is not None and len(self.calls) >= self.down_after:
            raise SourceUnreachable("ConnectError")
        self.calls.append(external_id)
        return self.answers[external_id]


async def _company(s) -> HubCompany:
    company = HubCompany(
        name="Test GmbH", normalized_name="test", dedupe_key=f"k-{uuid.uuid4()}",
        resolution_basis="name_place", source="bundesagentur",
        first_seen_at=NOW, last_seen_at=NOW, open_postings_count=0,
    )
    s.add(company)
    await s.flush()
    return company


async def _postings(rows: dict[str, dict]) -> uuid.UUID:
    """One company, one posting per key, each with ad text in the cold table."""
    async with SessionLocal() as s:
        company = await _company(s)
        for ext, extra in rows.items():
            s.add(HubJobPosting(
                hub_company_id=company.id, title=f"Role {ext}", source="bundesagentur",
                external_id=ext, content_hash=ext, first_seen_at=NOW, last_seen_at=NOW,
                is_active=True, description_fetched_at=NOW,
                payload=HubPostingPayload(raw={"r": ext}, description=f"text {ext}"),
                **{"unlisted_at": NOW - dt.timedelta(days=1), **extra},
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


async def _check(adapter, **kw) -> dict:
    async with SessionLocal() as s:
        return await liveness.check_batch(s, adapter=adapter, delay=0, **kw)


# --- the decision: only a 404 closes ----------------------------------------


async def test_only_a_404_closes_an_ad() -> None:
    await _postings({"gone": {}, "live": {}, "unclear": {}})
    result = await _check(_Adapter({"gone": "gone", "live": "live", "unclear": "unknown"}), limit=10)

    assert result == {"checked": 3, "closed": 1, "live": 1, "unknown": 1, "source_unreachable": False}
    gone, live, unclear = await _row("gone"), await _row("live"), await _row("unclear")
    assert (gone.is_active, gone.closed_at is not None) == (False, True)
    assert (live.is_active, live.live_checked_at is not None) == (True, True)
    # An unclear answer is not evidence either way: untouched, asked again later.
    assert (unclear.is_active, unclear.live_checked_at, unclear.closed_at) == (True, None, None)


async def test_a_closed_ads_text_is_deleted_but_the_role_is_kept() -> None:
    await _postings({"gone": {}, "live": {}})
    await _check(_Adapter({"gone": "gone", "live": "live"}), limit=10)

    # The ad text, raw copy and copied page go (the disk the closure frees)…
    assert await _payload("gone") is None
    assert (await _payload("live")).description == "text live"
    # …the role stays: "this company filled it" is still a fact.
    row = await _row("gone")
    assert row.title == "Role gone" and row.is_active is False


async def test_closing_recounts_the_companys_open_roles() -> None:
    company_id = await _postings({"a": {}, "b": {}, "c": {}})
    await _check(_Adapter({"a": "gone", "b": "gone", "c": "live"}), limit=10)
    async with SessionLocal() as s:
        assert (await s.get(HubCompany, company_id)).open_postings_count == 1


async def test_an_outage_stops_the_batch_and_closes_nothing() -> None:
    await _postings({"a": {}, "b": {}, "c": {}})
    adapter = _Adapter({"a": "gone", "b": "gone", "c": "gone"}, down_after=1)
    result = await _check(adapter, limit=10)

    assert result["source_unreachable"] is True
    assert result["checked"] == 1 and adapter.calls == ["a"]
    # The one ad the source DID answer for is closed; the rest wait, unstamped.
    assert (await _row("b")).is_active and (await _row("b")).live_checked_at is None


# --- who gets checked ---------------------------------------------------------


async def test_an_ad_still_in_the_listing_is_never_checked() -> None:
    await _postings({"listed": {"unlisted_at": None}, "missing": {}})
    adapter = _Adapter({"missing": "live"})
    await _check(adapter, limit=10)
    assert adapter.calls == ["missing"]


async def test_a_recently_confirmed_ad_waits_before_the_next_check() -> None:
    await _postings({
        "fresh": {"live_checked_at": NOW - dt.timedelta(days=2)},
        "due": {"live_checked_at": NOW - dt.timedelta(days=20)},
    })
    adapter = _Adapter({"fresh": "live", "due": "live"})
    await _check(adapter, limit=10, recheck_days=14)
    assert adapter.calls == ["due"]


async def test_closed_ads_are_not_checked_again() -> None:
    await _postings({"a": {}})
    await _check(_Adapter({"a": "gone"}), limit=10)
    adapter = _Adapter({"a": "gone"})
    assert (await _check(adapter, limit=10))["checked"] == 0 and adapter.calls == []


async def test_the_batch_is_bounded_and_oldest_suspects_go_first() -> None:
    await _postings({
        "new": {"unlisted_at": NOW - dt.timedelta(hours=1)},
        "old": {"unlisted_at": NOW - dt.timedelta(days=6)},
        "mid": {"unlisted_at": NOW - dt.timedelta(days=3)},
    })
    adapter = _Adapter({"new": "live", "old": "live", "mid": "live"})
    assert (await _check(adapter, limit=2))["checked"] == 2
    assert adapter.calls == ["old", "mid"]


# --- marking suspects from the listing ----------------------------------------


async def test_mark_flags_the_missing_and_clears_the_relisted() -> None:
    await _postings({"was_missing": {}, "missing_now": {"unlisted_at": None}, "steady": {"unlisted_at": None}})
    async with SessionLocal() as s:
        result = await liveness.mark(s, segment="employer", unlisted=["missing_now"], listed=["was_missing"])
    assert result == {"unlisted": 1, "listed": 1}
    assert (await _row("missing_now")).unlisted_at is not None
    assert (await _row("was_missing")).unlisted_at is None
    assert (await _row("steady")).unlisted_at is None


async def test_marking_again_keeps_the_first_time_an_ad_went_missing() -> None:
    first = NOW - dt.timedelta(days=7)
    await _postings({"a": {"unlisted_at": first}})
    async with SessionLocal() as s:
        await liveness.mark(s, segment="employer", unlisted=["a"], listed=[])
    assert (await _row("a")).unlisted_at.replace(tzinfo=dt.UTC) == first


async def test_active_ids_page_by_key_with_the_suspect_flag() -> None:
    await _postings({"c": {"unlisted_at": None}, "a": {}, "b": {"unlisted_at": None}})
    async with SessionLocal() as s:
        first = await liveness.active_ids(s, segment="employer", after=None, limit=2)
        rest = await liveness.active_ids(s, segment="employer", after=first[-1][0], limit=2)
    assert first == [("a", True), ("b", False)]
    assert rest == [("c", False)]


async def test_a_closed_ad_published_again_reopens() -> None:
    """The source re-lists a reference it took down: the ingest touch path
    reopens it and asks for its text again (the text was deleted at closure)."""
    from app.domain.hub import service
    from app.domain.hub.schemas import IngestRequest
    from tests.test_hub_ingest import StubAdapter, _fetch_result

    ext = _fetch_result().postings[0].external_id
    async with SessionLocal() as s:
        await service.ingest(s, adapter=StubAdapter(_fetch_result()), request=IngestRequest(where="Berlin"))
    async with SessionLocal() as s:
        row = (await s.execute(select(HubJobPosting).where(HubJobPosting.external_id == ext))).scalar_one()
        row.unlisted_at = NOW
        row.description_fetched_at = NOW
        await s.commit()
    await _check(_Adapter({ext: "gone"}), limit=1)
    assert (await _row(ext)).is_active is False

    async with SessionLocal() as s:
        await service.ingest(s, adapter=StubAdapter(_fetch_result()), request=IngestRequest(where="Berlin"))
    row = await _row(ext)
    assert row.is_active is True
    assert (row.closed_at, row.unlisted_at, row.description_fetched_at) == (None, None, None)


# --- the source's answers, pure ----------------------------------------------


@pytest.mark.parametrize(
    "status, verdict",
    [(200, "live"), (404, "gone"), (410, "gone"), (500, "unknown"), (503, "unknown"), (429, "unknown"), (403, "unknown")],
)
def test_only_not_found_means_gone(status: int, verdict: str) -> None:
    assert liveness_from_status(status) == verdict


def test_the_listing_yields_every_reference_and_the_split_facets() -> None:
    fixture = pathlib.Path(__file__).parent / "fixtures" / "bundesagentur_jobs.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["facetten"] = {
        "befristung": {"counts": {"1": 3, "2": 30, "3": 7}},
        "berufsfeld": {"counts": {"Informatik": 40}},
        "arbeitsort_plz": {"counts": {"10115": 9}},  # not a split dimension
    }
    page = parse_listing(payload)
    refs = [r["referenznummer"] for r in payload["ergebnisliste"]]
    # EVERY reference — including a record the ingest gate would reject for a
    # missing employer: liveness is about the ad, not about whether we kept it.
    assert page.external_ids == refs
    assert page.total_available == payload["maxErgebnisse"]
    assert set(page.facets) == {"befristung", "berufsfeld"}


# --- endpoints: machine-only, bounded ----------------------------------------


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
