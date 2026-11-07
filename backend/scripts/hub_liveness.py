"""Nightly liveness: close the ads the source took down (`hub/liveness.py`).

Runs after the nightly ingest, over HTTP with the machine credential — same
discipline as `hub_daily.py` (RULE 1: no user, no UI, no database credential).

    ELIGO_API_BASE=https://…/api/v1 ELIGO_INGEST_TOKEN=… \\
      python -m scripts.hub_liveness [--list] [--checks 15000]

**`--list` (weekly): the full listing → suspects.** Reads the source's whole
listing (716,898 ads on 2026-11-05) shard by shard, compares it with our open
ads and marks the ones it did not see. The API refuses `page > 100`, so a shard
holds at most 10,000; fields over that are split by any facet whose counts SUM
to the shard's total (exhaustive, so no ad falls between two values). Measured
2026-11-05: 205 shards, ~5,950 pages, 81.6% of the source — Verkauf with 108k
ads cannot be cut below the cap. A shard that cannot be split is read as far as
the cap allows; the rest of its ads become suspects and cost one check each.

Marking is skipped — and the run fails — when any shard failed or coverage is
below `--min-coverage`: a broken listing would flood the queue with live ads.

**`--checks N` (nightly): suspects → verdicts.** Asks the source about up to N
suspects, longest-missing first. Only a 404 closes an ad; the backend does the
deciding, this loop only drives it. Stops early when the queue is empty or the
source is down.

**`--source eures`** runs the same two steps for Austria and Switzerland
(`adapters/eures.py`). Its listing is one listing for both segments — the
source has no agency flag, the split is ours — so it is read once and marked
per segment. Regions shard it completely (18 buckets incl. "no region",
Oberösterreich split by NACE section), 50 a page, 200 pages a shard.

Exits non-zero on failure, so the scheduler's own notification is the
monitoring (SOC 2 CC7.2).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import sys
from collections.abc import Awaitable, Callable

import httpx

_RESULT_CEILING = 10_000
_ATTEMPTS = 3
#: Consecutive failed calls before the run concludes the source is down.
_DOWN_STREAK = 5
_MARK_CHUNK = 10_000
#: A source that misanswers a batch is asked again after a pause, this many
#: times in a row at most. One blip used to fail the night: 2026-11-07, after
#: 7,275 good checks the control did not answer once, and BA answered normally
#: a minute later. Three bad batches running is not a blip.
_TROUBLE_ATTEMPTS = 3
_TROUBLE_PAUSE = 120
SEGMENTS = ("employer", "private_recruiter")


@dataclasses.dataclass(frozen=True)
class SourcePlan:
    """How one source's listing is cut and paged."""

    name: str
    #: The facet every shard starts from.
    root: str
    #: Facets that may split an oversized shard, in order.
    split_order: tuple[str, ...]
    page_size: int
    page_ceiling: int
    #: True when the source lists each segment separately (BA's `pav`); False
    #: when one listing holds both (EURES) — read once, marked per segment.
    per_segment: bool


BA = SourcePlan(
    "bundesagentur", root="berufsfeld",
    split_order=("befristung", "angebotsart", "branche", "arbeitszeit"),
    page_size=100, page_ceiling=100, per_segment=True,
)
EURES = SourcePlan(
    "eures", root="region", split_order=("sector",),
    page_size=50, page_ceiling=200, per_segment=False,
)
PLANS = {p.name: p for p in (BA, EURES)}

Listing = Callable[[dict[str, str], int], Awaitable[dict]]


class SourceDown(Exception):
    """The source stopped answering for a run of calls, not just one."""


def split_dimension(
    facets: dict[str, dict[str, int]], total: int, used: set[str], order: tuple[str, ...] = BA.split_order
) -> str | None:
    """The first facet that divides this shard exactly — or None.

    Exact means its counts sum to the shard's total: every ad has one value.
    `arbeitszeit` usually sums to more (an ad is both full- and part-time) and
    `branche` to less (some ads have none); either would lose or double ads.
    """
    for dim in order:
        counts = facets.get(dim) or {}
        if dim not in used and len(counts) > 1 and sum(counts.values()) == total:
            return dim
    return None


async def plan_shards(listing: Listing, plan: SourcePlan = BA) -> dict:
    """Shards that together cover the listing, from the source's own facets.

    Returns `leaves` (filters, expected) to read, `truncated` — the leaves over
    the cap that no facet could split — and the source's `total`.
    """
    root = await listing({}, 1)
    total = root["total_available"]
    leaves: list[tuple[dict[str, str], int]] = []
    truncated: list[tuple[dict[str, str], int]] = []

    async def place(filters: dict[str, str], expected: int) -> None:
        if expected <= _RESULT_CEILING:
            leaves.append((filters, expected))
            return
        probe = await listing(filters, 1)
        dim = split_dimension(probe["facets"], probe["total_available"], set(filters), plan.split_order)
        if dim is None:
            leaves.append((filters, probe["total_available"]))
            truncated.append((filters, probe["total_available"]))
            return
        for value, count in sorted(probe["facets"][dim].items()):
            await place({**filters, dim: value}, count)

    for field, count in sorted((root["facets"].get(plan.root) or {}).items()):
        await place({plan.root: field}, count)
    return {"leaves": leaves, "truncated": truncated, "total": total}


