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
job for a periodic full crawl, not this one — `scripts/hub_liveness.py`, run
after this job, closes ads the source says it no longer has.

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

**Partner-board pages are read within a nightly budget.** A third of postings
link to the same vacancy on a partner board (jobexport, get-in-it, persy, …),
and those pages often name the contact the BA text leaves out. After the ad
text, the job reads up to `--partner-pages` of them (default 400), employers a
workspace watches first, one page per posting, robots.txt respected and paced
per host. Each page is attempted once, so the backlog drains night by night
instead of being re-read.

**Private recruiters run as their own pass** (agency finder, docs/plans/
info_hub.md Phase 0a). After the employer sweep and saved searches, the same
delta is read again with `segment=private_recruiter` (`pav=true`): leads for
Eligo's own sales, never shown to a customer. Sharded by berufsfeld like the
employers, with one difference — a field over the 10,000 cap FAILS the night
instead of being split by Bundesland, because a silently short field reads as
"no agencies there". Measured 2026-11-02: 4,905 postings in one day, 45,002 in
28 days over 132 fields, largest 3,610. It prints its own coverage line and
has its own verdict. The one-off backfill is
`--agencies-only --since 28 --no-descriptions --partner-pages 0`.

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
#: Partner pages per request. Each is a paced external fetch (~1 s), and the
#: batch runs inside one HTTP call the hosting proxy may cut off.
_PARTNER_BATCH_SIZE = 20


#: Consecutive pages that must come back "source unreachable" before the sweep
#: gives up. One is a blip — on 2026-10-02 the source dropped roughly half its
#: connections while the other half returned 703 records — and abandoning the
#: night over a blip loses the shards that would have worked. A run of five
#: says the source is down, not flaky.
_UNREACHABLE_STREAK = 5


class SourceDown(Exception):
    """The source stopped answering for a run of pages, not just one.

    2026-10-02: `rest.arbeitsagentur.de` dropped connections and the run spent
    49 minutes retrying 57 pages before reporting failure. One clear message
    beats a wall of identical ones, and the shards it skips have nothing to
    fetch anyway.
    """
#: Attempts per crawl page. A page cut off by the hosting proxy is transient and
#: a slice is idempotent, so re-sending it is cheaper than losing the shard.
_PAGE_ATTEMPTS = 3

# The default shard set: all of Germany, 16 ways. Chosen because it is the
# coarsest exhaustive key whose largest daily shard stays under the cap.
BUNDESLAENDER = [
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen",
    "Hamburg", "Hessen", "Mecklenburg-Vorpommern", "Niedersachsen",
    "Nordrhein-Westfalen", "Rheinland-Pfalz", "Saarland", "Sachsen",
    "Sachsen-Anhalt", "Schleswig-Holstein", "Thüringen",
]


