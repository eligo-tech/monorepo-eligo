#!/usr/bin/env python
"""Bring both candidate scores in line with the record.

Needed once, because `verification_score` was only ever recomputed by a
manual edit: on the live workspace 446 of 447 candidates sat at 0.0 while 46
of them had a CV and a committed record per extracted field. After this,
every write path keeps both current (see `candidates.recompute_scores`).

    python -m scripts.recompute_candidate_scores --tenant <uuid> [--dry-run]

Reports the distribution it produced, because the useful output is not "447
rows updated" but "46 records carry evidence, 401 do not" — which is the
state of the pool, and the thing worth looking at.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal, current_tenant_var
from app.domain.candidates import service as candidates_service
from app.domain.candidates.models import Candidate
from app.domain.registry import *  # noqa: F401,F403 — register every table


async def run(tenant_id: uuid.UUID, *, dry_run: bool) -> dict:
    current_tenant_var.set(str(tenant_id))
    buckets: Counter[str] = Counter()
    changed = 0
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Candidate).where(Candidate.tenant_id == tenant_id)
            )
        ).scalars().all()
        for row in rows:
            before = (row.verification_score, row.completeness_score)
            await candidates_service.recompute_scores(
                session, tenant_id=tenant_id, candidate=row
            )
            after = (row.verification_score, row.completeness_score)
            changed += int(before != after)
            buckets["mit Beleg" if row.verification_score > 0 else "ohne Beleg"] += 1
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return {"kandidaten": len(rows), "geändert": changed, **buckets}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", type=uuid.UUID, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(asyncio.run(run(args.tenant, dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
