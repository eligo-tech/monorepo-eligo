"""Nightly corpus refresh — the ONLY thing that fills the hub.

Per ARCHITECTURE.md RULE 1, ingestion is a scheduled job: no user, no UI. This
script is what the cron runs.

It talks to the deployed API over HTTP with the machine credential, NOT to the
database. That is deliberate:
  * CI holds one scoped token instead of production database credentials,
  * the job exercises the same path a human would, so it cannot drift from it,
  * every run leaves the same `hub_observations` evidence trail.

    ELIGO_API_BASE=https://…/api/v1 ELIGO_INGEST_TOKEN=… \
      python -m scripts.hub_daily

**Nationwide by default.** The shard key is the Bundesland, because two hard
limits force sharding and this is the coarsest key that fits under both:

  * The API refuses `page > 100`, so ANY query reaches at most 10,000 results
    (HTTP 400 beyond that). Germany has ~709,700 open postings — a single
    nationwide query can only ever see 1.4% of them.
  * One day of new postings nationwide is ~30,100. Split across the 16 Länder
    the largest shard is Nordrhein-Westfalen at ~5,800 — comfortably under the
    cap, with room to grow.

So a full nationwide daily pass is ~320 requests and a few minutes. There is no
reason to crawl one city.

**Delta, not full re-crawl.** `--since 1` fetches only what was published in the
last day: new postings INSERT, re-published ones UPDATE, the rest of the corpus
is never touched.

`--since` is an ENUM — the source honours only {0, 1, 7, 14, 28} and silently
returns ALL 709k for anything else. The request schema rejects other values, so
a typo is a 422 rather than an accidental full crawl.

**The stale sweep does NOT belong here** and is off by default. A
publication-date delta never re-lists a posting published two months ago that is
still open, so its `last_seen_at` goes stale even though the vacancy is live —
sweeping on that basis would close roles that never closed. Deactivation is only
sound after a pass that would have re-seen everything still listed, which is a
job for a periodic full crawl, not this one.

Exits non-zero if any shard fails, so the scheduler's own failure notification
is the monitoring (SOC 2 CC7.2).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

# The API returns HTTP 400 for page > 100, so no query can ever see more than
# 10,000 results. Every sharding decision here follows from that number.
_RESULT_CEILING = 10_000
_PAGE_CEILING = 100

# The default shard set: all of Germany, 16 ways. Chosen because it is the
# coarsest exhaustive key whose largest daily shard stays under the cap.
BUNDESLAENDER = [
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen",
    "Hamburg", "Hessen", "Mecklenburg-Vorpommern", "Niedersachsen",
    "Nordrhein-Westfalen", "Rheinland-Pfalz", "Saarland", "Sachsen",
    "Sachsen-Anhalt", "Schleswig-Holstein", "Thüringen",
]


async def _ingest_region(
    client: httpx.AsyncClient,
    *,
    region: str,
    radius_km: int,
    since_days: int,
    max_pages: int,
) -> dict[str, int]:
    totals = {"pages": 0, "fetched": 0, "companies": 0, "postings": 0, "updated": 0}

    for page in range(1, min(max_pages, _PAGE_CEILING) + 1):
        response = await client.post(
            "/hub/ingest",
            json={
                "source": "bundesagentur",
                "where": region,
                "radius_km": radius_km,
                "published_since_days": since_days,
                "page": page,
                "size": 100,
                # No max_age_minutes: the scheduled job wants the real thing,
                # never a cached answer. Freshness reuse exists for retries.
            },
        )
        response.raise_for_status()
        summary = response.json()

        # A shard bigger than the ceiling cannot be fully read. Say so rather
        # than letting a truncated crawl look like complete coverage.
        if page == 1 and (summary.get("total_available") or 0) > _RESULT_CEILING:
            print(
                f"    ! {region}: {summary['total_available']} results exceed the "
                f"{_RESULT_CEILING} hard cap — this shard is truncated. Narrow it "
                f"(smaller --since, or shard by PLZ).",
                file=sys.stderr,
            )

        totals["pages"] += 1
        totals["fetched"] += summary["fetched"]
        totals["companies"] += summary["companies_created"]
        totals["postings"] += summary["postings_created"]
        totals["updated"] += summary["postings_updated"]

        print(
            f"    page {page:>2}: {summary['fetched']:>3} geprüft  "
            f"+{summary['companies_created']:>3} Unternehmen  "
            f"+{summary['postings_created']:>3} Rollen  "
            f"~{summary['postings_updated']:>3} bekannt"
        )
        # Page on the SOURCE's total, never on the parsed count. `fetched` is
        # post-parse: a page holding one anonymous employer yields 99, and
        # treating that as a short page silently truncates the whole shard.
        total = summary.get("total_available")
        if summary["fetched"] == 0 or (total is not None and page * 100 >= total):
            break

    return totals


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--region",
        action="append",
        default=[],
        help="shard key; repeatable. Defaults to $ELIGO_HUB_REGIONS, else all 16 "
        "Bundesländer — i.e. all of Germany.",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=0,
        help="km around each shard. 0 for Bundesland shards: a radius would make "
        "neighbouring Länder overlap and re-fetch the same postings.",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=1,
        choices=[0, 1, 7, 14, 28],
        help="publication window. The source honours ONLY these values and "
        "silently returns everything for any other.",
    )
    parser.add_argument("--max-pages", type=int, default=100, help="page cap per shard")
    parser.add_argument(
        "--stale-days",
        type=int,
        default=0,
        help="close postings no crawl has seen for this long. 0 (default) is OFF: "
        "a publication-date delta never re-lists older postings that are still "
        "open, so sweeping after one would close live vacancies. Only run this "
        "after a pass that re-sees everything currently listed.",
    )
    args = parser.parse_args()

    base = os.environ.get("ELIGO_API_BASE", "").rstrip("/")
    token = os.environ.get("ELIGO_INGEST_TOKEN", "")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN must be set", file=sys.stderr)
        return 2

    configured = os.environ.get("ELIGO_HUB_REGIONS", "").strip()
    regions = args.region or (
        [r.strip() for r in configured.split(",") if r.strip()]
        if configured
        else BUNDESLAENDER
    )
    scope = "Deutschland" if regions == BUNDESLAENDER else f"{len(regions)} shard(s)"

    print(f"nightly corpus refresh · {scope} · delta {args.since}d")
    grand = {"pages": 0, "fetched": 0, "companies": 0, "postings": 0, "updated": 0}
    failures: list[str] = []

    async with httpx.AsyncClient(
        base_url=base,
        timeout=120.0,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        for region in regions:
            print(f"  {region}")
            try:
                totals = await _ingest_region(
                    client,
                    region=region,
                    radius_km=args.radius,
                    since_days=args.since,
                    max_pages=args.max_pages,
                )
            except Exception as exc:
                # One bad region must not silently shrink the corpus refresh.
                print(f"    FAILED: {exc}", file=sys.stderr)
                failures.append(region)
                continue
            for key in grand:
                grand[key] += totals[key]

        # Off by default — see the module docstring on why a delta must not
        # drive deactivation.
        if args.stale_days > 0:
            try:
                response = await client.post(
                    f"/hub/maintenance/expire-stale?days={args.stale_days}"
                )
                response.raise_for_status()
                closed = response.json()
                print(
                    f"  stale: {closed['deactivated']} Rollen geschlossen "
                    f"({closed['companies_recounted']} Unternehmen neu gezählt)"
                )
            except Exception as exc:
                print(f"  stale sweep FAILED: {exc}", file=sys.stderr)
                failures.append("expire-stale")

    print(
        f"pages {grand['pages']} · geprüft {grand['fetched']} · "
        f"+{grand['companies']} Unternehmen · +{grand['postings']} Rollen · "
        f"~{grand['updated']} bekannt"
    )
    if failures:
        print(f"FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
