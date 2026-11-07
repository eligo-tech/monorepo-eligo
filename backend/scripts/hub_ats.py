"""Employers' own Personio boards → the corpus (`app/domain/hub/ats.py`).

A scheduled job, over HTTP with the machine credential only — RULE 1, the
same discipline as `hub_daily.py`.

    ELIGO_API_BASE=https://…/api/v1 ELIGO_INGEST_TOKEN=… \\
      python -m scripts.hub_ats [--discover] [--minutes 90]

**`--discover`** reads Common Crawl's public URL index for every
`*.jobs.personio.de` / `*.jobs.personio.com` host in the last three crawls and
sends the board slugs to `POST /hub/ats/boards`. Measured 2026-11-06: ~2,800
distinct boards. Common Crawl sees part of Personio's customers, not all, so
discovery then reads the Wayback Machine's URL index for `*.jobs.personio.de`
(measured 2026-11-07: 6,429 boards, about half still live; the `.com` index
adds 4 and times out, and both hosts serve the same boards). A board keeps the
label of the source that found it first.

**Sync** (always) calls `POST /hub/ats/sync` until no board is due or the
time budget is spent; the backend reads one feed per board, about one a
second, and merges it.

Exits non-zero when the backend stops answering or most boards fail.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.parse

import httpx

from scripts.hub_liveness import Api, SourceDown

CRAWLS = 3
_INDEX = "https://index.commoncrawl.org"
_HOSTS = ("jobs.personio.de", "jobs.personio.com")
_SLUG = re.compile(r"^https?://([a-z0-9][a-z0-9-]{0,99})\.jobs\.personio\.(?:de|com)(?:[/:?]|$)", re.I)
#: Subdomains that are Personio's own, not an employer's board.
_NOT_BOARDS = {"www", "api", "app", "static", "assets", "cdn", "help", "support", "jobs", "careers"}
_CHUNK = 5_000
_WAYBACK = "https://web.archive.org/cdx/search/cdx?url=*.jobs.personio.de&fl=original&collapse=urlkey"


def slugs_from_urls(urls: list[str]) -> set[str]:
    """Board slugs in a list of URLs (the Wayback Machine answers one per line)."""
    found: set[str] = set()
    for url in urls:
        match = _SLUG.match(url.strip())
        if match and match.group(1).lower() not in _NOT_BOARDS:
            found.add(match.group(1).lower())
    return found


def slugs_from_index(lines: list[str]) -> set[str]:
    """Board slugs in one page of Common Crawl's JSON-lines index answer."""
    urls = []
    for line in lines:
        try:
            urls.append(json.loads(line)["url"])
        except (ValueError, KeyError, TypeError):
            continue
    return slugs_from_urls([u for u in urls if isinstance(u, str)])


async def _index(client: httpx.AsyncClient, url: str) -> str:
    """Common Crawl's index answers 504 under load: retry with back-off."""
    for attempt in range(6):
        try:
            response = await client.get(url, timeout=300)
            if response.status_code == 200:
                return response.text
        except httpx.HTTPError:
            pass
        await asyncio.sleep(15 * (attempt + 1))
    raise RuntimeError(f"Common Crawl index did not answer: {url}")


async def _common_crawl(client: httpx.AsyncClient, deadline: float) -> set[str]:
    crawls = (await client.get(f"{_INDEX}/collinfo.json", timeout=60)).json()[:CRAWLS]
    slugs: set[str] = set()
    for crawl in crawls:
        if time.monotonic() > deadline:
            print("  discover: time budget spent — sending what was found", file=sys.stderr)
            break
        for host in _HOSTS:
            query = urllib.parse.quote(f"*.{host}")
            base = f"{_INDEX}/{crawl['id']}-index?url={query}&output=json"
            try:
                pages = json.loads(await _index(client, base + "&showNumPages=true"))["pages"]
                for page in range(pages):
                    if time.monotonic() > deadline:
                        break
                    slugs |= slugs_from_index((await _index(client, f"{base}&fl=url&page={page}")).splitlines())
                    await asyncio.sleep(2)
            except Exception as exc:  # one crawl's index; the others still count
                print(f"    ! {crawl['id']} {host}: {exc}", file=sys.stderr)
        print(f"  discover: {len(slugs):,} boards after {crawl['id']}")
    return slugs


async def _wayback(client: httpx.AsyncClient) -> set[str]:
    """One answer, ~11 MB in ~100 s (measured). Three tries, then give up:
    an outage here must not cost what Common Crawl already found."""
    for attempt in range(3):
        try:
            response = await client.get(_WAYBACK, timeout=300)
            if response.status_code == 200:
                slugs = slugs_from_urls(response.text.splitlines())
                print(f"  discover: {len(slugs):,} boards in the Wayback Machine")
                return slugs
        except httpx.HTTPError:
            pass
        await asyncio.sleep(30 * (attempt + 1))
    print("    ! Wayback Machine did not answer — skipped this month", file=sys.stderr)
    return set()


async def _send(api: Api, slugs: set[str], via: str) -> int:
    added = 0
    ordered = sorted(slugs)
    for i in range(0, len(ordered), _CHUNK):
        result = await api.call("POST", "/hub/ats/boards", json={
            "ats": "personio", "slugs": ordered[i:i + _CHUNK], "discovered_via": via,
        })
        added += result["added"]
    print(f"  discover: {added:,} new boards from {via} ({len(ordered):,} seen)")
    return added


async def discover(api: Api, client: httpx.AsyncClient, *, minutes: float = 40.0) -> int:
    """Bounded: Common Crawl's index can stall for minutes per page, and the
    sync after it must keep its share of the job's time. The Wayback Machine
    is one request on its own budget (at most ~18 min with retries)."""
    found = await _common_crawl(client, time.monotonic() + minutes * 60)
    added = await _send(api, found, "commoncrawl")
    return added + await _send(api, await _wayback(client) - found, "wayback")


async def sync(api: Api, *, minutes: float, batch: int = 20) -> int:
    deadline = time.monotonic() + minutes * 60
    totals = {"boards": 0, "created": 0, "updated": 0, "closed": 0, "failed": 0}
    while time.monotonic() < deadline:
        result = await api.call("POST", "/hub/ats/sync", params={"limit": batch})
        for key in totals:
            totals[key] += result.get(key, 0)
        if result.get("source_unreachable"):
            raise SourceDown(f"Personio unreachable after {totals['boards']} boards")
        if not result.get("more_due") or not result.get("boards"):
            break
    print(f"  sync: {totals['boards']:,} boards — +{totals['created']:,} new, "
          f"~{totals['updated']:,} seen again, {totals['closed']:,} closed, {totals['failed']:,} failed")
    if totals["boards"] >= 20 and totals["failed"] > totals["boards"] / 2:
        print("FAILED: most boards could not be read", file=sys.stderr)
        return 1
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--discover", action="store_true", help="find new boards in Common Crawl first")
    parser.add_argument("--minutes", type=float, default=90.0, help="sync time budget")
    args = parser.parse_args()

    base, token = os.environ.get("ELIGO_API_BASE"), os.environ.get("ELIGO_INGEST_TOKEN")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN are required", file=sys.stderr)
        return 2
    async with httpx.AsyncClient(
        base_url=base, timeout=180.0, headers={"Authorization": f"Bearer {token}"}
    ) as client, httpx.AsyncClient(headers={"User-Agent": "eligolabs-hub/0.1 (+https://eligolabs.com)"}) as cc:
        api = Api(client)
        try:
            if args.discover:
                await discover(api, cc)
            return await sync(api, minutes=args.minutes)
        except SourceDown as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
