"""Store Markt's corpus totals and filter counts — the last step of the weekly jobs.

Markt reads these instead of counting the corpus on a cold cache (37 s for the
filters on prod, 2026-11-12). One machine-only request; the server computes
and stores both.

    ELIGO_API_BASE=… ELIGO_INGEST_TOKEN=… python -m scripts.hub_snapshot

Exits non-zero if the refresh fails, so the workflow shows red; Markt then
keeps the previous numbers.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx

from scripts.hub_daily import _post_retrying


async def main() -> int:
    base = os.environ.get("ELIGO_API_BASE", "").rstrip("/")
    token = os.environ.get("ELIGO_INGEST_TOKEN", "")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN must be set", file=sys.stderr)
        return 2
    # Two corpus-wide counts in one request: ~50 s cold on prod.
    async with httpx.AsyncClient(
        base_url=base, timeout=600.0, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        try:
            result = (await _post_retrying(client, "/hub/corpus-snapshots/refresh")).json()
        except Exception as exc:
            print(f"corpus snapshot FAILED: {exc}", file=sys.stderr)
            return 1
    print(f"Markt-Zahlen gespeichert: {result['open_postings']} offene Stellen · {result['computed_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
