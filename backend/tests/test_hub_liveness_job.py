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
        return {"total_available": total, "facets": facets, "external_ids": ids[(page - 1) * 100: page * 100]}

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


async def test_checks_stop_at_the_budget() -> None:
    asked: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params["limit"])
        asked.append(n)
        return httpx.Response(200, json={"checked": n, "closed": n, "live": 0, "unknown": 0, "source_unreachable": False})

    totals = await check_pass(_api(handler), budget=120, batch=50)
    assert asked == [50, 50, 20] and totals["closed"] == 120


async def test_checks_stop_when_the_queue_is_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"checked": 7, "closed": 2, "live": 5, "unknown": 0, "source_unreachable": False})

    totals = await check_pass(_api(handler), budget=1_000, batch=50)
    assert totals == {"checked": 7, "closed": 2, "live": 5, "unknown": 0}


async def test_an_unreachable_source_fails_the_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"checked": 3, "closed": 0, "live": 3, "unknown": 0, "source_unreachable": True})

    with pytest.raises(SourceDown):
        await check_pass(_api(handler), budget=1_000)


async def test_five_failed_calls_in_a_row_mean_the_source_is_down(monkeypatch) -> None:
    monkeypatch.setattr("scripts.hub_liveness.asyncio.sleep", _no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"detail": "listing unavailable"})

    api = _api(handler)
    with pytest.raises((SourceDown, RuntimeError)):
        await api.call("POST", "/hub/liveness/listing", json={})
    with pytest.raises(SourceDown):
        await api.call("POST", "/hub/liveness/listing", json={})


async def _no_sleep(_seconds: float) -> None:
    return None
