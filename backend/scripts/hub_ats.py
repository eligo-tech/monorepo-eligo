"""Employers' own Personio boards → the corpus (`app/domain/hub/ats.py`).

A scheduled job, over HTTP with the machine credential only — RULE 1, the
same discipline as `hub_daily.py`.

    ELIGO_API_BASE=https://…/api/v1 ELIGO_INGEST_TOKEN=… \\
      python -m scripts.hub_ats [--discover] [--minutes 90]

**`--discover`** reads Common Crawl's public URL index for every
`*.jobs.personio.de` / `*.jobs.personio.com` host in the last three crawls and
sends the board slugs to `POST /hub/ats/boards`. Measured 2026-11-06: ~2,000
distinct boards. Common Crawl sees part of Personio's customers, not all.

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


def slugs_from_index(lines: list[str]) -> set[str]:
    """Board slugs in one page of Common Crawl's JSON-lines index answer."""
    found: set[str] = set()
    for line in lines:
        try:
            url = json.loads(line)["url"]
        except (ValueError, KeyError, TypeError):
            continue
        match = _SLUG.match(url)
        if match and match.group(1).lower() not in _NOT_BOARDS:
            found.add(match.group(1).lower())
    return found


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


async def discover(api: Api, client: httpx.AsyncClient, *, minutes: float = 40.0) -> int:
    """Bounded: Common Crawl's index can stall for minutes per page, and the
    sync after it must keep its share of the job's time."""
    deadline = time.monotonic() + minutes * 60
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
    added = 0
    ordered = sorted(slugs)
    for i in range(0, len(ordered), _CHUNK):
        result = await api.call("POST", "/hub/ats/boards", json={
            "ats": "personio", "slugs": ordered[i:i + _CHUNK], "discovered_via": "commoncrawl",
        })
        added += result["added"]
    print(f"  discover: {added:,} new boards ({len(ordered):,} seen)")
    return added


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
