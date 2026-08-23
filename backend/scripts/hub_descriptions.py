"""Bulk-fill ad text, so the corpus is searchable by what a role actually asks for.

The listing endpoint returns no description — verified against the live API, no
parameter changes that — so the only source of full text is
`/pc/v4/jobdetails/{base64(refnr)}`, **one request per posting**. There is no
bulk call to make. 26,000 postings is 26,000 requests.

That is why this is a deliberate pass rather than something the nightly job
finishes on its own: at the nightly budget of 300 it would take three months.
Run it once against the slices you care about, and let the nightly job keep up
from there.

    ELIGO_API_BASE=… ELIGO_INGEST_TOKEN=… python -m scripts.hub_descriptions --target 3000

Ordering is the union of saved searches (server-side), so the text fills in
where people actually recruit rather than uniformly across ads nobody will
place. Idempotent and resumable: only postings without a description are ever
considered, so an interrupted run costs nothing and a re-run continues. That
same property is why a failed batch is retried rather than fatal — a pass
spanning hours will meet a redeploy or a proxy blip, and abandoning the run over
one is wasteful when repeating the request costs nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

# A redeploy or a proxy blip mid-run is expected over hours, not exceptional.
_MAX_BATCH_ATTEMPTS = 4
_MAX_CONSECUTIVE_FAILURES = 3


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=int,
        default=2000,
        help="stop after roughly this many descriptions have been stored",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=25,
        help="postings per request. The server paces itself between fetches, so "
        "a larger batch is a LONGER-HELD connection, not a faster crawl — and a "
        "long request is what a hosting proxy times out. 25 keeps each request "
        "near ten seconds.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="keep going until every active posting has been attempted",
    )
    args = parser.parse_args()

    base = os.environ.get("ELIGO_API_BASE", "").rstrip("/")
    token = os.environ.get("ELIGO_INGEST_TOKEN", "")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN must be set", file=sys.stderr)
        return 2

    stored = attempted = empty = 0
    async with httpx.AsyncClient(
        base_url=base, timeout=600.0, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        # Informational only, and deliberately non-fatal: `progress` is a
        # human-authenticated read, this script carries a machine credential,
        # and a missing preamble is no reason to refuse to do the work. The
        # same numbers come back on every batch anyway.
        try:
            start = (await client.get("/hub/descriptions/progress")).json()
            print(
                f"start: {start['with_description']}/{start['active_postings']} "
                f"postings searchable by their text"
            )
        except Exception:
            pass

        consecutive_failures = 0
        while args.all or stored < args.target:
            result = None
            for attempt in range(_MAX_BATCH_ATTEMPTS):
                try:
                    response = await client.post(
                        f"/hub/descriptions/fetch?limit={args.batch}"
                    )
                    response.raise_for_status()
                    result = response.json()
                    break
                except Exception as exc:
                    # A run spanning hours WILL meet a redeploy, a proxy blip or
                    # a slow upstream. Aborting on the first one wastes the
                    # whole pass, and the work is idempotent — retrying costs
                    # nothing but a wait.
                    wait = min(2 ** attempt * 5, 60)
                    print(
                        f"  batch failed ({type(exc).__name__}: {exc}) — "
                        f"retrying in {wait}s",
                        file=sys.stderr,
                    )
                    if attempt < _MAX_BATCH_ATTEMPTS - 1:
                        await asyncio.sleep(wait)

            if result is None:
                consecutive_failures += 1
                # Persistent failure is different from a blip: stop rather than
                # hammer a service that is plainly unwell.
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    print(
                        f"giving up after {consecutive_failures} failed batches",
                        file=sys.stderr,
                    )
                    return 1
                continue
            consecutive_failures = 0

            # `attempted` is this BATCH, never the corpus total — the endpoint
            # also returns `corpus_attempted`, and conflating the two once made
            # this check unable to fire at all.
            if result["attempted"] == 0:
                print("  every active posting has now been tried")
                break

            attempted += result["attempted"]
            stored += result["stored"]
            empty += result["empty"]
            print(
                f"  +{result['stored']:>3} stored ({result['empty']} without text) · "
                f"{result['with_description']}/{result['active_postings']} searchable · "
                f"{result.get('remaining', '?')} not yet tried"
            )

    print(
        f"attempted {attempted} · stored {stored} · {empty} had no text to fetch"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
