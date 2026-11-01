#!/usr/bin/env python
"""Put one row in every table, so a migration meets data.

    python -m scripts.fill_every_table

Most migrations that break in production only break when rows exist: a
NOT NULL column added without a default, a backfill that assumes a shape, a
unique index over duplicates. An empty CI database passes all of them.

The schema is READ FROM THE DATABASE (reflection), not from the models. The CI
job runs this against the schema main had, using the PR's code — the models
already describe the new schema, the database still has the old one.

Values are dummies chosen per column type; foreign keys point at the row
inserted into the parent table. Throwaway databases only: it refuses to run
unless `ALEMBIC_DATABASE_URL` names the target, the same guard `alembic`
uses (migrations/env.py) against migrating production by accident.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import uuid

from sqlalchemy import MetaData, insert, types
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine

SKIP = {"alembic_version"}
_UNKNOWN = object()


def _value(table: str, col):  # noqa: ANN001, ANN202
    t = col.type
    if isinstance(t, postgresql.UUID) or isinstance(t, types.Uuid):
        return uuid.uuid4()
    if isinstance(t, (postgresql.JSON, postgresql.JSONB, types.JSON)):
        return {}
    if isinstance(t, postgresql.ARRAY):
        return []
    if isinstance(t, types.Enum):
        return t.enums[0]
    if isinstance(t, types.Boolean):
        return False
    if isinstance(t, types.DateTime):
        return dt.datetime.now(dt.UTC)
    if isinstance(t, types.Date):
        return dt.date.today()
    if isinstance(t, types.Interval):
        return dt.timedelta(0)
    if isinstance(t, (types.Integer, types.Numeric, types.Float)):
        return 1
    if isinstance(t, types.LargeBinary):
        return b"x"
    if isinstance(t, types.String):  # String, Text, VARCHAR(n)
        text = f"fill-{table}-{col.name}"
        return text[: t.length] if t.length else text
    return _UNKNOWN


def _fill(sync_conn) -> list[str]:  # noqa: ANN001
    meta = MetaData()
    meta.reflect(bind=sync_conn)
    inserted: dict[str, dict] = {}
    done = []
    for table in meta.sorted_tables:
        if table.name in SKIP:
            continue
        row: dict = {}
        for col in table.columns:
            fks = list(col.foreign_keys)
            if fks:
                parent = fks[0].column
                parent_row = inserted.get(parent.table.name)
                if parent_row is not None and parent.name in parent_row:
                    row[col.name] = parent_row[parent.name]
                elif not col.nullable:
                    raise RuntimeError(f"{table.name}.{col.name}: parent {parent.table.name} has no row")
                continue
            if col.server_default is not None or col.identity is not None:
                continue  # the database fills it — that default is part of what we test
            if col.autoincrement is True and col.primary_key:
                continue
            value = _value(table.name, col)
            if value is _UNKNOWN:
                if col.nullable:
                    continue  # NULL — still a row for the migration to meet
                raise TypeError(
                    f"{table.name}.{col.name}: fill_every_table has no dummy value for "
                    f"{col.type!r}. Add one in scripts/fill_every_table.py:_value."
                )
            row[col.name] = value
        result = sync_conn.execute(insert(table).values(**row).returning(*table.columns))
        inserted[table.name] = dict(result.mappings().one())
        done.append(table.name)
    return done


async def main() -> int:
    url = os.environ.get("ALEMBIC_DATABASE_URL")
    if not url:
        print("refusing: set ALEMBIC_DATABASE_URL to the throwaway database to fill", file=sys.stderr)
        return 2
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            done = await conn.run_sync(_fill)
    finally:
        await engine.dispose()
    print(f"one row in each of {len(done)} tables")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
