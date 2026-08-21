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
import sys
import uuid

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AdminSessionLocal as SessionLocal
from app.core.database import current_tenant_var
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
from app.domain.tenants.models import Tenant

logger = get_logger(__name__)

# The API refuses to page beyond this; a shard needing more must be narrowed.
_SOURCE_PAGE_CEILING = 100


async def _resolve_tenant(clerk_org_id: str | None) -> uuid.UUID:
    """Pick the tenant to load into: an explicit org, the only one, or the default."""
    async with SessionLocal() as session:
        if clerk_org_id:
            from app.domain.tenants import service as tenants_service

            tenant = await tenants_service.get_or_create(session, clerk_org_id=clerk_org_id)
            return tenant.id
        rows = (await session.execute(select(Tenant))).scalars().all()
        if len(rows) == 1:
            return rows[0].id
        if len(rows) > 1:
            sys.exit(
                f"{len(rows)} tenants exist — pass --org <clerk_org_id> to choose:\n"
                + "\n".join(f"  {t.clerk_org_id}  {t.id}" for t in rows)
            )
    return settings.default_tenant_id


async def _corpus_size(tenant_id: uuid.UUID) -> tuple[int, int]:
    async with SessionLocal() as session:
        companies = await session.scalar(
            select(func.count(HubCompany.id)).where(HubCompany.tenant_id == tenant_id)
        )
        postings = await session.scalar(
            select(func.count(HubJobPosting.id)).where(HubJobPosting.tenant_id == tenant_id)
        )
    return companies or 0, postings or 0


async def _run_shard(
    *,
    tenant_id: uuid.UUID,
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
                # Pin the tenant so RLS lets the write through on Postgres.
                current_tenant_var.set(str(tenant_id))
                summary = await service.ingest(
                    session, tenant_id=tenant_id, adapter=adapter, request=request
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

        if summary.fetched < size:
            break  # short page ⇒ end of this shard
        if page == max_pages:
            remaining = (summary.total_available or 0) - page * size
            truncated = remaining > 0
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
    parser.add_argument("--org", default=None, help="clerk_org_id of the target tenant")
    args = parser.parse_args()

    tenant_id = await _resolve_tenant(args.org)
    # Shards are the cross product; an empty list means "unfiltered on that axis".
    wheres = args.where or [None]
    whats = args.what or [None]

    before = await _corpus_size(tenant_id)
    print(f"tenant {tenant_id}  ·  source {args.source}")
    print(f"corpus before: {before[0]} companies · {before[1]} postings\n")

    grand = {"pages": 0, "fetched": 0, "companies": 0, "postings": 0, "rejected": 0}
    for where in wheres:
        for what in whats:
            label = " · ".join(part for part in (where, what) if part) or "alles"
            print(f"  shard: {label}")
            totals = await _run_shard(
                tenant_id=tenant_id,
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

    after = await _corpus_size(tenant_id)
    print(f"pages {grand['pages']} · fetched {grand['fetched']} · rejected {grand['rejected']}")
    print(
        f"corpus after:  {after[0]} companies (+{after[0] - before[0]}) · "
        f"{after[1]} postings (+{after[1] - before[1]})"
    )


if __name__ == "__main__":
    asyncio.run(main())
