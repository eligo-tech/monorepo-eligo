#!/usr/bin/env python
"""Import the workspace's own aiFind book into the system-of-record.

Machine-triggered, like every other ingestion here (ARCHITECTURE.md RULE 1):
no user, no UI, no request handler. Run it from cron or by hand; nothing in the
application calls it.

    python -m scripts.aifind_import --tenant <uuid> [--dry-run]

Credentials come from AI_FIND_EMAIL / AI_FIND_PWD. They are a password rather
than an API key because the source's SPA client has direct access grants
disabled, so the only way in is the browser's own flow — see
`app.integrations.aifind`.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import httpx

from app.core.database import AdminSessionLocal
from app.domain.atsimport import service as importer
from app.integrations import aifind


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, help="destination workspace uuid")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and report, write nothing",
    )
    args = parser.parse_args()

    username = os.getenv("AI_FIND_EMAIL")
    password = os.getenv("AI_FIND_PWD")
    if not username or not password:
        print("AI_FIND_EMAIL / AI_FIND_PWD are not set", file=sys.stderr)
        return 1

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await aifind.fetch_access_token(
            client, username=username, password=password
        )
        fetched = {}
        for entity in ("companies", "managers", "jobs", "candidates"):
            fetched[entity] = await aifind.fetch_all(
                client, token=token, operation=entity
            )
            print(f"  {entity}: {len(fetched[entity])}")

    if args.dry_run:
        print("dry run — nothing written")
        return 0

    async with AdminSessionLocal() as session:
        summary = await importer.import_aifind(
            session,
            tenant_id=uuid.UUID(args.tenant),
            companies=fetched["companies"],
            managers=fetched["managers"],
            jobs=fetched["jobs"],
            candidates=fetched["candidates"],
        )

    for key, value in summary.as_dict().items():
        print(f"  {key}: {value}")
    # A mandate with no client is worth seeing, not worth failing on.
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
