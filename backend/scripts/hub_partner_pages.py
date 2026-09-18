"""Read partner-board pages on demand, without the rest of the nightly job.

The nightly job reads up to 400 partner pages after its import, which puts them
an hour or more behind a manual trigger. This runs only that step — the same
machine-only endpoint, the same batches and retries — so "read the Quelle pages
now" takes minutes.

    ELIGO_API_BASE=… ELIGO_INGEST_TOKEN=… python -m scripts.hub_partner_pages --budget 400

Safe alongside the nightly job: each posting is attempted once, and the server
claims its batch with `FOR UPDATE SKIP LOCKED`, so two runs never fetch the
same page. Exits non-zero if the step fails, so the workflow shows red.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

from scripts.hub_daily import _fetch_partner_pages


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--budget",
        type=int,
        default=400,
        help="partner pages to read this run. Watched employers first.",
    )
    args = parser.parse_args()

    base = os.environ.get("ELIGO_API_BASE", "").rstrip("/")
    token = os.environ.get("ELIGO_INGEST_TOKEN", "")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN must be set", file=sys.stderr)
        return 2

    async with httpx.AsyncClient(
        base_url=base,
        timeout=120.0,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        try:
            q = await _fetch_partner_pages(client, budget=args.budget)
        except Exception as exc:
            print(f"partner-page fetch FAILED: {exc}", file=sys.stderr)
            return 1
    print(
        f"Partnerseiten: {q['attempted']} geprüft, +{q['stored']} gelesen "
        f"({q['failed']} Fehler, {q['skipped']} übersprungen) · "
        f"{q['source_page_read']}/{q['with_source_url']} gelesen"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
