#!/usr/bin/env python
"""Fail when the database and the models disagree.

    python -m scripts.schema_drift

Compares the connected database (`settings.admin_url`, or
`ALEMBIC_DATABASE_URL` when set — the same target `alembic` uses) with the
ORM metadata, using Alembic's autogenerate comparison. Exit 0 on no
difference, 1 with every difference printed.

Why it exists: production is built by `alembic upgrade head`, a fresh database
by `create_all`. Nothing checked that the two produce the same schema, and on
2026-11-01 they did not — `JSONDict` made `json` columns where the migrations
had made `jsonb`. The CI job "Backend · upgrade from main" runs this against
a database that was migrated, which is the shape production has.
"""

from __future__ import annotations

import asyncio
import os
import pprint
import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.domain import registry  # noqa: F401 — imports every model onto Base.metadata


def _diff(sync_conn) -> list:  # noqa: ANN001
    ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
    return compare_metadata(ctx, Base.metadata)


async def main() -> int:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or settings.admin_url
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            diff = await conn.run_sync(_diff)
    finally:
        await engine.dispose()
    if not diff:
        print("schema matches the models")
        return 0
    print(f"{len(diff)} difference(s) between the database and the models:")
    pprint.pprint(diff, width=160)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