async def _post_ingest(
    client: httpx.AsyncClient,
    payload: dict,
    *,
    unreachable: dict[str, int],
    label: str,
) -> dict:
    """One `POST /hub/ingest`, retried. A slice is idempotent, so re-sending is safe."""
    for attempt in range(_PAGE_ATTEMPTS):
        response = await client.post("/hub/ingest", json=payload)
        # 422 + "unreachable" is the API saying the SOURCE did not answer,
        # not that this request was wrong. Worth one more try — transport
        # failures are often transient — but counted, so a source that is
        # genuinely down ends the sweep instead of being retried per shard.
        if response.status_code == 422 and "unreachable" in response.text:
            unreachable["streak"] += 1
            if unreachable["streak"] >= _UNREACHABLE_STREAK:
                raise SourceDown(
                    f"{unreachable['streak']} pages in a row: "
                    f"{response.json().get('detail', response.text)[:120]}"
                )
            if attempt < _PAGE_ATTEMPTS - 1:
                wait = min(2**attempt * 5, 60)
                print(
                    f"    {label}: source unreachable — retrying in {wait}s",
                    file=sys.stderr,
                )
                await asyncio.sleep(wait)
                continue
            # Out of attempts on this page: fail the shard the ordinary way.
            response.raise_for_status()
        if response.status_code == 200 or response.status_code == 201:
            unreachable["streak"] = 0
        try:
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            # The same failure the description batches already handle: a
            # request that outlives the hosting proxy comes back 5xx even
            # though every upstream call succeeded. On 2026-09-07 exactly
            # one shard — "Immobilienwirtschaft und Facility-Management" —
            # went quiet for 62s and then 500'd, and with no retry here that
            # single cut-off failed the whole nightly run: the sweep had
            # already reached 100.1% coverage and still exited 1.
            #
            # A crawl slice is idempotent (upserts keyed on the source id),
            # so re-sending one is safe and costs the source one more page.
            if attempt == _PAGE_ATTEMPTS - 1:
                raise
            wait = min(2**attempt * 5, 60)
            print(
                f"    {label} failed ({type(exc).__name__}: {exc}) — "
                f"retrying in {wait}s",
                file=sys.stderr,
            )
            await asyncio.sleep(wait)
    raise AssertionError("unreachable: the last attempt raises")


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
    unreachable: dict[str, int] | None = None,
    segment: str | None = None,
) -> dict[str, int]:
    totals = {
        "pages": 0, "fetched": 0, "companies": 0, "postings": 0, "updated": 0,
        # What the SOURCE says exists for this shard — the coverage numerator.
        "available": 0,
    }
    # Shared across shards by the caller, so "five in a row" means five pages,
    # not five per shard.
    unreachable = {"streak": 0} if unreachable is None else unreachable

    for page in range(1, min(max_pages, _PAGE_CEILING) + 1):
        summary = await _post_ingest(
            client,
            {
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
                # Omitted for employers, so their requests stay byte-for-
                # byte what they were.
                **({"segment": segment} if segment else {}),
                # No max_age_minutes: the scheduled job wants the real
                # thing, never a cached answer. Freshness reuse exists for
                # retries.
            },
            unreachable=unreachable,
            label=f"page {page}",
        )
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
            if segment:
                raise ShardCapExceeded(
                    f"{berufsfeld or region}: {summary['total_available']} results"
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
            if segment:
                raise ShardCapExceeded(
                    f"{berufsfeld or region}: stopped at the {page}-page cap, "
                    f"{(total or 0) - page * 100} unread"
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


async def _fetch_partner_pages(client: httpx.AsyncClient, *, budget: int) -> dict[str, int]:
    """Read up to `budget` partner-board pages, in proxy-sized batches.

    Stops early when the server reports nothing left to attempt. A batch that
    keeps failing ends the step (and fails the run) rather than looping.
    """
    totals = {"attempted": 0, "stored": 0, "failed": 0, "skipped": 0}
    latest: dict[str, int] = {}
    while totals["attempted"] < budget:
        size = min(_PARTNER_BATCH_SIZE, budget - totals["attempted"])
        result: dict[str, int] | None = None
        for attempt in range(_DESCRIPTION_BATCH_ATTEMPTS):
            try:
                response = await client.post(f"/hub/partner-pages/fetch?limit={size}")
                response.raise_for_status()
                result = response.json()
                break
            except Exception as exc:
                wait = min(2 ** attempt * 5, 60)
                print(
                    f"  partner-page batch failed ({type(exc).__name__}: {exc}) — "
                    f"retrying in {wait}s",
                    file=sys.stderr,
                )
                if attempt < _DESCRIPTION_BATCH_ATTEMPTS - 1:
                    await asyncio.sleep(wait)
        if result is None:
            raise RuntimeError(
                f"partner-page batch failed after {_DESCRIPTION_BATCH_ATTEMPTS} attempts"
            )
        latest = result
        for key in totals:
            totals[key] += result[key]
        if result["attempted"] == 0:
            break  # backlog empty
    return {**latest, **totals}


#: Agencies per site-check request. Each check is ~4 paced fetches (robots,
#: homepage, Impressum), so five keep one request well inside a proxy timeout.
_SITE_BATCH_SIZE = 5


async def _check_sites(client: httpx.AsyncClient, *, budget: int) -> dict[str, int]:
    """Verify up to `budget` agency websites, in proxy-sized batches. Stops
    when the server reports nothing left to check."""
    totals = {"checked": 0, "verified": 0, "not_named": 0, "no_impressum": 0, "blocked": 0, "error": 0}
    while totals["checked"] < budget:
        size = min(_SITE_BATCH_SIZE, budget - totals["checked"])
        response = await client.post(f"/hub/agencies/sites/check?limit={size}")
        response.raise_for_status()
        result = response.json()
        for key in totals:
            totals[key] += result.get(key, 0)
        if result.get("checked", 0) == 0:
            break
    return totals


#: Employers per request. The server stops waiting after 90 s, so a batch
#: stays inside the 120 s read timeout whatever the sites do.
_EMPLOYER_SITE_BATCH = 20


async def _check_employer_sites(client: httpx.AsyncClient, *, budget: int) -> dict[str, int]:
    """ELI-30: up to `budget` employers' Impressum (phone, VAT id, register),
    in batches. Stops when the server has nothing left to check."""
    totals = {"checked": 0, "verified": 0, "not_named": 0, "no_impressum": 0,
              "blocked": 0, "error": 0, "no_domain": 0}
    empty = 0
    while totals["checked"] < budget:
        size = min(_EMPLOYER_SITE_BATCH, budget - totals["checked"])
        response = await client.post(f"/hub/employers/sites/check?limit={size}")
        response.raise_for_status()
        result = response.json()
        for key in totals:
            totals[key] += result.get(key, 0)
        # A batch can finish nothing when every site in it is slow; two in a
        # row means there is nothing left, not bad luck.
        empty = empty + 1 if result.get("checked", 0) == 0 else 0
        if empty >= 2:
            break
    return totals


def _print_employer_sites(e: dict[str, int]) -> None:
    print(
        f"Arbeitgeber-Impressum: {e['checked']} geprüft, {e['verified']} bestätigt, "
        f"{e['no_domain']} ohne Website, {e['not_named']} fremdes Impressum, "
        f"{e['no_impressum']} ohne Impressum, {e['blocked']} gesperrt, {e['error']} Fehler"
    )


async def _link_companies(client: httpx.AsyncClient) -> dict[str, int]:
    """ELI-33: link every workspace's companies to Markt where name AND town
    match exactly (one receipt per link)."""
    response = await client.post("/hub/company-links/auto")
    response.raise_for_status()
    return response.json()


#: Ads keyed per request: one bulk UPDATE, well inside the proxy's timeout.
_VACANCY_BATCH = 5_000


async def _classify_families(client: httpx.AsyncClient, *, budget: int) -> dict[str, int]:
    """Label up to `budget` older open ads tech/other (`hub/families.py`), in
    batches — the same IO discipline as the vacancy keys."""
    totals = {"classified": 0, "remaining": 0}
    while totals["classified"] < budget:
        size = min(_VACANCY_BATCH, budget - totals["classified"])
        response = await client.post(f"/hub/job-families/backfill?limit={size}")
        response.raise_for_status()
        result = response.json()
        totals["classified"] += result.get("classified", 0)
        totals["remaining"] = result.get("remaining", 0)
        if result.get("classified", 0) < size:
            break
    return totals


#: Waits between attempts when the API is briefly gone — a deploy replaces the
#: container in well under a minute (2026-11-10: #233 deployed mid-fill).
_RETRY_WAITS = (15.0, 30.0, 60.0, 120.0)


async def _post_retrying(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """POST an idempotent batch, retrying a 5xx or a dropped connection.

    Only for passes that are safe to repeat — the ad-contacts pass reads a
    queue and replaces its rows, so a batch that ran but whose answer was lost
    is simply not in the queue any more. A 4xx (bad token, bad request) is not
    retried: waiting does not fix it.
    """
    for wait in (*_RETRY_WAITS, None):
        try:
            response = await client.post(url)
            if response.status_code < 500:
                response.raise_for_status()
                return response
            if wait is None:
                response.raise_for_status()
        except httpx.TransportError:
            if wait is None:
                raise
        print(f"  {url}: API not answering, retry in {wait:.0f}s", file=sys.stderr)
        await asyncio.sleep(wait)
    raise AssertionError("unreachable")


async def _read_ad_contacts(client: httpx.AsyncClient, *, budget: int) -> dict[str, int]:
    """Read the persons up to `budget` queued open ads name into
    `hub_ad_contacts` (`hub/ad_contacts.py`), in batches — the same IO
    discipline as the vacancy keys. Runs after the text passes, so tonight's
    new ad texts and partner pages are read tonight."""
    totals = {"read": 0, "contacts": 0, "remaining": 0}
    while totals["read"] < budget:
        size = min(_VACANCY_BATCH, budget - totals["read"])
        response = await _post_retrying(client, f"/hub/ad-contacts/backfill?limit={size}")
        result = response.json()
        totals["read"] += result.get("read", 0)
        totals["contacts"] += result.get("contacts", 0)
        totals["remaining"] = result.get("remaining", 0)
        if result.get("read", 0) < size:
            break
    return totals


_MODEL_BATCH = 50


async def _read_ad_contacts_model(client: httpx.AsyncClient, *, budget: int) -> dict[str, int]:
    """ELI-25: ask the model about up to `budget` ads the rules named nobody in
    (`hub/contact_model.py`). Runs after the rules pass, which queues them.
    Stops when the queue is empty, no model is configured (remaining -1), or a
    whole batch failed — the model is down; the ads wait for the next night."""
    totals = {"read": 0, "contacts": 0, "failed": 0, "remaining": 0}
    while totals["read"] < budget:
        size = min(_MODEL_BATCH, budget - totals["read"])
        response = await _post_retrying(client, f"/hub/ad-contacts/model-backfill?limit={size}")
        result = response.json()
        totals["read"] += result.get("read", 0)
        totals["contacts"] += result.get("contacts", 0)
        totals["failed"] += result.get("failed", 0)
        totals["remaining"] = result.get("remaining", 0)
        if totals["remaining"] < 0 or result.get("read", 0) == 0:
            break
        if result.get("read", 0) + result.get("failed", 0) < size:
            break
    return totals


def _print_model(m: dict[str, int]) -> None:
    if m["remaining"] < 0:
        print("  Ansprechpartner (Modell): kein Modell konfiguriert — übersprungen")
        return
    print(
        f"  Ansprechpartner (Modell): {m['read']} Anzeigen gelesen, {m['contacts']} Personen bestätigt, "
        f"{m['failed']} fehlgeschlagen, {m['remaining']} offen"
    )


async def _key_vacancies(client: httpx.AsyncClient, *, budget: int) -> dict[str, int]:
    """Give up to `budget` older open ads their `vacancy_key`, in batches.
    Spread over nights on purpose: one UPDATE of 650k rows would be a disk-IO
    burst on a database already short of budget."""
    totals = {"keyed": 0, "remaining": 0}
    while totals["keyed"] < budget:
        size = min(_VACANCY_BATCH, budget - totals["keyed"])
        response = await client.post(f"/hub/vacancy-keys/backfill?limit={size}")
        response.raise_for_status()
        result = response.json()
        totals["keyed"] += result.get("keyed", 0)
        totals["remaining"] = result.get("remaining", 0)
        if result.get("keyed", 0) < size:
            break
    return totals


def run_verdict(
    *,
    source_down: str | None,
    failures: list[str],
    reached: int,
    national_total: int,
    min_coverage: float,
) -> tuple[int, str]:
    """Did this night succeed? Exit code plus the line that explains it.

    It used to be "any shard failed → red", which with a source dropping ~30%
    of connections (measured 2026-10-02: 7 of 10 answered) meant a red mail
    most mornings for a run that had done nearly all its work. A daily red
    mail is a mail nobody reads, and that is how a real failure gets missed.

    So the run is judged by what reached the corpus:

      * the source being DOWN is always red — nothing was collected;
      * otherwise coverage decides, because that is the thing we actually
        care about;
      * with no coverage figure (the probe itself failed) fall back to the old
        rule: an unmeasured run cannot be called good.
    """
    if source_down:
        return 1, f"FAILED: source unreachable — {source_down}"
    if not national_total:
        if failures:
            return 1, "FAILED: no coverage figure and shards failed"
        return 0, "ok (no coverage figure available)"
    pct = reached / national_total * 100
    if pct < min_coverage:
        return 1, (
            f"FAILED: coverage {pct:.1f}% is below the {min_coverage:.0f}% this "
            f"run must reach ({len(failures)} shard(s) failed)"
        )
    if failures:
        return 0, (
            f"ok: {pct:.1f}% coverage despite {len(failures)} failed shard(s) — "
            "the source dropped connections, the corpus did not lose ground"
        )
    return 0, f"ok: {pct:.1f}% coverage"


# ---------------------------------------------------------------------------
# Private recruiters — the agency finder's leads (docs/plans/info_hub.md 0a)
# ---------------------------------------------------------------------------

PRIVATE_RECRUITER = "private_recruiter"


class ShardCapExceeded(Exception):
    """A shard of the agency pass cannot be read whole."""


def agency_shards(*, total: int, shard_plan: list[dict]) -> list[str]:
    """The berufsfeld fields to read, or ShardCapExceeded.

    Always by field, even when the whole delta would fit one query: a posting
    learns its field only from the shard that fetched it, and the field mix is
    a ranking signal for agencies.

    Unlike the employer sweep there is no Bundesland fallback. `wo=` loses
    whole states, and for leads a silently short field reads as "no agencies
    there". Fail the night instead and narrow `--since`.
    """
    if not total:
        return []
    if not shard_plan:
        raise ShardCapExceeded(f"{total} postings but the source gave no field facets")
    over = [f"{e['value']} ({e['count']})" for e in shard_plan if e["count"] > _RESULT_CEILING]
    if over:
        raise ShardCapExceeded(
            f"over the {_RESULT_CEILING} cap: {', '.join(over)} — use a smaller --since"
        )
    return [e["value"] for e in shard_plan]


async def agency_pass(
    client: httpx.AsyncClient,
    *,
    since: int,
    max_pages: int,
    delay: float,
    created_external_ids: set[str],
    unreachable: dict[str, int] | None = None,
    retry_wait: float = 30.0,
) -> dict:
    """Ingest every private-recruiter posting in the window, field by field.

    Returns what the coverage verdict needs: `available` (what the source said
    each shard held), `total` (the nationwide pav figure), failed shards, and
    `cap_exceeded` when the window cannot be read whole — in which case nothing
    beyond the probe page is fetched.
    """
    unreachable = {"streak": 0} if unreachable is None else unreachable
    result: dict = {"available": 0, "total": 0, "failures": [], "cap_exceeded": None,
                    "postings": 0, "companies": 0}
    body = await _post_ingest(
        client,
        {
            "source": "bundesagentur",
            "segment": PRIVATE_RECRUITER,
            "published_since_days": since,
            "page": 1,
            "size": 100,
        },
        unreachable=unreachable,
        label="Agenturen probe",
    )
    created_external_ids.update(body.get("posting_external_ids_created", []))
    result["total"] = body.get("total_available") or 0
    try:
        fields = agency_shards(total=result["total"], shard_plan=body.get("shard_plan") or [])
    except ShardCapExceeded as exc:
        result["cap_exceeded"] = str(exc)
        return result

    async def read(field: str) -> dict[str, int]:
        return await _ingest_region(
            client,
            region=None,
            radius_km=0,
            since_days=since,
            max_pages=max_pages,
            delay=delay,
            berufsfeld=field,
            primary=True,
            created_external_ids=created_external_ids,
            unreachable=unreachable,
            segment=PRIVATE_RECRUITER,
        )

    failed: list[str] = []
    for attempt in (1, 2):  # a second ask recovers most dropped connections
        if attempt == 2:
            await asyncio.sleep(retry_wait)
        todo, failed = (fields if attempt == 1 else failed), []
        for field in todo:
            try:
                totals = await read(field)
            except SourceDown:
                raise
            except ShardCapExceeded as exc:
                result["cap_exceeded"] = str(exc)
                return result
            except Exception as exc:
                print(f"    Agenturen · {field} FAILED: {exc}", file=sys.stderr)
                failed.append(field)
                continue
            result["available"] += totals["available"]
            result["postings"] += totals["postings"]
            result["companies"] += totals["companies"]
        if not failed:
            break
    result["failures"] = failed
    return result


def agency_verdict(result: dict, *, min_coverage: float) -> tuple[int, str]:
    """The employer rule (`run_verdict`), plus: a cap breach is always red."""
    if result.get("cap_exceeded"):
        return 1, f"FAILED: agencies — shard cap exceeded: {result['cap_exceeded']}"
    if result.get("refresh_failed"):
        # The crawl may be complete, but the list Eligo works from is stale.
        return 1, f"FAILED: agency profiles not rebuilt — {result['refresh_failed']}"
    code, message = run_verdict(
        source_down=None,
        failures=result["failures"],
        reached=result["available"],
        national_total=result["total"],
        min_coverage=min_coverage,
    )
    return code, f"agencies {message}"


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
        "--min-coverage",
        type=float,
        default=90.0,
        help="percent of the window's postings this run must reach before it "
        "counts as successful. Below it the night lost ground and the workflow "
        "goes red; above it, a few shards the source dropped are not news.",
    )
    parser.add_argument(
        "--partner-pages",
        type=int,
        default=400,
        help="partner-board pages to read this run (0 = off). Watched employers "
        "first; each page is attempted once, so the backlog drains over nights.",
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
    parser.add_argument(
        "--no-agencies",
        dest="agencies",
        action="store_false",
        help="skip the private-recruiter pass (agency finder leads)",
    )
    parser.add_argument(
        "--site-checks",
        type=int,
        default=100,
        help="agency websites to verify through their Impressum this run "
        "(0 = off). Best-scored agencies first; each domain is checked once.",
    )
    parser.add_argument(
        "--vacancy-keys",
        type=int,
        default=50_000,
        help="older open ads to give a vacancy key this run (0 = off); the "
        "backlog drains over nights, new ads are keyed at ingest",
    )
    parser.add_argument(
        "--job-families",
        type=int,
        default=60_000,
        help="older open ads to label tech/other this run (0 = off); the "
        "backlog drains over nights, new ads are labelled at ingest",
    )
    parser.add_argument(
        "--ad-contacts",
        type=int,
        default=100_000,
        help="open ads whose named contact persons to read this run (0 = off); "
        "the first backlog (~635k ads) drains over nights, then each night's "
        "new and re-fetched texts",
    )
    parser.add_argument(
        "--ad-contacts-model",
        type=int,
        default=20_000,
        help="ads the contact rules named nobody in to ask the model about this run "
        "(0 = off, ELI-25); runs after --ad-contacts",
    )
    parser.add_argument(
        "--ad-contacts-only",
        action="store_true",
        help="run ONLY the ad-contacts pass, e.g. the first fill: "
        "`--ad-contacts-only --ad-contacts 700000`",
    )
    parser.add_argument(
        "--no-company-links",
        dest="company_links",
        action="store_false",
        help="skip linking workspaces' companies to Markt (ELI-33)",
    )
    parser.add_argument(
        "--company-links-only",
        action="store_true",
        help="run ONLY the company ↔ Markt linking (ELI-33)",
    )
    parser.add_argument(
        "--employer-sites-only",
        type=int,
        default=0,
        metavar="N",
        help="run ONLY the employers' Impressum check (ELI-30) for up to N "
        "employers — the daily hub-employer-sites workflow",
    )
    parser.add_argument(
        "--agencies-only",
        action="store_true",
        help="run ONLY the private-recruiter pass — the backfill: "
        "`--agencies-only --since 28 --no-descriptions --partner-pages 0`",
    )
    args = parser.parse_args()
    if args.agencies_only:
        # Nothing but the agency pass. A stale sweep after a run that saw no
        # employer would close every employer posting, and ad text for a
        # 28-day window (~45k detail calls) would outlast the workflow; the
        # hub-descriptions workflow owns that backlog.
        args.agencies, args.profiles, args.descriptions = True, False, False
        args.partner_pages, args.stale_days, args.vacancy_keys, args.job_families = 0, 0, 0, 0
        args.ad_contacts = 0
        args.ad_contacts_model = 0
        args.company_links = False

    base = os.environ.get("ELIGO_API_BASE", "").rstrip("/")
    token = os.environ.get("ELIGO_INGEST_TOKEN", "")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN must be set", file=sys.stderr)
        return 2

    if args.company_links_only:
        async with httpx.AsyncClient(
            base_url=base, timeout=300.0, headers={"Authorization": f"Bearer {token}"}
        ) as client:
            n = await _link_companies(client)
            print(f"Unternehmen ↔ Markt: +{n['linked']} verknüpft in {n['tenants']} Workspaces")
        return 0

    if args.employer_sites_only > 0:
        async with httpx.AsyncClient(
            base_url=base, timeout=120.0, headers={"Authorization": f"Bearer {token}"}
        ) as client:
            _print_employer_sites(await _check_employer_sites(client, budget=args.employer_sites_only))
        return 0

    if args.ad_contacts_only:
        async with httpx.AsyncClient(
            base_url=base, timeout=120.0, headers={"Authorization": f"Bearer {token}"}
        ) as client:
            c = await _read_ad_contacts(client, budget=args.ad_contacts)
            print(f"Ansprechpartner: {c['read']} Anzeigen gelesen, {c['contacts']} Personen, {c['remaining']} offen")
            if args.ad_contacts_model > 0:
                _print_model(await _read_ad_contacts_model(client, budget=args.ad_contacts_model))
        return 0

    configured = os.environ.get("ELIGO_HUB_REGIONS", "").strip()
    regions = args.region or (
        [r.strip() for r in configured.split(",") if r.strip()]
        if configured
        else BUNDESLAENDER
    )
    scope = "Deutschland" if regions == BUNDESLAENDER else f"{len(regions)} shard(s)"

    if args.agencies_only:
        regions, scope = [], "nur Agenturen"
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
        shard_plan: list[dict] = []
        if not args.agencies_only:  # no employer probe when the sweep is off
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

        source_down: str | None = None
        # One counter for the whole night: the source is either answering or
        # it is not, and a per-shard count would never reach the threshold.
        unreachable = {"streak": 0}
        # Shards that failed once. With a source dropping ~30% of connections
        # (measured 2026-10-02: 7 of 10 requests answered), most succeed on a
        # second ask — and a shard abandoned after one try is a hole in the
        # corpus nobody notices.
        retryable: list[dict] = []

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
                if source_down:
                    break
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
                            unreachable=unreachable,
                        )
                    except SourceDown as exc:
                        print(f"  SOURCE DOWN: {exc} — skipping the rest of the sweep",
                              file=sys.stderr)
                        source_down = str(exc)
                        failures.append("source-unreachable")
                        break
                    except Exception as exc:
                        print(f"    FAILED: {exc}", file=sys.stderr)
                        failures.append(field)
                        retryable.append(
                            {"region": sub, "berufsfeld": field, "radius_km": 0,
                             "primary": True, "label": field}
                        )
                        continue
                    for key in grand:
                        grand[key] += totals[key]
            regions = []  # the field sweep replaces the regional one

        for region in regions:
            if source_down:
                break
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
                    unreachable=unreachable,
                )
            except SourceDown as exc:
                print(f"  SOURCE DOWN: {exc} — skipping the rest of the sweep",
                      file=sys.stderr)
                source_down = str(exc)
                failures.append("source-unreachable")
                break
            except Exception as exc:
                # One bad region must not silently shrink the corpus refresh.
                print(f"    FAILED: {exc}", file=sys.stderr)
                failures.append(region)
                retryable.append(
                    {"region": region, "radius_km": args.radius, "primary": True,
                     "label": region}
                )
                continue
            for key in grand:
                grand[key] += totals[key]

        # Off by default — see the module docstring on why a delta must not
        # drive deactivation.
        # --- saved searches: crawl what workspaces actually watch ---------
        if args.profiles and not source_down:
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
                        unreachable=unreachable,
                    )
                except Exception as exc:
                    print(f"      FAILED: {exc}", file=sys.stderr)
                    failures.append(label)
                    retryable.append(
                        {"region": directive.get("city"),
                         "radius_km": directive.get("radius_km") or 0,
                         "what": directive["q"], "label": label}
                    )
                    continue
                for key in grand:
                    grand[key] += totals[key]
            if directives:
                try:
                    await client.post("/hub/crawl-profiles/mark-crawled", json=directives)
                except Exception as exc:
                    print(f"  mark-crawled failed: {exc}", file=sys.stderr)

        # --- private recruiters: the agency finder's leads -----------------
        # Before the ad text, so new agency postings get theirs tonight too.
        agencies: dict | None = None
        # Kept apart from `source_down`: the source failing during THIS pass
        # must not skip the employers' ad text or retries, nor turn a complete
        # employer sweep into "source unreachable".
        agency_down: str | None = source_down
        if args.agencies and not source_down:
            print("  Agenturen (private Arbeitsvermittlung)")
            try:
                agencies = await agency_pass(
                    client,
                    since=args.since,
                    max_pages=args.max_pages,
                    delay=args.delay,
                    created_external_ids=created_external_ids,
                    unreachable=unreachable,
                )
            except SourceDown as exc:
                print(f"  SOURCE DOWN (Agenturen): {exc}", file=sys.stderr)
                agency_down = str(exc)
            except Exception as exc:
                print(f"  agency pass FAILED: {exc}", file=sys.stderr)
                agencies = {"available": 0, "total": 0, "failures": ["agencies"],
                            "cap_exceeded": None, "postings": 0, "companies": 0}
            if agencies:
                print(
                    f"    +{agencies['companies']} Agenturen · +{agencies['postings']} Rollen · "
                    f"coverage {agencies['available']}/{agencies['total']}"
                )
        # --- ad text for what people actually search -----------------------
        if source_down and args.descriptions:
            print("  Anzeigentexte: übersprungen — Quelle nicht erreichbar")
        elif args.descriptions and created_external_ids:
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

        # --- agency finder: verify website candidates via the Impressum -----
        # Before the rebuild, so tonight's verifications show tonight.
        if args.agencies and not agency_down and args.site_checks > 0:
            try:
                q = await _check_sites(client, budget=args.site_checks)
                print(
                    f"    Websites: {q['checked']} geprüft, {q['verified']} bestätigt, "
                    f"{q['not_named']} fremdes Impressum, {q['no_impressum']} ohne Impressum, "
                    f"{q['blocked']} gesperrt, {q['error']} Fehler"
                )
            except Exception as exc:
                print(f"  site checks FAILED: {exc}", file=sys.stderr)
                failures.append("site-checks")

        # --- agency finder: rebuild the ranked list ------------------------
        # After the ad text, so tonight's new agencies are judged with theirs;
        # even after a partial pass, so the list reflects what the corpus holds.
        if args.agencies and not agency_down:
            try:
                response = await client.post("/hub/agencies/refresh")
                response.raise_for_status()
                r = response.json()
                print(
                    f"    Agenturprofile: {r['profiles']} "
                    f"({r['agency']} Agentur · {r['unclear']} unklar · {r['client']} Kunde)"
                )
            except Exception as exc:
                print(f"  agency profile refresh FAILED: {exc}", file=sys.stderr)
                if agencies is not None:
                    agencies["refresh_failed"] = str(exc)

        # --- partner-board pages: where the named contact often is ----------
        if args.partner_pages > 0:
            try:
                q = await _fetch_partner_pages(client, budget=args.partner_pages)
                print(
                    f"  Partnerseiten: {q['attempted']} geprüft, +{q['stored']} gelesen "
                    f"({q['failed']} Fehler, {q['skipped']} übersprungen) · "
                    f"{q['source_page_read']}/{q['with_source_url']} gelesen"
                )
            except Exception as exc:
                print(f"  partner-page fetch FAILED: {exc}", file=sys.stderr)
                failures.append("partner-pages")

        # --- vacancy keys for ads that predate them (hub/vacancy.py) ---------
        if args.vacancy_keys > 0:
            try:
                k = await _key_vacancies(client, budget=args.vacancy_keys)
                print(f"  Vakanz-Schlüssel: +{k['keyed']} vergeben, {k['remaining']} offen")
            except Exception as exc:
                print(f"  vacancy-key backfill FAILED: {exc}", file=sys.stderr)
                failures.append("vacancy-keys")

        # --- tech/other labels for ads that predate them (hub/families.py) ---
        if args.job_families > 0:
            try:
                f = await _classify_families(client, budget=args.job_families)
                print(f"  Berufsfamilie: +{f['classified']} eingeordnet, {f['remaining']} offen")
            except Exception as exc:
                print(f"  job-family backfill FAILED: {exc}", file=sys.stderr)
                failures.append("job-families")

        # --- ELI-33: workspaces' companies ↔ Markt, exact name+town only ------
        # Before the contacts, so a company new in Markt tonight is linked.
        if args.company_links:
            try:
                n = await _link_companies(client)
                print(f"  Unternehmen ↔ Markt: +{n['linked']} verknüpft in {n['tenants']} Workspaces")
            except Exception as exc:
                print(f"  company links FAILED: {exc}", file=sys.stderr)
                failures.append("company-links")

        # --- persons named in open ads (hub/ad_contacts.py) — after the text passes ---
        if args.ad_contacts > 0:
            try:
                c = await _read_ad_contacts(client, budget=args.ad_contacts)
                print(f"  Ansprechpartner: {c['read']} Anzeigen gelesen, {c['contacts']} Personen, {c['remaining']} offen")
            except Exception as exc:
                print(f"  ad-contacts pass FAILED: {exc}", file=sys.stderr)
                failures.append("ad-contacts")
        if args.ad_contacts_model > 0:
            try:
                _print_model(await _read_ad_contacts_model(client, budget=args.ad_contacts_model))
            except Exception as exc:
                print(f"  ad-contacts model pass FAILED: {exc}", file=sys.stderr)
                failures.append("ad-contacts-model")

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

        # --- second pass: ask the shards that failed once more -------------
        if retryable and not source_down:
            print(f"  zweiter Versuch ({len(retryable)} Shards)")
            recovered: list[str] = []
            for shard in retryable:
                try:
                    totals = await _ingest_region(
                        client,
                        region=shard.get("region"),
                        radius_km=shard.get("radius_km", 0),
                        since_days=args.since,
                        max_pages=args.max_pages,
                        delay=args.delay,
                        what=shard.get("what"),
                        berufsfeld=shard.get("berufsfeld"),
                        primary=shard.get("primary", False),
                        created_external_ids=created_external_ids,
                        unreachable=unreachable,
                    )
                except SourceDown as exc:
                    print(f"  SOURCE DOWN: {exc}", file=sys.stderr)
                    source_down = str(exc)
                    break
                except Exception as exc:
                    print(f"    {shard['label']} erneut FAILED: {exc}", file=sys.stderr)
                    continue
                recovered.append(shard["label"])
                for key in grand:
                    grand[key] += totals[key]
            if recovered:
                print(f"    erholt: {', '.join(recovered)}")
                failures = [f for f in failures if f not in recovered]

    if not args.agencies_only:
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
    verdict = 0
    if not args.agencies_only:
        verdict, message = run_verdict(
            source_down=source_down,
            failures=failures,
            reached=grand["available"],
            national_total=national_total,
            min_coverage=args.min_coverage,
        )
        print(message, file=sys.stderr if verdict else sys.stdout)
    if args.agencies:
        if agency_down or agencies is None:
            code, message = 1, f"agencies FAILED: source unreachable — {agency_down}"
        else:
            code, message = agency_verdict(agencies, min_coverage=args.min_coverage)
        print(message, file=sys.stderr if code else sys.stdout)
        verdict = max(verdict, code)
    return verdict


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
