"""Run the imports workspaces have asked for.

The scheduled half of per-workspace onboarding: a recruiter connects their ATS
in Einstellungen and presses "Import anfordern"; this performs it. Like the
other scheduled scripts here it drives the operator endpoint over HTTP, so the
runner needs the machine token and nothing else — no database credentials in
the CI environment.

    ELIGO_API_BASE=… ELIGO_INGEST_TOKEN=… python -m scripts.tenant_imports --limit 3

Exits non-zero when a source failed, so the workflow shows red and somebody
looks — the workspace sees the same reason in its own settings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx

#: A login plus a few hundred detail calls per source; a long queue is better
#: served by several runs than by one request that times out halfway.
DEFAULT_LIMIT = 3
#: The detail passes dominate: measured at roughly a second per candidate.
TIMEOUT_SECONDS = 60 * 50


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="skip the per-candidate / per-manager detail passes (fast, but "
        "skills, phone numbers and notes are exactly what they carry)",
    )
    args = parser.parse_args()

    base = os.environ.get("ELIGO_API_BASE", "").rstrip("/")
    token = os.environ.get("ELIGO_INGEST_TOKEN", "")
    if not base or not token:
        print("ELIGO_API_BASE and ELIGO_INGEST_TOKEN must be set", file=sys.stderr)
        return 2

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{base}/tenant-sources/run-imports",
            params={"limit": args.limit, "with_details": not args.no_details},
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code >= 400:
            print(f"FAILED: HTTP {response.status_code} {response.text[:300]}", file=sys.stderr)
            return 1
        result = response.json()

    print(json.dumps(result, indent=2))
    for entry in result.get("results", []):
        mark = "ok" if entry["ok"] else "FAILED"
        print(f"  {mark}: {entry.get('error') or entry.get('summary')}")
    return 1 if result.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
