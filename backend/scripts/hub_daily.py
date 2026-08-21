"""Nightly corpus refresh — the ONLY thing that fills the hub.

Per ARCHITECTURE.md RULE 1, ingestion is a scheduled job: no user, no UI. This
script is what the cron runs.

It talks to the deployed API over HTTP with the machine credential, NOT to the
database. That is deliberate:
  * CI holds one scoped token instead of production database credentials,
  * the job exercises the same path a human would, so it cannot drift from it,
  * every run leaves the same `hub_observations` evidence trail.

    ELIGO_API_BASE=https://…/api/v1 ELIGO_INGEST_TOKEN=… \
      python -m scripts.hub_daily --region München --region Hamburg

**Delta, not full re-crawl.** Each region is fetched with
`published_since_days` (default 2), so a run sees only what was published
recently: new postings INSERT, re-published ones UPDATE, and the rest of the
corpus is never touched. A nightly run is therefore small and cheap, which is
the point — nothing is "recalculated".

A delta cannot observe a REMOVAL: a filled vacancy simply stops appearing.
Absence is only visible over time, so the run finishes by closing postings no
crawl has seen for `--stale-days`.

Exits non-zero if any region fails, so the scheduler's own failure notification
is the monitoring (SOC 2 CC7.2).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

# The source refuses to page beyond this; a delta should never come close.
_PAGE_CEILING = 50


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
        if summary["fetched"] < 100:
            break  # short page ⇒ delta exhausted

    return totals


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--region",
        action="append",
        default=[],
        help="city/PLZ; repeatable. Defaults to $ELIGO_HUB_REGIONS (comma-separated).",
    )
    parser.add_argument("--radius", type=int, default=25, help="km around each region")
    parser.add_argument(
        "--since",
        type=int,
        default=2,
        help="only postings published in the last N days. 2 not 1, so a missed "
        "or late run still overlaps the previous day instead of leaving a hole.",
    )
    parser.add_argument("--max-pages", type=int, default=20, help="page cap per region")
    parser.add_argument(
        "--stale-days",
        type=int,
        default=14,
        help="close postings no crawl has seen for this long. 0 disables.",
    )
    args = parser.parse_args()

    base = os.environ.get("ELIGO_API_BASE", "").rstrip("/")
    token = os.environ.get("ELIGO_INGEST_TOKEN", "")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN must be set", file=sys.stderr)
        return 2

    regions = args.region or [
        r.strip()
        for r in os.environ.get("ELIGO_HUB_REGIONS", "München").split(",")
        if r.strip()
    ]

    print(f"nightly corpus refresh · {len(regions)} region(s) · delta {args.since}d")
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
