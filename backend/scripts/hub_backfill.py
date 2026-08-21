"""Walk a public source and fill the hub corpus for a region.

The `/hub/ingest` endpoint takes ONE slice (one page of one query). This script
is the loop around it: shard → paginate → rate-limit → report.

    .venv/bin/python -m scripts.hub_backfill --where Berlin --radius 25
    .venv/bin/python -m scripts.hub_backfill --where Berlin --what Softwareentwickler
    .venv/bin/python -m scripts.hub_backfill --where München --where Hamburg --max-pages 20
    .venv/bin/python -m scripts.hub_backfill --where Berlin --since 1   # daily delta

Runs against `ELIGO_DATABASE_URL`, so pointing it at Supabase backfills
production. Safe to re-run: ingestion is idempotent — an unchanged posting only
bumps `last_seen_at`, so a second pass reports creations of zero.

The corpus is SHARED, so this takes no tenant: one crawl of Berlin serves every
workspace. What each tenant layers on top (tracked companies, their own CRM
rows) lives in `hub_company_link` and is untouched by a backfill.

Two limits are deliberate and REPORTED rather than silent:

  * The Bundesagentur caps deep paging (~100 pages). A shard with more results
    than that is truncated, and the script says so — split it by `--what` or a
    narrower `--where` to reach the tail.
  * `--delay` throttles requests. The API publishes no rate limit; being a
    considerate client of a free public service is the point, not a workaround.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, select

from app.core.database import AdminSessionLocal as SessionLocal
from app.core.logging import get_logger
# Registers EVERY table on Base.metadata. Required, not cosmetic: `hub_companies`
# has a foreign key to `companies`, so importing hub models alone leaves the FK
# target unresolvable and the first flush raises NoReferencedTableError.
from app.domain import registry  # noqa: F401
from app.domain.hub import service
from app.domain.hub.adapters.factory import available_sources, get_source_adapter
from app.domain.hub.gate import PreconditionFailed
from app.domain.hub.models import HubCompany, HubJobPosting
from app.domain.hub.schemas import IngestRequest

logger = get_logger(__name__)

# The API refuses to page beyond this; a shard needing more must be narrowed.
_SOURCE_PAGE_CEILING = 100


async def _corpus_size() -> tuple[int, int]:
    async with SessionLocal() as session:
        companies = await session.scalar(select(func.count(HubCompany.id)))
        postings = await session.scalar(select(func.count(HubJobPosting.id)))
    return companies or 0, postings or 0


async def _run_shard(
    *,
    source: str,
    what: str | None,
    where: str | None,
    radius: int | None,
    since: int | None,
    size: int,
    max_pages: int,
    delay: float,
) -> dict[str, int]:
    """Page through one (what, where) shard until it is exhausted."""
    adapter = get_source_adapter(source)
    label = " · ".join(part for part in (where, what) if part) or "alles"
    totals = {"pages": 0, "fetched": 0, "companies": 0, "postings": 0, "rejected": 0}
    truncated = False

    for page in range(1, max_pages + 1):
        request = IngestRequest(
            source=source,
            what=what,
            where=where,
            radius_km=radius,
            published_since_days=since,
            page=page,
            size=size,
        )
        try:
            async with SessionLocal() as session:
                summary = await service.ingest(
                    session, adapter=adapter, request=request
                )
        except PreconditionFailed as exc:
            print(f"    page {page:>3}: refused — {exc}")
            break

        totals["pages"] += 1
        totals["fetched"] += summary.fetched
        totals["companies"] += summary.companies_created
        totals["postings"] += summary.postings_created
        totals["rejected"] += len(summary.rejected)

        print(
            f"    page {page:>3}: {summary.fetched:>3} fetched  "
            f"+{summary.companies_created:>3} companies  "
            f"+{summary.postings_created:>3} postings  "
            f"~{summary.postings_updated:>3} seen before"
            + (f"  ✗{len(summary.rejected)} rejected" if summary.rejected else "")
        )

        # Page on the SOURCE's total, never on the parsed count: `fetched` is
        # post-parse, so a page holding one unattributable record comes back
        # short and would silently truncate the shard.
        total = summary.total_available
        if summary.fetched == 0 or (total is not None and page * size >= total):
            break
        if page == max_pages:
            truncated = (summary.total_available or 0) > page * size
        if page >= _SOURCE_PAGE_CEILING:
            truncated = True
            break

        await asyncio.sleep(delay)

    if truncated:
        # Never let a bounded crawl read as complete coverage.
        print(
            f"    ⚠ shard '{label}' truncated at {totals['pages']} pages — narrow it "
            f"with --what or a smaller --radius to reach the rest"
        )
    return totals


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="bundesagentur", choices=available_sources())
    parser.add_argument("--where", action="append", default=[], help="city/PLZ; repeatable")
    parser.add_argument("--what", action="append", default=[], help="keyword; repeatable")
    parser.add_argument("--radius", type=int, default=25, help="km around --where")
    parser.add_argument("--since", type=int, default=None, help="only postings published in the last N days (daily delta)")
    parser.add_argument("--size", type=int, default=100, help="records per page (API max 100)")
    parser.add_argument("--max-pages", type=int, default=25, help="page cap per shard")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    args = parser.parse_args()

    # Shards are the cross product; an empty list means "unfiltered on that axis".
    wheres = args.where or [None]
    whats = args.what or [None]

    before = await _corpus_size()
    print(f"shared corpus  ·  source {args.source}")
    print(f"corpus before: {before[0]} companies · {before[1]} postings\n")

    grand = {"pages": 0, "fetched": 0, "companies": 0, "postings": 0, "rejected": 0}
    for where in wheres:
        for what in whats:
            label = " · ".join(part for part in (where, what) if part) or "alles"
            print(f"  shard: {label}")
            totals = await _run_shard(
                source=args.source,
                what=what,
                where=where,
                radius=args.radius if where else None,
                since=args.since,
                size=args.size,
                max_pages=args.max_pages,
                delay=args.delay,
            )
            for key in grand:
                grand[key] += totals[key]
            print()

    after = await _corpus_size()
    print(f"pages {grand['pages']} · fetched {grand['fetched']} · rejected {grand['rejected']}")
    print(
        f"corpus after:  {after[0]} companies (+{after[0] - before[0]}) · "
        f"{after[1]} postings (+{after[1] - before[1]})"
    )


if __name__ == "__main__":
    asyncio.run(main())
