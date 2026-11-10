"""Employers' own job boards (Personio, Ashby, Greenhouse, Lever) → the corpus (`app/domain/hub/ats.py`).

A scheduled job, over HTTP with the machine credential only — RULE 1, the
same discipline as `hub_daily.py`.

    ELIGO_API_BASE=https://…/api/v1 ELIGO_INGEST_TOKEN=… \\
      python -m scripts.hub_ats [--ats personio|ashby|greenhouse|lever-eu|lever] [--discover [--host H]] [--minutes 90]

**`--discover`** reads Common Crawl's public URL index for every
`*.jobs.personio.de` / `*.jobs.personio.com` host in the last three crawls and
sends the board slugs to `POST /hub/ats/boards`. Measured 2026-11-06: ~2,800
distinct boards. Common Crawl sees part of Personio's customers, not all, so
discovery then reads the Wayback Machine's URL index for `*.jobs.personio.de`
(measured 2026-11-07: 6,429 boards, about half still live; the `.com` index
adds 4 and times out, and both hosts serve the same boards). A board keeps the
label of the source that found it first.

For **Ashby, Greenhouse and Lever**, boards are paths, not subdomains
(`jobs.ashbyhq.com/<slug>/…`). Discovery reads the Wayback Machine's index for
each host in 36 prefix pieces (`a*` … `9*`): one answer for a whole host was
cut off at 420 s. Measured 2026-11-08: ~7,600 Ashby, ~15,000 Greenhouse
(779 on its EU host), ~7,300 Lever (172 on its EU instance) boards. Greenhouse's
EU host is read and sent first: its boards are the richest in DACH jobs, and
new boards are synced in the order they were found.

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
_WAYBACK_MAX_BYTES = 64 * 1024 * 1024  # measured answer: ~11 MB
_WAYBACK_SECONDS = 480  # a whole answer, not one read; measured 50–198 s
_WAYBACK = "https://web.archive.org/cdx/search/cdx?url=*.jobs.personio.de&fl=original&collapse=urlkey"
_PIECE = "https://web.archive.org/cdx/search/cdx?url={host}/{prefix}*&fl=original&collapse=urlkey"
_PREFIXES = "abcdefghijklmnopqrstuvwxyz0123456789"
#: Board hosts whose first path segment is the board, per board system, in
#: the order they are read: the richest in DACH jobs first.
PATH_HOSTS = {
    "ashby": ("jobs.ashbyhq.com",),
    "greenhouse": ("job-boards.eu.greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io"),
    "lever-eu": ("jobs.eu.lever.co",),
    "lever": ("jobs.lever.co",),
}
#: First path segments that are the host's own pages, not an employer's board.
_NOT_PATH_BOARDS = {"api", "b", "meeting", "embed", "_next", "favicon.ico", "robots.txt", "static", "v1",
               "assets", "jobs", "search", "apply", "careers"}
_EMBED_FOR = re.compile(r"[?&]for=([a-z0-9][a-z0-9._-]{0,99})(?:&|$)", re.I)


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
    try:
        crawls = (await client.get(f"{_INDEX}/collinfo.json", timeout=60)).json()[:CRAWLS]
    except (httpx.HTTPError, ValueError) as exc:  # the Wayback Machine still counts
        print(f"    ! Common Crawl's crawl list did not answer: {exc}", file=sys.stderr)
        return set()
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


def path_slugs(host: str, urls: list[str]) -> set[str]:
    """Board slugs on a host whose first path segment is the board
    (`jobs.ashbyhq.com/<slug>/…`). Greenhouse's embed pages name the board in
    `?for=<slug>`."""
    pattern = re.compile(
        rf"^https?://{re.escape(host)}(?::\d+)?/([a-z0-9][a-z0-9._-]{{0,99}})(?:([/?#])(.*))?$", re.I)
    found: set[str] = set()
    for url in urls:
        match = pattern.match(url.strip())
        if not match:
            continue
        first = match.group(1).lower()
        if first == "embed":
            embedded = _EMBED_FOR.search(url)
            if embedded:
                found.add(embedded.group(1).lower())
        elif first not in _NOT_PATH_BOARDS:
            found.add(first)
    return found


def ashby_slugs(urls: list[str]) -> set[str]:
    return path_slugs("jobs.ashbyhq.com", urls)


async def _wayback_text(client: httpx.AsyncClient, url: str = _WAYBACK) -> str | None:
    async with client.stream("GET", url, timeout=300) as response:
        if response.status_code != 200:
            return None
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > _WAYBACK_MAX_BYTES:
                print("    ! Wayback answer over the size cap — ignored", file=sys.stderr)
                return ""
        return body.decode("utf-8", "replace")


async def _wayback(client: httpx.AsyncClient) -> set[str]:
    """One answer, ~11 MB in 50–198 s (measured). Three tries, each capped in
    time and size, then give up: an outage here must not cost what Common
    Crawl already found."""
    for attempt in range(3):
        if attempt:
            await asyncio.sleep(30 * attempt)
        try:
            text = await asyncio.wait_for(_wayback_text(client), _WAYBACK_SECONDS)
        except (httpx.HTTPError, TimeoutError):
            continue
        if text is None:
            continue
        slugs = slugs_from_urls(text.splitlines())
        print(f"  discover: {len(slugs):,} boards in the Wayback Machine")
        return slugs
    print("    ! Wayback Machine did not answer — skipped this month", file=sys.stderr)
    return set()


async def _paths(client: httpx.AsyncClient, host: str, deadline: float) -> set[str]:
    """One host's boards in the Wayback Machine, one prefix at a time: a
    whole-host answer is cut off (measured: 420 s). A piece that fails is
    skipped — next month's discovery asks again."""
    slugs: set[str] = set()
    for prefix in _PREFIXES:
        if time.monotonic() > deadline:
            print(f"  discover: time budget spent at {host}/{prefix}* — sending what was found",
                  file=sys.stderr)
            break
        url = _PIECE.format(host=host, prefix=prefix)
        for attempt in range(2):
            try:
                text = await asyncio.wait_for(_wayback_text(client, url), _WAYBACK_SECONDS)
            except (httpx.HTTPError, TimeoutError):
                text = None
            if text is not None:
                slugs |= path_slugs(host, text.splitlines())
                break
            if attempt == 0:
                await asyncio.sleep(30)
        else:
            print(f"    ! Wayback piece {host}/{prefix}* did not answer", file=sys.stderr)
        await asyncio.sleep(2)
    print(f"  discover: {len(slugs):,} boards on {host} in the Wayback Machine")
    return slugs