async def read_leaves(
    listing: Listing, leaves: list[tuple[dict[str, str], int]], plan: SourcePlan = BA
) -> dict:
    """Every reference the listing shows. A leaf that fails is recorded, not fatal."""
    live: set[str] = set()
    failed: list[dict[str, str]] = []
    for filters, expected in leaves:
        pages = min(plan.page_ceiling, -(-expected // plan.page_size)) or 1
        try:
            for page in range(1, pages + 1):
                body = await listing(filters, page)
                live.update(body["external_ids"])
                # By RECORDS, not references: a record without a reference
                # would otherwise end the shard a page early.
                if body.get("records", len(body["external_ids"])) < plan.page_size:
                    break
        except SourceDown:
            raise
        except Exception as exc:
            print(f"    ! {filters}: FAILED ({exc})", file=sys.stderr)
            failed.append(filters)
    return {"live": live, "failed": failed}


def listing_verdict(*, read: int, total: int, failed: list, min_coverage: float) -> tuple[bool, str]:
    """May this listing mark suspects? Only when it is whole enough to trust."""
    coverage = read / total if total else 0.0
    line = f"{read:,} of {total:,} listed ads read ({coverage:.1%})"
    if failed:
        return False, f"FAILED: {len(failed)} shard(s) unread — {line}; nothing marked"
    if coverage < min_coverage:
        return False, f"FAILED: coverage below {min_coverage:.0%} — {line}; nothing marked"
    return True, f"OK: {line}"


def diff(page: list[tuple[str, bool]], live: set[str]) -> tuple[list[str], list[str]]:
    """(newly unlisted, listed again) for one page of our open ads."""
    unlisted = [ext for ext, suspect in page if not suspect and ext not in live]
    listed = [ext for ext, suspect in page if suspect and ext in live]
    return unlisted, listed


# --- HTTP ---------------------------------------------------------------------


class Api:
    """The deployed API, retried. Every call here is safe to repeat."""

    def __init__(self, client: httpx.AsyncClient, *, delay: float = 0.0) -> None:
        self.client = client
        self.delay = delay
        self.streak = 0

    async def call(self, method: str, path: str, **kw) -> dict:
        error = "no attempt"
        for attempt in range(_ATTEMPTS):
            try:
                response = await self.client.request(method, path, **kw)
                if response.status_code < 500:
                    response.raise_for_status()
                    self.streak = 0
                    return response.json()
                error = f"HTTP {response.status_code}"
            except httpx.TransportError as exc:
                error = type(exc).__name__
            self.streak += 1
            if self.streak >= _DOWN_STREAK:
                raise SourceDown(f"{self.streak} calls in a row failed, last: {error}")
            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(min(2**attempt * 5, 30))
        raise RuntimeError(f"{method} {path}: {error}")

    def listing(self, segment: str, source: str = BA.name) -> Listing:
        async def page(filters: dict[str, str], number: int) -> dict:
            body = await self.call(
                "POST", "/hub/liveness/listing",
                json={"source": source, "segment": segment, "filters": filters, "page": number},
            )
            if self.delay:
                await asyncio.sleep(self.delay)  # a free public service is not a load test
            return body
        return page


async def mark_suspects(api: Api, segment: str, live: set[str], source: str = BA.name) -> dict[str, int]:
    """Walk our open ads and record which the listing did and did not show."""
    totals = {"open": 0, "unlisted": 0, "listed": 0}
    after: str | None = None
    while True:
        params = {"source": source, "segment": segment, **({"after": after} if after else {})}
        body = await api.call("GET", "/hub/liveness/active", params=params)
        page = [(ext, bool(flag)) for ext, flag in body["ids"]]
        totals["open"] += len(page)
        unlisted, listed = diff(page, live)
        for i in range(0, max(len(unlisted), len(listed)), _MARK_CHUNK):
            result = await api.call("POST", "/hub/liveness/mark", json={
                "source": source,
                "segment": segment,
                "unlisted": unlisted[i:i + _MARK_CHUNK],
                "listed": listed[i:i + _MARK_CHUNK],
            })
            totals["unlisted"] += result["unlisted"]
            totals["listed"] += result["listed"]
        after = body.get("next")
        if not after:
            return totals


async def check_pass(api: Api, *, budget: int, batch: int = 25, source: str = BA.name) -> dict:
    """Drive the backend's checker until the budget or the queue runs out.

    Stops — and fails the run — when the source is down, its control ad did not
    answer live, or a whole batch got no answer at all (throttling): asking the
    same source harder is never the fix.
    """
    totals = {"checked": 0, "closed": 0, "live": 0, "unknown": 0}
    trouble = 0
    while totals["checked"] < budget:
        size = min(batch, budget - totals["checked"])
        result = await api.call("POST", "/hub/liveness/check", params={"limit": size, "source": source})
        for key in totals:
            totals[key] += result.get(key, 0)
        checked = result.get("checked", 0)
        problem = None
        if result.get("control_failed"):
            problem = f"the control ad did not answer live after {totals['checked']} checks"
        elif result.get("source_unreachable"):
            problem = f"source unreachable after {totals['checked']} checks"
        elif checked and not (result.get("closed", 0) + result.get("live", 0)):
            problem = f"{checked} checks in a row got no answer"
        if problem:
            # Nothing was closed on a bad answer (the backend's guard). Pause
            # and ask again; only a source that stays broken ends the night.
            trouble += 1
            if trouble >= _TROUBLE_ATTEMPTS:
                raise SourceDown(problem)
            print(f"    ~ {problem} — pausing {_TROUBLE_PAUSE}s, attempt {trouble + 1} of {_TROUBLE_ATTEMPTS}",
                  file=sys.stderr)
            await asyncio.sleep(_TROUBLE_PAUSE)
            continue
        trouble = 0
        if checked == 0:
            break  # the queue is empty (a time-capped batch returns fewer than asked)
    return totals


async def list_segment(
    api: Api, segment: str, *, min_coverage: float, plan: SourcePlan = BA,
    mark_segments: tuple[str, ...] | None = None,
) -> tuple[bool, str]:
    """Read one listing, then mark it against `mark_segments` (default: the
    segment it was read for)."""
    listing = api.listing(segment, plan.name)
    shards = await plan_shards(listing, plan)
    label = segment if plan.per_segment else plan.name
    print(f"  {label}: {shards['total']:,} listed, {len(shards['leaves'])} shards, "
          f"{len(shards['truncated'])} over the cap")
    for filters, expected in shards["truncated"]:
        print(f"    ~ {filters}: {expected:,} — only {_RESULT_CEILING:,} readable", file=sys.stderr)
    read = await read_leaves(listing, shards["leaves"], plan)
    ok, line = listing_verdict(
        read=len(read["live"]), total=shards["total"], failed=read["failed"], min_coverage=min_coverage
    )
    print(f"  {label}: {line}")
    if ok:
        for target in mark_segments or (segment,):
            marked = await mark_suspects(api, target, read["live"], plan.name)
            print(f"  {target}: {marked['open']:,} open in the corpus — "
                  f"{marked['unlisted']:,} newly unlisted, {marked['listed']:,} listed again")
    return ok, line


async def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--list", action="store_true", help="read the full listing and mark suspects (weekly)")
    parser.add_argument("--checks", type=int, default=15_000, help="suspects to check tonight (0 = none)")
    parser.add_argument("--segments", default=",".join(SEGMENTS))
    parser.add_argument("--delay", type=float, default=0.2, help="seconds between listing pages")
    parser.add_argument("--min-coverage", type=float, default=0.75)
    parser.add_argument("--source", choices=sorted(PLANS), default=BA.name)
    args = parser.parse_args()
    plan = PLANS[args.source]

    base, token = os.environ.get("ELIGO_API_BASE"), os.environ.get("ELIGO_INGEST_TOKEN")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN are required", file=sys.stderr)
        return 2
    segments = [s for s in args.segments.split(",") if s]
    if any(s not in SEGMENTS for s in segments):
        print(f"--segments: one of {SEGMENTS}", file=sys.stderr)
        return 2

    failed = False
    async with httpx.AsyncClient(
        base_url=base, timeout=120.0, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        api = Api(client, delay=args.delay)
        try:
            if args.list and plan.per_segment:
                for segment in segments:
                    ok, _ = await list_segment(api, segment, min_coverage=args.min_coverage, plan=plan)
                    failed |= not ok
            elif args.list:
                ok, _ = await list_segment(
                    api, segments[0], min_coverage=args.min_coverage, plan=plan,
                    mark_segments=tuple(segments),
                )
                failed |= not ok
            if args.checks:
                totals = await check_pass(api, budget=args.checks, source=plan.name)
                print(f"  checks: {totals['checked']:,} asked — {totals['closed']:,} closed, "
                      f"{totals['live']:,} live, {totals['unknown']:,} no answer")
        except SourceDown as exc:
            print(f"FAILED: source down — {exc}", file=sys.stderr)
            return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
