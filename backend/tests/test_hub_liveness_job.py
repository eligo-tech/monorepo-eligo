"""The nightly liveness job — `scripts/hub_liveness.py`.

What it must get right, measured on the live source 2026-11-05: the full
listing (716,898 ads) cannot be read in one query (10,000 cap), 24 fields are
over the cap, and only some facets divide a field exactly — `befristung` and
`angebotsart` sum to the field's total, `arbeitszeit` sums to more (an ad can
be full- and part-time) and `branche` to less. Splitting by a facet that does
not sum exactly would silently lose or double ads.
"""

from __future__ import annotations

import json

import httpx
import pytest

from scripts.hub_liveness import (
    Api,
    SourceDown,
    check_pass,
    diff,
    listing_verdict,
    mark_suspects,
    plan_shards,
    read_leaves,
    split_dimension,
)


def test_a_shard_is_split_only_by_a_facet_that_sums_to_its_total() -> None:
    facets = {
        "befristung": {"1": 3, "2": 5, "3": 2},      # sums to 10: exact
        "arbeitszeit": {"vz": 8, "tz": 6},           # sums to 14: overlaps
        "branche": {"9": 4},                         # sums to 4: incomplete
    }
    assert split_dimension(facets, 10, used=set()) == "befristung"
    assert split_dimension(facets, 10, used={"befristung"}) is None
    assert split_dimension({"angebotsart": {"1": 10}}, 10, used=set()) is None  # one value divides nothing


def _listing(tree: dict, calls: list | None = None):
    """A fake listing: `tree` maps a frozen filter set to (total, facets, ids)."""

    async def listing(filters: dict[str, str], page: int) -> dict:
        if calls is not None:
            calls.append((dict(filters), page))
        total, facets, ids = tree[frozenset(filters.items())]
        chunk = ids[(page - 1) * 100: page * 100]
        return {"total_available": total, "facets": facets, "external_ids": chunk, "records": len(chunk)}

    return listing


async def test_the_plan_splits_an_oversized_field_and_flags_what_cannot_be_split() -> None:
    tree = {
        frozenset(): (40_000, {"berufsfeld": {"Klein": 900, "Gross": 25_000, "Riesig": 14_000}}, []),
        frozenset({("berufsfeld", "Gross")}): (25_000, {"befristung": {"1": 9_000, "2": 8_000, "3": 8_000}}, []),
        frozenset({("berufsfeld", "Riesig")}): (14_000, {"arbeitszeit": {"vz": 14_000, "tz": 3_000}}, []),
    }
    plan = await plan_shards(_listing(tree))
    assert plan["total"] == 40_000
    assert ({"berufsfeld": "Gross", "befristung": "2"}, 8_000) in plan["leaves"]
    assert ({"berufsfeld": "Klein"}, 900) in plan["leaves"]
    # Riesig cannot be cut exactly: read as far as the cap allows, and say so.
    assert plan["truncated"] == [({"berufsfeld": "Riesig"}, 14_000)]
    assert ({"berufsfeld": "Riesig"}, 14_000) in plan["leaves"]


async def test_every_page_of_a_leaf_is_read_and_a_failed_leaf_is_recorded() -> None:
    ids = [f"r{i}" for i in range(250)]
    tree = {frozenset({("berufsfeld", "A")}): (250, {}, ids)}
    calls: list = []
    result = await read_leaves(_listing(tree, calls), [({"berufsfeld": "A"}, 250), ({"berufsfeld": "Kaputt"}, 5)])
    assert result["live"] == set(ids)
    assert [page for _, page in calls if _ == {"berufsfeld": "A"}] == [1, 2, 3]
    assert result["failed"] == [{"berufsfeld": "Kaputt"}]


async def test_a_page_short_of_references_but_full_of_records_reads_on() -> None:
    pages = {1: (["a"] * 99, 100), 2: (["b"], 1)}
    calls: list[int] = []

    async def listing(filters: dict[str, str], page: int) -> dict:
        calls.append(page)
        ids, records = pages[page]
        return {"total_available": 101, "facets": {}, "external_ids": ids, "records": records}

    await read_leaves(listing, [({"berufsfeld": "A"}, 101)])
    assert calls == [1, 2]


async def test_a_leaf_over_the_cap_stops_at_page_100() -> None:
    tree = {frozenset({("berufsfeld", "V")}): (108_000, {}, [f"v{i}" for i in range(20_000)])}
    calls: list = []
    await read_leaves(_listing(tree, calls), [({"berufsfeld": "V"}, 108_000)])
    assert max(page for _, page in calls) == 100


@pytest.mark.parametrize(
    "read, total, failed, ok",
    [
        (585_106, 716_898, [], True),        # the measured 81.6%
        (400_000, 716_898, [], False),       # too little to trust absence
        (700_000, 716_898, [{"berufsfeld": "X"}], False),  # a whole shard missing
        (0, 0, [], False),                   # the source said nothing
    ],
)
def test_a_listing_marks_suspects_only_when_it_is_whole_enough(read, total, failed, ok) -> None:
    assert listing_verdict(read=read, total=total, failed=failed, min_coverage=0.75)[0] is ok


