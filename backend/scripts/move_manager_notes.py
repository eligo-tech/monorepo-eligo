"""Move imported manager notes from one workspace to the one they belong to.

The aiFind import was run twice by the old operator script — once into a
test workspace and once into the customer's. The second run brought the
managers, companies, candidates and jobs, and did not bring the notes. So
646 managers in the customer's workspace have an empty history, while a
near-identical 648 in the test workspace carry all 512.

This moves the notes to the managers they are actually about. It is a
correction of a mis-ingestion, not a disclosure: every row moved was the
destination tenant's own data from the start, and it ends up in exactly one
workspace instead of the wrong one.

    # what would move
    .venv/bin/python -m scripts.move_manager_notes <source> <dest>

    # do it
    .venv/bin/python -m scripts.move_manager_notes <source> <dest> --apply

Either argument may be a tenant uuid, a Clerk organization id, or a name.

## What matches, and what is refused

Managers are paired on `(external_source, external_id)` — the identity the
source system assigned, which survived both imports. Nothing is matched on
a name: two people called "M. Weber" at the same client are one typo away
from a note landing on the wrong person's record, and a note attributed to
the wrong manager is worse than a missing one.

A note is refused rather than guessed when:

  * its manager has no twin in the destination (no `external_id`, or the
    destination never got that person),
  * it carries a `candidate_id` or `job_id`. Those point at rows in the
    SOURCE tenant. Copying the id across would leave a foreign key reaching
    into another workspace's data — the exact thing tenant isolation
    exists to prevent — and remapping them is a different job with a
    different matching key. These are in practice the notes somebody typed
    in the app, not the imported ones.

Refusals are printed individually. A summary count would make it easy to
not read them.

## Re-running it

Notes are keyed on `(external_source, external_id)`. A note already present
in the destination under that key is skipped, so a second run moves nothing
and reports zero. That matters because the first thing anyone does after a
partial failure is run it again.

## The delete

"Move" means the source rows go away: leaving them would keep one
customer's personal data in a second workspace, which is the problem this
is fixing, not a side effect of it. Insert and delete run in ONE
transaction — a crash between them would otherwise duplicate the history or
destroy it.

Before deleting, every moved row is written to a timestamped JSON file in
the working directory. The transaction protects against a crash; the file
protects against the move being the wrong idea, which no amount of
transactional care will tell you in advance.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
import uuid

from sqlalchemy import select

from app.core.database import AdminSessionLocal as SessionLocal

# Every domain, not just the two tables this touches: `managers.company_id`
# is a foreign key, and SQLAlchemy resolves it against whatever is registered
# on `Base.metadata` at mapper-configuration time. Importing the two models
# alone gets as far as writing the backup file and then dies on
# NoReferencedTableError — after the side effect, before the work.
from app.domain import registry  # noqa: F401
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.tenants.models import Tenant


def _usage() -> None:
    print(__doc__)
    raise SystemExit(2)


async def _resolve(session, target: str) -> Tenant:
    """Find a workspace by uuid, Clerk org id, or name."""
    rows = (await session.execute(select(Tenant))).scalars().all()
    try:
        wanted = uuid.UUID(target)
        found = next((t for t in rows if t.id == wanted), None)
    except ValueError:
        found = next(
            (t for t in rows if t.clerk_org_id == target or t.name == target), None
        )
    if found is None:
        print(f"no workspace matches {target!r}. Known:\n")
        for t in rows:
            print(f"  {t.clerk_org_id or '—':34} {t.name or '—':42} tenant={t.id}")
        raise SystemExit(1)
    return found


def _key(manager: Manager) -> tuple[str | None, str] | None:
    """The identity the source system gave this person, or None if it has none."""
    if not manager.external_id:
        return None
    return (manager.external_source, manager.external_id)


async def _move(source: str, dest: str, apply: bool) -> None:
    async with SessionLocal() as session:
        src = await _resolve(session, source)
        dst = await _resolve(session, dest)

        if src.id == dst.id:
            print("source and destination are the same workspace. Nothing to do.")
            raise SystemExit(1)

        print(f"source      {src.name}  ({src.id})")
        print(f"destination {dst.name}  ({dst.id})\n")

        src_managers = (
            await session.execute(select(Manager).where(Manager.tenant_id == src.id))
        ).scalars().all()
        dst_managers = (
            await session.execute(select(Manager).where(Manager.tenant_id == dst.id))
        ).scalars().all()

        # Build the destination index, and refuse to run at all if the key is
        # not unique there — a fan-out would silently attach each note to
        # whichever twin happened to be last.
        index: dict[tuple[str | None, str], Manager] = {}
        for m in dst_managers:
            k = _key(m)
            if k is None:
                continue
            if k in index:
                print(
                    f"ABORT: external key {k} names two managers in {dst.name}: "
                    f"{index[k].full_name!r} and {m.full_name!r}. "
                    "Notes cannot be placed unambiguously."
                )
                raise SystemExit(1)
            index[k] = m

        by_id = {m.id: m for m in src_managers}

        notes = (
            await session.execute(
                select(ManagerInteraction)
                .where(ManagerInteraction.tenant_id == src.id)
                .order_by(ManagerInteraction.occurred_at)
            )
        ).scalars().all()

        dst_notes = (
            await session.execute(
                select(ManagerInteraction).where(ManagerInteraction.tenant_id == dst.id)
            )
        ).scalars().all()
        before_dst = len(dst_notes)
        existing = {
            (n.external_source, n.external_id) for n in dst_notes if n.external_id
        }

        movable: list[tuple[ManagerInteraction, Manager]] = []
        refused: list[tuple[ManagerInteraction, str]] = []
        skipped = 0

        for n in notes:
            if n.candidate_id is not None or n.job_id is not None:
                which = " and ".join(
                    w
                    for w, v in (("candidate", n.candidate_id), ("job", n.job_id))
                    if v is not None
                )
                refused.append((n, f"carries a {which} id into another workspace"))
                continue
            if n.manager_id is None:
                refused.append((n, "no manager on the note"))
                continue
            owner = by_id.get(n.manager_id)
            if owner is None:
                refused.append((n, "manager not in the source workspace"))
                continue
            k = _key(owner)
            if k is None:
                refused.append((n, f"{owner.full_name!r} has no external id"))
                continue
            twin = index.get(k)
            if twin is None:
                refused.append((n, f"{owner.full_name!r} has no twin in {dst.name}"))
                continue
            if n.external_id and (n.external_source, n.external_id) in existing:
                skipped += 1
                continue
            movable.append((n, twin))

        print(f"notes in {src.name}: {len(notes)}")
        print(f"  will move        {len(movable)}")
        print(f"  already there    {skipped}")
        print(f"  refused          {len(refused)}")

        if refused:
            print("\nrefused, one line each — these stay where they are:")
            for n, why in refused:
                when = n.occurred_at.date() if n.occurred_at else "—"
                head = (n.summary or "").replace("\n", " ")[:48]
                print(f"  {when}  {n.interaction_type:<22} {why}")
                if head:
                    print(f"              {head!r}")

        if not movable:
            print("\nnothing to move.")
            return

        kinds: dict[str, int] = {}
        for n, _ in movable:
            kinds[n.interaction_type] = kinds.get(n.interaction_type, 0) + 1
        print("\nby kind:")
        for k2, c in sorted(kinds.items(), key=lambda kv: -kv[1]):
            print(f"  {k2:<26} {c}")

        touched = {t.id for _, t in movable}
        print(f"\nmanagers in {dst.name} that gain a history: {len(touched)}")

        if not apply:
            print("\nDRY RUN — nothing written. Re-run with --apply.")
            return

        # The rows as they are NOW, captured before the delete detaches them.
        # Serialised here but written to disk only once the move is staged and
        # counted: a backup file written ahead of a step that then fails is a
        # pile of someone's personal data left on disk for nothing.
        snapshot = [
            {
                "id": str(n.id),
                "tenant_id": str(n.tenant_id),
                "manager_id": str(n.manager_id),
                "interaction_type": n.interaction_type,
                "occurred_at": n.occurred_at.isoformat() if n.occurred_at else None,
                "summary": n.summary,
                "actor_user_id": n.actor_user_id,
                "actor_name": n.actor_name,
                "external_id": n.external_id,
                "external_source": n.external_source,
            }
            for n, _ in movable
        ]

        # One transaction: a crash between the insert and the delete would
        # either duplicate the whole history or lose it.
        for n, twin in movable:
            session.add(
                ManagerInteraction(
                    tenant_id=dst.id,
                    manager_id=twin.id,
                    candidate_id=None,
                    job_id=None,
                    interaction_type=n.interaction_type,
                    occurred_at=n.occurred_at,
                    summary=n.summary,
                    actor_user_id=n.actor_user_id,
                    actor_name=n.actor_name,
                    external_id=n.external_id,
                    external_source=n.external_source,
                )
            )
        for n, _ in movable:
            await session.delete(n)

        await session.flush()

        after_src = len(
            (
                await session.execute(
                    select(ManagerInteraction).where(
                        ManagerInteraction.tenant_id == src.id
                    )
                )
            ).scalars().all()
        )
        after_dst = len(
            (
                await session.execute(
                    select(ManagerInteraction).where(
                        ManagerInteraction.tenant_id == dst.id
                    )
                )
            ).scalars().all()
        )
        expect_src = len(notes) - len(movable)
        expect_dst = before_dst + len(movable)

        # Counted inside the transaction, so a mismatch rolls the move back
        # rather than printing a number nobody will re-check afterwards.
        for label, got, want in (
            (src.name, after_src, expect_src),
            (dst.name, after_dst, expect_dst),
        ):
            if got != want:
                await session.rollback()
                print(f"ABORT: {label} has {got}, expected {want}. Rolled back.")
                raise SystemExit(1)

        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = f"manager_notes_{src.name}_{stamp}.json"
        with open(backup, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        print(f"\nwrote {backup} ({len(snapshot)} rows) — the source rows as they were")

        await session.commit()
        print(f"\nmoved {len(movable)} notes")
        print(f"  {src.name:<28} {len(notes)} → {after_src}")
        print(f"  {dst.name:<28} {before_dst} → {after_dst}")
        print(f"\nbackup of the moved rows: {backup}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) != 2 or flags - {"--apply"}:
        _usage()
    asyncio.run(_move(args[0], args[1], apply="--apply" in flags))


if __name__ == "__main__":
    main()
