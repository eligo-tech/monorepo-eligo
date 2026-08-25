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

**Germany-wide, sharded by occupational field, and it measures its own coverage.**

Sharding is forced: the API refuses `page > 100`, so any single query reaches at
most 10,000 results, while Germany has ~709,700 open postings and ~30,100 new
ones per day. One query can never see the country.

The shard key is `berufsfeld`, and the shard plan comes from the API's own
response facets — not a list in this file that would silently go stale.
Measured 2026-08-22 on one day's postings:

    berufsfeld   127 fields, 99.4% coverage, 1 field over the 10k cap
    Bundesland    16 shards,  81.2% coverage, 0 shards over the cap

Bundesland's shortfall is not size. `wo=` is a place-NAME lookup, not a region
selector, so states whose names are also villages resolve to the village:
`wo=Hessen` → 82 postings for the entire state, `wo=Sachsen` → 63. No spelling
variant fixes it, and no sub-sharding fixes a query pointed at the wrong place.
`berufsfeld` has no such hole.

It is also the ONLY way a posting learns its own field: the source never returns
`berufsfeld` per record, only in facets, so a posting carries one exactly when a
crawl asked for that field. The shard key and the UI filter are the same fact.

A field over the cap is split by Bundesland — losing part of one field rather
than the whole crawl, and the coverage line reports whatever was lost. The job
probes the nationwide total every run and prints the coverage it achieved, so a
shortfall is visible rather than assumed away.

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

**Saved searches deepen the corpus where people actually recruit.** After the
regional sweep the job fetches `/hub/crawl-profiles` — the deduplicated union of
every workspace's enabled saved search — and runs one slice per directive with
the keywords passed to the SOURCE.

That matters because the source's full-text search covers posting DESCRIPTIONS,
which this corpus does not store. Measured 2026-08-22: only 5% of TypeScript
roles and 33% of Java roles carry the term in their title, so a corpus search
alone misses most of them. Passing the keywords upstream recovers the rest at a
handful of requests per profile, instead of fetching descriptions corpus-wide.

The directives carry no tenant: the crawler learns what to fetch, never who
asked.