def test_the_diff_flags_the_missing_and_clears_the_relisted() -> None:
    page = [("a", False), ("b", True), ("c", False), ("d", True)]
    assert diff(page, live={"a", "b"}) == (["c"], ["b"])


def _api(handler) -> Api:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://api")
    return Api(client)


async def test_marking_walks_every_page_of_our_open_ads() -> None:
    marked: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/hub/liveness/active":
            if request.url.params.get("after") is None:
                return httpx.Response(200, json={"ids": [["a", False], ["b", True]], "next": "b"})
            return httpx.Response(200, json={"ids": [["c", False]], "next": None})
        body = json.loads(request.content)
        marked.append(body)
        return httpx.Response(200, json={"unlisted": len(body["unlisted"]), "listed": len(body["listed"])})

    totals = await mark_suspects(_api(handler), "employer", live={"a", "b"})
    assert totals == {"open": 3, "unlisted": 1, "listed": 1}
    assert [m["unlisted"] for m in marked] == [[], ["c"]]
    assert [m["listed"] for m in marked] == [["b"], []]


def _answer(checked: int, closed: int = 0, live: int = 0, unknown: int = 0, **flags) -> dict:
    return {"checked": checked, "closed": closed, "live": live, "unknown": unknown,
            "source_unreachable": False, "control_failed": False, **flags}


async def test_checks_stop_at_the_budget() -> None:
    asked: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params["limit"])
        asked.append(n)
        return httpx.Response(200, json=_answer(n, closed=n))

    totals = await check_pass(_api(handler), budget=120, batch=50)
    assert asked == [50, 50, 20] and totals["closed"] == 120


async def test_checks_stop_when_the_queue_is_empty() -> None:
    answers = iter([_answer(25, closed=5, live=20), _answer(7, closed=2, live=5), _answer(0)])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(answers))

    totals = await check_pass(_api(handler), budget=1_000)
    assert totals == {"checked": 32, "closed": 7, "live": 25, "unknown": 0}


async def test_a_failed_control_fails_the_run(monkeypatch) -> None:
    monkeypatch.setattr("scripts.hub_liveness.asyncio.sleep", _no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_answer(0, control_failed=True))

    with pytest.raises(SourceDown, match="control"):
        await check_pass(_api(handler), budget=1_000)


async def test_a_batch_with_no_answers_at_all_fails_the_run(monkeypatch) -> None:
    """Throttled (429) or blocked: the same night must not keep asking."""
    monkeypatch.setattr("scripts.hub_liveness.asyncio.sleep", _no_sleep)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_answer(25, unknown=25))

    with pytest.raises(SourceDown, match="no answer"):
        await check_pass(_api(handler), budget=15_000)
    assert len(calls) == 3  # paused twice — a throttle often lifts — then stopped


async def test_an_unreachable_source_fails_the_run(monkeypatch) -> None:
    monkeypatch.setattr("scripts.hub_liveness.asyncio.sleep", _no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_answer(3, live=3, source_unreachable=True))

    with pytest.raises(SourceDown):
        await check_pass(_api(handler), budget=1_000)


async def test_five_failed_calls_in_a_row_mean_the_source_is_down(monkeypatch) -> None:
    monkeypatch.setattr("scripts.hub_liveness.asyncio.sleep", _no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"detail": "listing unavailable"})

    api = _api(handler)
    # Three attempts at the first call: an error, not yet an outage…
    with pytest.raises(RuntimeError):
        await api.call("POST", "/hub/liveness/listing", json={})
    # …two more failures make five in a row.
    with pytest.raises(SourceDown):
        await api.call("POST", "/hub/liveness/listing", json={})


async def _no_sleep(_seconds: float) -> None:
    return None


# --- a blip is not an outage (run 42290283320, 2026-11-07) -------------------
# After 7,275 good checks the control ad did not answer live once, and the
# whole night failed; a minute later BA answered normally. The run must pause
# and ask again — and still stop when the source stays broken.


@pytest.mark.parametrize("flag", ["control_failed", "source_unreachable"])
async def test_one_blip_pauses_and_the_checks_go_on(monkeypatch, flag: str) -> None:
    monkeypatch.setattr("scripts.hub_liveness.asyncio.sleep", _no_sleep)
    answers = iter([_answer(25, closed=5, live=20), _answer(0, **{flag: True}),
                    _answer(25, closed=1, live=24), _answer(0)])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(answers))

    totals = await check_pass(_api(handler), budget=1_000)
    assert totals["checked"] == 50 and totals["closed"] == 6


async def test_a_control_that_keeps_failing_still_fails_the_run(monkeypatch) -> None:
    monkeypatch.setattr("scripts.hub_liveness.asyncio.sleep", _no_sleep)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_answer(0, control_failed=True))

    with pytest.raises(SourceDown, match="control"):
        await check_pass(_api(handler), budget=1_000)
    assert len(calls) == 3  # bounded: paused twice, then gave up
