"""Employer headcount — a step of the weekly hub chain (ELI-54).

Two passes, both through machine-only operator routes (ARCHITECTURE.md
RULE 1 — no user, no UI):

1. **Ad texts** (`POST /hub/headcount/backfill`): employers whose ad texts
   are new since the last read, or never read, are read for a self-statement
   ("Mit rund 250 Mitarbeitenden …") by deterministic rules
   (`app/domain/hub/headcount.py`). Reads text already in the corpus — no
   fetch. Keyset-paged, so one run walks the queue once; the first run reads
   every hiring employer, later weeks only those with new text.
2. **Wikidata** (`POST /hub/headcount/wikidata`): P1128 for employers with a
   stored website domain, matched only by official website = that domain.
   Batched SPARQL, paced, one request at a time; each domain is asked again
   after 28 days. A refused query (429) ends the pass — next week resumes.

Writes are small and batched: the stamps are unindexed columns (HOT updates),
and a value is rewritten only when it changes — the Disk-IO budget of the
Small Supabase instance is why the hub chain is weekly (2026-11-12).

    ELIGO_API_BASE=… ELIGO_INGEST_TOKEN=… python -m scripts.hub_headcount \\
      --minutes 120 --wikidata 20000

Exits non-zero when a pass fails, so the workflow shows red.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import httpx

from scripts.hub_daily import _post_retrying

_BATCH = 500
#: Three SPARQL queries per request (adapters/wikidata.BATCH = 40): at
#: most ~95 s, far inside the 600 s client timeout, so a retry never
#: overlaps a request still running.
_WIKIDATA_BATCH = 120


async def _ad_texts(client: httpx.AsyncClient, *, deadline: float) -> dict[str, int]:
    totals = {"read": 0, "sized": 0, "cleared": 0}
    after = ""
    while time.monotonic() < deadline:
        response = await _post_retrying(client, f"/hub/headcount/backfill?limit={_BATCH}{after}")
        result = response.json()
        for key in totals:
            totals[key] += result.get(key, 0)
        if result.get("done") or not result.get("last_id"):
            totals["done"] = 1
            break
        after = f"&after={result['last_id']}"
    return totals


async def _wikidata(client: httpx.AsyncClient, *, budget: int, deadline: float) -> dict[str, int]:
    totals = {"asked": 0, "matched": 0, "sized": 0, "failed": 0}
    after = ""
    while totals["asked"] + totals["failed"] < budget and time.monotonic() < deadline:
        size = min(_WIKIDATA_BATCH, budget - totals["asked"] - totals["failed"])
        response = await _post_retrying(client, f"/hub/headcount/wikidata?limit={size}{after}")
        result = response.json()
        for key in totals:
            totals[key] += result.get(key, 0)
        if result.get("failed") or result.get("done") or not result.get("last_domain"):
            break
        after = "&" + str(httpx.QueryParams({"after": result["last_domain"]}))
    return totals


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=120, help="time budget for both passes")
    parser.add_argument("--wikidata", type=int, default=20_000, help="domains to ask Wikidata (0 = off)")
    args = parser.parse_args()

    base = os.environ.get("ELIGO_API_BASE", "").rstrip("/")
    token = os.environ.get("ELIGO_INGEST_TOKEN", "")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN must be set", file=sys.stderr)
        return 2
    deadline = time.monotonic() + args.minutes * 60
    failures: list[str] = []
    async with httpx.AsyncClient(
        base_url=base, timeout=600.0, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        try:
            t = await _ad_texts(client, deadline=deadline)
            state = "fertig" if t.get("done") else "Zeitbudget erreicht"
            print(
                f"Mitarbeitende (Anzeigentext): {t['read']} Unternehmen gelesen · "
                f"{t['sized']} mit Größe · {t['cleared']} entfernt · {state}"
            )
        except Exception as exc:
            print(f"headcount ad-text pass FAILED: {exc}", file=sys.stderr)
            failures.append("ad-text")
        if args.wikidata > 0:
            try:
                w = await _wikidata(client, budget=args.wikidata, deadline=deadline)
                print(
                    f"Mitarbeitende (Wikidata): {w['asked']} Domains gefragt · {w['matched']} "
                    f"Treffer · {w['sized']} übernommen · {w['failed']} abgelehnt (nächste Woche)"
                )
            except Exception as exc:
                print(f"headcount Wikidata pass FAILED: {exc}", file=sys.stderr)
                failures.append("wikidata")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
