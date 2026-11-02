"""Add a company or a person to the corpus opt-out list, and clean up.

    python -m scripts.hub_suppress company "Zebrafink Personalberatung GmbH" --reason objection
    python -m scripts.hub_suppress person  "Katrin Wolter" --reason erasure
    python -m scripts.hub_suppress list

`company` removes every corpus row of that name (every site, employer and
agency rows) and refuses it at every future ingest. `person` cuts the name out
of every stored ad text and out of every future one. Both are idempotent; run
again to re-sweep. A crawl already running when you suppress still uses the
list as it was when it started — run the command once more after the nightly
job has finished.

Owner connection (`ELIGO_ADMIN_DATABASE_URL`): the app role can read the list
but not write it. A tenant's own `companies` / `managers` rows are its record
and are NOT touched — an erasure request that covers them is handled in that
workspace.

Keep the request itself (who asked, when, how answered) in the request log,
not here: this table holds only what is needed to recognise the record.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.database import AdminSessionLocal, admin_engine, current_tenant_var
from app.domain import registry  # noqa: F401 — register all models
from app.domain.hub import suppression
from app.domain.hub.models import SUPPRESSION_REASONS, SUPPRESSION_SCOPES, HubSuppression


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scope", choices=[*SUPPRESSION_SCOPES, "list"])
    parser.add_argument("name", nargs="?")
    parser.add_argument("--reason", choices=SUPPRESSION_REASONS)
    args = parser.parse_args()

    try:
        async with AdminSessionLocal() as session:
            if args.scope == "list":
                rows = (
                    await session.execute(select(HubSuppression).order_by(HubSuppression.created_at))
                ).scalars().all()
                for row in rows:
                    print(f"{row.created_at:%Y-%m-%d}  {row.scope:8} {row.reason:10} {row.key}")
                print(f"{len(rows)} suppression(s)")
                return 0
            if not args.name or not args.reason:
                parser.error("a name and --reason are required")
            try:
                outcome = await suppression.suppress(
                    session, scope=args.scope, name=args.name, reason=args.reason
                )
            except ValueError as exc:
                print(exc, file=sys.stderr)
                return 2
    finally:
        await admin_engine.dispose()

    for field, value in outcome.items():
        print(f"  {field}: {value}")
    if outcome.get("companies_named"):
        print(
            "  ! companies are named after this person (sole trader?) — suppress "
            "them too: scripts.hub_suppress company \"<name>\" --reason …"
        )
    return 0


if __name__ == "__main__":
    current_tenant_var.set(None)
    sys.exit(asyncio.run(main()))
