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

For a workspace that onboards itself, prefer the product path: it stores its
own credential under Einstellungen and the scheduled runner imports it
(`scripts/tenant_imports`). This stays for a one-off against a tenant that
has not connected a source yet.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

from app.core.database import AdminSessionLocal
from app.domain.atsimport import service as importer
from app.domain.tenantsources import runner


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, help="destination workspace uuid")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and report, write nothing",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="skip the per-candidate detail pass (one request per candidate)",
    )
    args = parser.parse_args()

    username = os.getenv("AI_FIND_EMAIL")
    password = os.getenv("AI_FIND_PWD")
    if not username or not password:
        print("AI_FIND_EMAIL / AI_FIND_PWD are not set", file=sys.stderr)
        return 1

    # One fetch implementation, shared with the scheduled per-workspace
    # runner (`domain/tenantsources/runner.py`). Two copies of a login flow
    # and two detail passes would drift the first time the source changed.
    fetched = await runner.fetch_aifind(
        username=username, password=password, with_details=not args.no_details
    )
    for entity, rows in fetched.items():
        print(f"  {entity}: {len(rows)}")

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
