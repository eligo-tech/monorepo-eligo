"""Nightly EURES ingest — Austria and Switzerland (`adapters/eures.py`).

Same discipline as `hub_daily.py` (RULE 1): a scheduled job, over HTTP, with
the machine credential only — no user, no UI, no database credential.

    ELIGO_API_BASE=https://…/api/v1 ELIGO_INGEST_TOKEN=… \\
      python -m scripts.hub_eures [--full] [--delay 0.5]

Every night it reads what changed in the last day (`LAST_DAY`: ~14,000 AT +
~5,500 CH on 2026-11-06, ~400 pages). `--full` reads everything (~89,600 ads,
~1,800 pages) — the first fill, or after an outage.

**Sharding.** A query reaches 10,000 ads at most. The 18 region buckets
(`eures.REGIONS`, including each country's "no region") hold every ad; a
bucket over the cap is split by NACE section, whose counts the source returns
with page 1 and which sum to the bucket exactly. The run probes the
two-country total and prints the coverage it reached, so a gap is a number on
every run, never an assumption.

**What is not stored**, and printed per run: ads whose employer is "siehe
Beschreibung" (two-thirds of the AMS ads), and Bundesagentur ads EURES relays
(BA is their source). See `adapters/eures.py`.

Exits non-zero when the source is down or a shard could not be read.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import os
import sys

import httpx

from scripts.hub_liveness import Api, SourceDown

# Copies of `adapters/eures.py` — the scheduler installs httpx only, not the
# app. `tests/test_hub_eures_job.py` fails when they drift apart.
REGIONS = (
    "at11", "at12", "at13", "at21", "at22", "at31", "at32", "at33", "at34", "at-NS",
    "ch01", "ch02", "ch03", "ch04", "ch05", "ch06", "ch07", "ch-NS",
)
PAGE_SIZE = 50
PAGE_CEILING = 200
_RESULT_CEILING = 10_000


async def ingest_page(api: Api, *, where: str, sector: str | None, since: int | None, page: int) -> dict:
    body = {"source": "eures", "where": where, "page": page, "size": PAGE_SIZE}
    if sector is not None:
        body["sector"] = sector
    if since is not None:
        body["published_since_days"] = since
    return await api.call("POST", "/hub/ingest", json=body)


async def read_shard(
    api: Api, *, where: str, sector: str | None, since: int | None, first: dict | None, delay: float,
    totals: collections.Counter,
) -> None:
    """Every page of one shard, by the SOURCE's total (never by what parsed:
    a page of unnamed employers parses to 0 and is not the end)."""
    summary = first or await ingest_page(api, where=where, sector=sector, since=since, page=1)
    total = summary.get("total_available") or 0
    pages = min(PAGE_CEILING, -(-total // PAGE_SIZE))
    for page in range(1, pages + 1):
        if page > 1:
            if delay:
                await asyncio.sleep(delay)  # a free public service is not a load test
            summary = await ingest_page(api, where=where, sector=sector, since=since, page=page)
        totals["created"] += summary.get("postings_created", 0)
        totals["updated"] += summary.get("postings_updated", 0)
        totals["rejected"] += len(summary.get("rejected") or [])
        for reason, count in (summary.get("dropped") or {}).items():
            totals[f"dropped: {reason}"] += count


async def plan(
    api: Api, *, since: int | None, failed: list[str]
) -> list[tuple[str, str | None, int, dict | None]]:
    """(region, sector, expected, page-1 summary) per shard.

    Page 1 of each bucket is read here, not thrown away: it is the first page
    of that shard. A bucket over the cap is replaced by its NACE sections. A
    bucket whose first page fails goes to `failed`; the others are still read.
    """
    shards: list[tuple[str, str | None, int, dict | None]] = []
    for region in REGIONS:
        try:
            first = await ingest_page(api, where=region, sector=None, since=since, page=1)
        except SourceDown:
            raise
        except Exception as exc:
            print(f"    ! {region}: FAILED ({exc})", file=sys.stderr)
            failed.append(region)
            continue
        total = first.get("total_available") or 0
        if total <= _RESULT_CEILING:
            shards.append((region, None, total, first))
            continue
        sectors = {item["value"]: item["count"] for item in first.get("shard_plan") or []}
        if sum(sectors.values()) != total:
            # Not exhaustive: reading the sections would lose or double ads.
            print(f"    ~ {region}: {total:,} over the cap and its sections do not sum "
                  f"({sum(sectors.values()):,}) — only {_RESULT_CEILING:,} readable", file=sys.stderr)
            shards.append((region, None, total, first))
            continue
        shards.extend((region, sector, count, None) for sector, count in sorted(sectors.items()))
    return shards


async def run(api: Api, *, since: int | None, delay: float) -> int:
    failed: list[str] = []
    shards = await plan(api, since=since, failed=failed)
    readable = sum(min(expected, _RESULT_CEILING) for _, _, expected, _ in shards)
    window = "everything" if since is None else f"the last {since} day(s)"
    print(f"  eures: {len(shards)} shards, {readable:,} ads in {window}")
    if since is None:
        # Coverage only means something against the unwindowed total. The
        # buckets overlap slightly (an ad in two regions), so ≥100% is normal.
        try:
            root = await api.call("POST", "/hub/liveness/listing", json={"source": "eures", "page": 1})
            total = root["total_available"]
            print(f"  eures: the two countries list {total:,} — shards reach "
                  f"{readable / total:.1%}" if total else "  eures: the source lists 0 ads")
        except SourceDown:
            raise
        except Exception as exc:
            print(f"  eures: coverage unknown ({exc})", file=sys.stderr)

    totals: collections.Counter = collections.Counter()
    for region, sector, _, first in shards:
        label = region + (f"/{sector}" if sector else "")
        try:
            await read_shard(
                api, where=region, sector=sector, since=since, first=first, delay=delay, totals=totals
            )
        except SourceDown:
            raise
        except Exception as exc:  # one shard, recorded; the run goes on
            print(f"    ! {label}: FAILED ({exc})", file=sys.stderr)
            failed.append(label)

    print(f"  eures: +{totals['created']:,} new, ~{totals['updated']:,} seen again, "
          f"{totals['rejected']:,} rejected by the gate")
    for key in sorted(k for k in totals if k.startswith("dropped: ")):
        print(f"  eures: {totals[key]:,} not stored — {key.removeprefix('dropped: ')}")
    if failed:
        print(f"FAILED: {len(failed)} shard(s) unread: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--full", action="store_true", help="read every ad, not the last day's")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between pages")
    args = parser.parse_args()

    base, token = os.environ.get("ELIGO_API_BASE"), os.environ.get("ELIGO_INGEST_TOKEN")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN are required", file=sys.stderr)
        return 2
    async with httpx.AsyncClient(
        base_url=base, timeout=180.0, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        try:
            return await run(Api(client), since=None if args.full else 1, delay=args.delay)
        except SourceDown as exc:
            print(f"FAILED: source down — {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