**Every newly inserted posting gets one ad-text attempt.** The listing endpoint
returns no description, so the ingest response returns the stable source IDs it
created and this coordinator fetches exactly those details. Existing rows are
never swept merely because they lack text; the separate manual bulk workflow is
the only owner of historical backlog. A same-day rerun creates no rows and makes
no description calls.

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
_DESCRIPTION_BATCH_SIZE = 25
_DESCRIPTION_BATCH_ATTEMPTS = 4

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
    delay: float = 0.0,
    what: str | None = None,
    berufsfeld: str | None = None,
    primary: bool = False,
    created_external_ids: set[str] | None = None,
) -> dict[str, int]:
    totals = {
        "pages": 0, "fetched": 0, "companies": 0, "postings": 0, "updated": 0,
        # What the SOURCE says exists for this shard — the coverage numerator.
        "available": 0,
    }

    for page in range(1, min(max_pages, _PAGE_CEILING) + 1):
        response = await client.post(
            "/hub/ingest",
            json={
                "source": "bundesagentur",
                # Passed to the source's full-text parameter, which reaches
                # posting descriptions the corpus does not store.
                "what": what,
                "berufsfeld": berufsfeld,
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
        if created_external_ids is not None:
            created_external_ids.update(summary.get("posting_external_ids_created", []))
        if page == 1 and primary:
            # Only the PRIMARY sweep counts toward coverage. A saved-search
            # keyword slice is a subset of it and would inflate the figure.
            totals["available"] = summary.get("total_available") or 0

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
        if page == min(max_pages, _PAGE_CEILING):
            # Stopping at the page cap with results left is lost coverage. Say
            # so — a bounded crawl must never read as a complete one.
            print(
                f"    ! {region}: stopped at the {page}-page cap with "
                f"{(total or 0) - page * 100} results unread",
                file=sys.stderr,
            )
        if delay:
            # A free public service is not a load test.
            await asyncio.sleep(delay)

    return totals


async def _fetch_descriptions(
    client: httpx.AsyncClient,
    *,
    external_ids: set[str],
) -> dict[str, int]:
    """Fetch ad text only for postings created by this nightly run.

    The server fetches one source detail page at a time and deliberately paces
    those calls. Sending the nightly budget of 300 in one request therefore
    takes roughly two minutes and can be cut off by the hosting proxy even when
    every upstream call succeeds. Keep each request near ten seconds, retry a
    transiently failed batch. The explicit source IDs are the run boundary: a
    rerun does no description work for rows created by the earlier invocation,
    and historical backlog remains the manual bulk workflow's responsibility.
    """
    attempted = stored = empty = 0
    latest: dict[str, int] = {}
    pending = sorted(external_ids)

    while pending:
        batch_ids = pending[:_DESCRIPTION_BATCH_SIZE]
        pending = pending[_DESCRIPTION_BATCH_SIZE:]
        result: dict[str, int] | None = None
        for attempt in range(_DESCRIPTION_BATCH_ATTEMPTS):
            try:
                response = await client.post(
                    f"/hub/descriptions/fetch?limit={len(batch_ids)}",
                    json={"external_ids": batch_ids},
                )
                response.raise_for_status()
                result = response.json()
                break
            except Exception as exc:
                wait = min(2 ** attempt * 5, 60)
                print(
                    f"  description batch failed ({type(exc).__name__}: {exc}) — "
                    f"retrying in {wait}s",
                    file=sys.stderr,
                )
                if attempt < _DESCRIPTION_BATCH_ATTEMPTS - 1:
                    await asyncio.sleep(wait)

        if result is None:
            raise RuntimeError(
                f"description batch failed after {_DESCRIPTION_BATCH_ATTEMPTS} attempts"
            )

        latest = result
        batch_attempted = result["attempted"]
        attempted += batch_attempted
        stored += result["stored"]
        empty += result["empty"]
    return {
        **latest,
        "attempted": attempted,
        "stored": stored,
        "empty": empty,
    }


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
        "--delay",
        type=float,
        default=0.4,
        help="seconds between requests. Being a considerate client of a free "
        "public service is a design constraint, not an obstacle.",
    )
    parser.add_argument(
        "--by-region",
        action="store_true",
        help="shard by Bundesland instead of occupational field. The old "
        "behaviour, kept as an escape hatch: it reaches only ~81%% of the daily "
        "delta because `wo=` matches place names and loses whole states.",
    )
    parser.add_argument(
        "--no-descriptions",
        dest="descriptions",
        action="store_false",
        help="skip ad-text fetches for postings newly inserted by this run",
    )
    parser.add_argument(
        "--no-profiles",
        dest="profiles",
        action="store_false",
        help="skip the saved-search directives and crawl regions only",
    )
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
    grand = {
        "pages": 0, "fetched": 0, "companies": 0, "postings": 0, "updated": 0,
        "available": 0,
    }
    failures: list[str] = []
    national_total = 0
    created_external_ids: set[str] = set()

    async with httpx.AsyncClient(
        base_url=base,
        timeout=120.0,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        # One unfiltered page: ingests normally AND yields the nationwide total,
        # which is the denominator for the coverage report below.
        try:
            probe = await client.post(
                "/hub/ingest",
                json={
                    "source": "bundesagentur",
                    "published_since_days": args.since,
                    "page": 1,
                    "size": 100,
                },
            )
            probe.raise_for_status()
            body = probe.json()
            created_external_ids.update(body.get("posting_external_ids_created", []))
            national_total = body.get("total_available") or 0
            shard_plan = body.get("shard_plan") or []
        except Exception as exc:
            print(f"  probe failed: {exc}", file=sys.stderr)
            shard_plan = []

        # --- primary sweep -------------------------------------------------
        if not args.by_region and shard_plan:
            for entry in shard_plan:
                field, expected = entry["value"], entry["count"]
                print(f"  {field}  ({expected})")
                # Oversized fields cannot be read whole; split them by
                # Bundesland. `wo=` is unreliable for a few states, so this
                # loses part of ONE field rather than the whole crawl — and the
                # coverage line reports whatever was lost.
                sub_shards: list[str | None] = (
                    BUNDESLAENDER if expected > _RESULT_CEILING else [None]
                )
                if len(sub_shards) > 1:
                    print(
                        f"    ! {field}: {expected} exceeds the {_RESULT_CEILING} "
                        f"cap — splitting by Bundesland",
                        file=sys.stderr,
                    )
                for sub in sub_shards:
                    try:
                        totals = await _ingest_region(
                            client,
                            region=sub,
                            radius_km=0,
                            since_days=args.since,
                            max_pages=args.max_pages,
                            delay=args.delay,
                            berufsfeld=field,
                            primary=True,
                            created_external_ids=created_external_ids,
                        )
                    except Exception as exc:
                        print(f"    FAILED: {exc}", file=sys.stderr)
                        failures.append(field)
                        continue
                    for key in grand:
                        grand[key] += totals[key]
            regions = []  # the field sweep replaces the regional one

        for region in regions:
            print(f"  {region}")
            try:
                totals = await _ingest_region(
                    client,
                    region=region,
                    radius_km=args.radius,
                    since_days=args.since,
                    max_pages=args.max_pages,
                    delay=args.delay,
                    primary=True,
                    created_external_ids=created_external_ids,
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
        # --- saved searches: crawl what workspaces actually watch ---------
        if args.profiles:
            try:
                response = await client.get("/hub/crawl-profiles")
                response.raise_for_status()
                directives = response.json()
            except Exception as exc:
                print(f"  crawl profiles unavailable: {exc}", file=sys.stderr)
                directives = []
                failures.append("crawl-profiles")

            if directives:
                print(f"  Suchprofile ({len(directives)})")
            for directive in directives:
                label = " · ".join(
                    part for part in (directive["q"], directive.get("city")) if part
                )
                print(f"    {label}")
                try:
                    totals = await _ingest_region(
                        client,
                        region=directive.get("city"),
                        radius_km=directive.get("radius_km") or 0,
                        since_days=args.since,
                        max_pages=args.max_pages,
                        delay=args.delay,
                        what=directive["q"],
                        created_external_ids=created_external_ids,
                    )
                except Exception as exc:
                    print(f"      FAILED: {exc}", file=sys.stderr)
                    failures.append(label)
                    continue
                for key in grand:
                    grand[key] += totals[key]
            if directives:
                try:
                    await client.post("/hub/crawl-profiles/mark-crawled", json=directives)
                except Exception as exc:
                    print(f"  mark-crawled failed: {exc}", file=sys.stderr)

        # --- ad text for what people actually search -----------------------
        if args.descriptions and created_external_ids:
            try:
                d = await _fetch_descriptions(
                    client, external_ids=created_external_ids
                )
                print(
                    f"  Anzeigentexte: {d['attempted']} geprüft, +{d['stored']} geholt "
                    f"({d['empty']} ohne Text) · "
                    f"{d['with_description']}/{d['active_postings']} durchsuchbar"
                )
            except Exception as exc:
                print(f"  description fetch FAILED: {exc}", file=sys.stderr)
                failures.append("descriptions")
        elif args.descriptions:
            print("  Anzeigentexte: keine neuen Rollen in diesem Lauf")

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
    if national_total:
        pct = grand["available"] / national_total * 100
        line = (
            f"coverage {grand['available']}/{national_total} of Germany "
            f"({pct:.1f}%) for this window"
        )
        # Bundesland shards are known-incomplete (~83%); print it every run so
        # the gap stays visible rather than becoming an assumption.
        # Below the threshold, say WHERE the loss is rather than repeating a
        # generic remedy: with berufsfeld shards the residue is one oversized
        # field split by Bundesland, which is a different problem from the
        # structural hole the Bundesland-only sweep had.
        print(
            line
            if pct >= 95
            else f"{line} — the shortfall is an oversized field split by "
            f"Bundesland, whose `wo=` lookup loses some states",
            file=sys.stdout if pct >= 95 else sys.stderr,
        )
    if failures:
        print(f"FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
