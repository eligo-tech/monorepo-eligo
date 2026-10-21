"""Rewrite stored interaction kinds into the ELI-9 vocabulary. Dry-run first.

Reading normalises already (`ManagerInteractionRead`), so the product is
correct without ever running this — what it buys is a column you can `GROUP
BY` and a database that says one thing once.

**It is not an Alembic migration on purpose.** Migrations run unattended on
every deploy, and this rewrites rows of real notes about real people on a
mapping that was read off a sample. The numbers should be looked at by
somebody before the UPDATE runs, so the default is a report and nothing else:

    .venv/bin/python -m scripts.normalise_interaction_types            # report
    .venv/bin/python -m scripts.normalise_interaction_types --apply    # rewrite

Kinds with no mapping — "Job Spec", "Client Canvas", "Candidate
Qualification" — are listed and left exactly as they are. Folding them into
`note` would destroy a distinction those rows still carry, and nobody has
said what they should become.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter

from sqlalchemy import func, select, update

from app.core.database import AdminSessionLocal as SessionLocal
from app.domain.common.enums import normalise_interaction_type
from app.domain.managers.models import ManagerInteraction


async def _distribution() -> Counter[str]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    ManagerInteraction.interaction_type,
                    func.count(ManagerInteraction.id),
                ).group_by(ManagerInteraction.interaction_type)
            )
        ).all()
    return Counter({kind: count for kind, count in rows})


async def main() -> None:
    apply = "--apply" in sys.argv
    stored = await _distribution()
    if not stored:
        print("no interactions in this database.")
        return

    changes: dict[str, tuple[str, int]] = {}
    unchanged: list[tuple[str, int]] = []
    unmapped: list[tuple[str, int]] = []

    for kind, count in sorted(stored.items(), key=lambda kv: -kv[1]):
        canonical = normalise_interaction_type(kind)
        if canonical == kind:
            # Either already canonical, or a kind nothing knows about. The
            # difference matters to a reader, so say which.
            (unchanged if kind.islower() and " " not in kind else unmapped).append(
                (kind, count)
            )
        else:
            changes[kind] = (canonical, count)

    total = sum(stored.values())
    print(f"{total} interaction(s) in {len(stored)} distinct kind(s)\n")

    if changes:
        print("WOULD REWRITE" if not apply else "REWRITING")
        for kind, (canonical, count) in sorted(
            changes.items(), key=lambda kv: -kv[1][1]
        ):
            print(f"  {kind:28} → {canonical:18} {count:>5}")
    if unchanged:
        print("\nalready canonical")
        for kind, count in unchanged:
            print(f"  {kind:28}   {'':18} {count:>5}")
    if unmapped:
        print("\nNO MAPPING — left exactly as they are")
        for kind, count in unmapped:
            print(f"  {kind:28}   {'':18} {count:>5}")
        print(
            "\n  These are on neither list in ELI-9. Decide what they mean "
            "before\n  anything folds them into another kind."
        )

    if not apply:
        print("\n(dry run — nothing was written. Re-run with --apply.)")
        return
    if not changes:
        print("\nnothing to rewrite.")
        return

    async with SessionLocal() as session:
        for kind, (canonical, _) in changes.items():
            await session.execute(
                update(ManagerInteraction)
                .where(ManagerInteraction.interaction_type == kind)
                .values(interaction_type=canonical)
            )
        await session.commit()
    print(f"\nrewrote {sum(c for _, c in changes.values())} row(s).")


if __name__ == "__main__":
    asyncio.run(main())