async def _send(api: Api, slugs: set[str], via: str, ats: str = "personio") -> int:
    added = 0
    ordered = sorted(slugs)
    for i in range(0, len(ordered), _CHUNK):
        result = await api.call("POST", "/hub/ats/boards", json={
            "ats": ats, "slugs": ordered[i:i + _CHUNK], "discovered_via": via,
        })
        added += result["added"]
    print(f"  discover: {added:,} new boards from {via} ({len(ordered):,} seen)")
    return added


async def discover(api: Api, client: httpx.AsyncClient, *, minutes: float = 40.0) -> int:
    """Bounded: Common Crawl's index can stall for minutes per page, and the
    sync after it must keep its share of the job's time. The Wayback Machine
    is one request on its own budget (at most ~26 min with retries)."""
    found = await _common_crawl(client, time.monotonic() + minutes * 60)
    added = await _send(api, found, "commoncrawl")
    return added + await _send(api, await _wayback(client) - found, "wayback")


async def discover_paths(
    api: Api, client: httpx.AsyncClient, ats: str, *, minutes: float = 75.0, hosts: list[str] | None = None
) -> int:
    """Each host's boards are sent as soon as that host is read, so the
    richest host's boards are found — and later read — first.

    `hosts` limits a run to some of the system's hosts: boards.greenhouse.io
    alone spends a run's budget (measured 2026-11-09), so job-boards.greenhouse.io
    is only reached by a run of its own."""
    chosen = list(PATH_HOSTS[ats])
    if hosts:
        unknown = [h for h in hosts if h not in chosen]
        if unknown:
            raise ValueError(f"not a {ats} host: {', '.join(unknown)} (known: {', '.join(chosen)})")
        chosen = [h for h in chosen if h in hosts]
    deadline = time.monotonic() + minutes * 60
    added, seen = 0, set()
    for host in chosen:
        if time.monotonic() > deadline:
            break
        found = await _paths(client, host, deadline) - seen
        seen |= found
        added += await _send(api, found, f"wayback:{host}"[:60], ats)
    return added


async def sync(api: Api, *, minutes: float, batch: int = 20, ats: str = "personio") -> int:
    deadline = time.monotonic() + minutes * 60
    totals = {"boards": 0, "created": 0, "updated": 0, "closed": 0, "failed": 0, "unnamed": 0}
    while time.monotonic() < deadline:
        result = await api.call("POST", "/hub/ats/sync", params={"limit": batch, "ats": ats})
        for key in totals:
            totals[key] += result.get(key, 0)
        if result.get("source_unreachable"):
            raise SourceDown(f"{ats} unreachable after {totals['boards']} boards")
        if not result.get("more_due") or not result.get("boards"):
            break
    print(f"  sync {ats}: {totals['boards']:,} boards — +{totals['created']:,} new, "
          f"~{totals['updated']:,} seen again, {totals['closed']:,} closed, {totals['failed']:,} failed"
          + (f", {totals['unnamed']:,} with DACH jobs but no company name" if totals["unnamed"] else ""))
    if totals["boards"] >= 20 and totals["failed"] > totals["boards"] / 2:
        print("FAILED: most boards could not be read", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """The command line, with `--host` checked before any work starts: a host
    the run cannot honour is an error, never silently ignored."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--ats", choices=("personio", *PATH_HOSTS), default="personio", help="which boards")
    parser.add_argument("--discover", action="store_true", help="find new boards in public URL indexes first")
    parser.add_argument("--host", action="append", default=None,
                        help="discover on this board host only (repeatable; Ashby/Greenhouse/Lever)")
    parser.add_argument("--minutes", type=float, default=90.0, help="sync time budget")
    args = parser.parse_args(argv)
    if args.host:
        if not args.discover:
            parser.error("--host only applies with --discover")
        known = PATH_HOSTS.get(args.ats, ())
        unknown = [h for h in args.host if h not in known]
        if unknown:
            parser.error(f"--host {', '.join(unknown)} is not a {args.ats} board host "
                         f"(known: {', '.join(known) or 'none — discovered from Common Crawl'})")
    return args


async def main() -> int:
    args = parse_args()

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
                await (discover(api, cc) if args.ats == "personio"
                       else discover_paths(api, cc, args.ats, hosts=args.host))
            return await sync(api, minutes=args.minutes, ats=args.ats)
        except SourceDown as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
