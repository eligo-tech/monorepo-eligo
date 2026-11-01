#!/usr/bin/env python
"""Fail when the database and the models disagree.

    python -m scripts.schema_drift

Compares the database named by `ALEMBIC_DATABASE_URL` with the ORM
metadata, using Alembic's autogenerate comparison. Exit 0 on no difference,
1 with every difference printed.

Why it exists: production is built by `alembic upgrade head`, a fresh database
by `create_all`. Nothing checked that the two produce the same schema, and on
2026-11-01 they did not — `JSONDict` made `json` columns where the migrations
had made `jsonb`. The CI job "Backend · upgrade from main" runs this after
upgrading main's schema with the PR's migrations, so it catches a PR whose
migrations and model changes disagree. It cannot see drift already on main:
that schema is built by `create_all`, from the models. The json/jsonb drift
was found by running it on a schema the migrations had built.

Refuses without `ALEMBIC_DATABASE_URL`: on a developer machine the default
target is production (see migrations/env.py).
"""

from __future__ import annotations

import asyncio
import os
import pprint
import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import Base
from app.domain import registry  # noqa: F401 — imports every model onto Base.metadata


def _diff(sync_conn) -> list:  # noqa: ANN001
    ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
    return compare_metadata(ctx, Base.metadata)


async def main() -> int:
    url = os.environ.get("ALEMBIC_DATABASE_URL")
    if not url:
        print("refusing: set ALEMBIC_DATABASE_URL to the database to compare", file=sys.stderr)
        return 2
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
