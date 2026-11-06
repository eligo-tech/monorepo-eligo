"""The nightly EURES job — `scripts/hub_eures.py` — and EURES in the liveness job.

Driven against a fake API: the job only talks HTTP, so these pin what it asks
for and how it reads the answers.
"""

from __future__ import annotations

import collections
import json

import httpx

from app.domain.hub.adapters import eures
from scripts import hub_eures
from scripts.hub_liveness import EURES, Api, list_segment, plan_shards, read_leaves


def test_the_jobs_copies_match_the_adapter() -> None:
    assert hub_eures.REGIONS == eures.REGIONS
    assert (hub_eures.PAGE_SIZE, hub_eures.PAGE_CEILING) == (eures.PAGE_SIZE, eures.PAGE_CEILING)


class _Source:
    """The deployed API, faked: per-bucket totals and NACE splits."""

    def __init__(self, totals: dict[str, int], sectors: dict[str, dict[str, int]] | None = None) -> None:
        self.totals = totals
        self.sectors = sectors or {}
        self.ingests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/hub/liveness/listing"):
            self.probes = getattr(self, "probes", 0) + 1
            return httpx.Response(200, json={"external_ids": [], "records": 0,
                                             "total_available": sum(self.totals.values()), "facets": {}})
        self.ingests.append(body)
        where, sector = body["where"], body.get("sector")
        total = self.sectors[where][sector] if sector else self.totals.get(where, 0)
        plan = [{"value": k, "count": v} for k, v in self.sectors.get(where, {}).items()]
        return httpx.Response(201, json={
            "total_available": total, "postings_created": 1, "postings_updated": 0,
            "rejected": [], "dropped": {"employer not named": 2}, "shard_plan": plan,
        })


def _api(source: _Source) -> Api:
    return Api(httpx.AsyncClient(transport=httpx.MockTransport(source.handler), base_url="http://t"))


async def test_a_bucket_over_the_cap_is_read_by_its_sections() -> None:
    source = _Source({"at31": 15_401, "at13": 120}, sectors={"at31": {"c": 9_000, "o": 6_401}})
    code = await hub_eures.run(_api(source), since=1, delay=0)

    asked = collections.Counter((b["where"], b.get("sector")) for b in source.ingests)
    assert code == 0
    assert asked[("at31", "c")] == 180 and asked[("at31", "o")] == 129  # every page, ≤ 200
    assert asked[("at31", None)] == 1  # the probe only
    assert asked[("at13", None)] == 3  # page 1 reused as the first page, then 2 more
    assert all(b["published_since_days"] == 1 and b["size"] == 50 for b in source.ingests)


async def test_sections_that_do_not_sum_are_not_trusted() -> None:
    source = _Source({"at31": 15_401}, sectors={"at31": {"c": 9_000}})
    await hub_eures.run(_api(source), since=None, delay=0)

    asked = collections.Counter((b["where"], b.get("sector")) for b in source.ingests)
    assert ("at31", "c") not in asked
    assert asked[("at31", None)] == 200  # read as far as the cap allows, and said so
    assert all("published_since_days" not in b for b in source.ingests)  # --full


async def test_a_page_of_unnamed_employers_is_not_the_end_of_a_shard(capsys) -> None:
    # Every page parses to fewer records than it holds (2 dropped each): paging
    # must go by the source's total, or the shard ends after page 1.
    source = _Source({"ch04": 260})
    await hub_eures.run(_api(source), since=1, delay=0)

    assert sum(1 for b in source.ingests if b["where"] == "ch04") == 6
    assert "not stored — employer not named" in capsys.readouterr().out


async def test_a_failed_shard_fails_the_run_but_not_the_others() -> None:
    source = _Source({"at13": 60, "ch04": 60})
    inner = source.handler

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if body.get("where") == "at13":
            return httpx.Response(422, json={"detail": "ingest precondition failed"})
        return inner(request)

    api = Api(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t"))
    code = await hub_eures.run(api, since=1, delay=0)

    assert code == 1
    assert sum(1 for b in source.ingests if b["where"] == "ch04") == 2


# --- EURES in the liveness job ------------------------------------------------


def _listing(tree: dict, calls: list | None = None):
    async def listing(filters: dict[str, str], page: int) -> dict:
        if calls is not None:
            calls.append((dict(filters), page))
        key = tuple(sorted(filters.items()))
        node = tree[key]
        return {"external_ids": node.get("ids", []), "records": node.get("records", 0),
                "total_available": node["total"], "facets": node.get("facets", {})}
    return listing


async def test_the_eures_listing_starts_from_regions_and_splits_by_section() -> None:
    tree = {
        (): {"total": 15_501, "facets": {"region": {"at13": 100, "at31": 15_401}}},
        (("region", "at31"),): {"total": 15_401, "facets": {"sector": {"c": 9_000, "o": 6_401}}},
    }
    plan = await plan_shards(_listing(tree), EURES)

    assert sorted(plan["leaves"], key=str) == sorted([
        ({"region": "at13"}, 100),
        ({"region": "at31", "sector": "c"}, 9_000),
        ({"region": "at31", "sector": "o"}, 6_401),
    ], key=str)
    assert plan["truncated"] == []


async def test_eures_pages_are_fifty_and_go_to_two_hundred() -> None:
    calls: list = []
    tree = {(("region", "at31"), ("sector", "c")): {"total": 9_000, "ids": ["x"], "records": 50}}
    await read_leaves(_listing(tree, calls), [({"region": "at31", "sector": "c"}, 9_000)], EURES)

    assert len(calls) == 180


async def test_one_eures_listing_is_marked_for_both_segments() -> None:
    marked: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/listing"):
            body = json.loads(request.content)
            assert body["source"] == "eures"
            return httpx.Response(200, json={"external_ids": ["a"], "records": 1, "total_available": 1,
                                             "facets": {"region": {"at13": 1}}})
        if path.endswith("/active"):
            marked.append((request.url.params["source"], request.url.params["segment"]))
            return httpx.Response(200, json={"ids": [["a", False], ["gone", False]], "next": None})
        body = json.loads(request.content)
        assert body["source"] == "eures"
        return httpx.Response(200, json={"unlisted": len(body["unlisted"]), "listed": 0})

    api = Api(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t"))
    ok, _ = await list_segment(api, "employer", min_coverage=0.75, plan=EURES,
                               mark_segments=("employer", "private_recruiter"))

    assert ok
    assert marked == [("eures", "employer"), ("eures", "private_recruiter")]


async def test_the_full_read_prints_its_coverage_and_the_delta_does_not_ask(capsys) -> None:
    source = _Source({"at13": 60, "ch04": 40})
    await hub_eures.run(_api(source), since=None, delay=0)
    assert "shards reach 100.0%" in capsys.readouterr().out
    assert source.probes == 1

    delta = _Source({"at13": 60})
    await hub_eures.run(_api(delta), since=1, delay=0)
    assert getattr(delta, "probes", 0) == 0


async def test_a_section_the_facet_names_beyond_u_is_read() -> None:
    # NACE Rev. 2.1 section "v" — present in the live Austrian facet.
    source = _Source({"at31": 15_401}, sectors={"at31": {"c": 15_400, "v": 1}})
    code = await hub_eures.run(_api(source), since=None, delay=0)

    assert code == 0
    assert ("at31", "v") in {(b["where"], b.get("sector")) for b in source.ingests}
