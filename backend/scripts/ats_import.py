#!/usr/bin/env python
"""Import a workspace's own ATS book into the system-of-record.

Machine-triggered, like every other ingestion here (ARCHITECTURE.md RULE 1):
no user, no UI, no request handler. Run it from cron or by hand; nothing in
the application calls it.

    python -m scripts.ats_import --tenant <uuid> [--source aifind] [--dry-run]

The source is a key from the connector registry (`domain/atsimport/factory`),
not a name written into this script: adding a system means adding a connector,
never editing the tools around it.

Credentials come from ELIGO_ATS_USER / ELIGO_ATS_SECRET (the older
AI_FIND_EMAIL / AI_FIND_PWD still work, so existing cron entries keep
running). Which of the two a connector needs is `connector.needs`.

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
from app.domain.atsimport import factory
from app.domain.atsimport import service as importer
from app.domain.atsimport.connectors.base import Credentials


def _credentials() -> Credentials:
    """Env first in the new names, then the ones the first integration used."""
    return Credentials(
        username=os.getenv("ELIGO_ATS_USER") or os.getenv("AI_FIND_EMAIL"),
        secret=os.getenv("ELIGO_ATS_SECRET") or os.getenv("AI_FIND_PWD"),
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, help="destination workspace uuid")
    parser.add_argument(
        "--source",
        default="aifind",
        choices=factory.available(),
        help="which connected system to read",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch and report, write nothing"
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="skip the per-row detail pass (one request per candidate)",
    )
    args = parser.parse_args()

    connector = factory.get_connector(args.source)
    credentials = _credentials()
    missing = [
        field
        for field in connector.needs
        if not getattr(credentials, field if field != "password" else "secret", None)
    ]
    if missing:
        print(
            f"{connector.label} braucht {', '.join(missing)} — "
            "ELIGO_ATS_USER / ELIGO_ATS_SECRET setzen",
            file=sys.stderr,
        )
        return 1

    # One fetch implementation, shared with the scheduled per-workspace runner
    # (`domain/tenantsources/runner.py`). Two copies of a login flow and two
    # detail passes would drift the first time the source changed.
    export = await connector.fetch(credentials, with_details=not args.no_details)
    for entity, count in export.counts().items():
        print(f"  {entity}: {count}")

    if args.dry_run:
        print("dry run — nothing written")
        return 0

    async with AdminSessionLocal() as session:
        summary = await importer.import_export(
            session,
            tenant_id=uuid.UUID(args.tenant),
            export=export,
            source=connector.key,
        )

    for key, value in summary.as_dict().items():
        print(f"  {key}: {value}")
    # A mandate with no client is worth seeing, not worth failing on.
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
