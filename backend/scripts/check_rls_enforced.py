#!/usr/bin/env python
"""CI gate: every tenant table is policed, and the runtime role cannot bypass it.

    python -m scripts.check_rls_enforced

The same audit as the startup guard (`assert_runtime_rls_enforced`), but
strict. The startup guard treats "I could not check" as a warning on
purpose — a transient fault must not take production down. In CI that
leniency made the gate unable to fail: with a role that could not log in, it
logged a warning and the step printed "policed" (reproduced 2026-11-01).
Here, not being able to check is a failure.

Connects with `ELIGO_DATABASE_URL`, which must be the runtime (app) role.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.core.database import _ROLE_BYPASS_QUERY, _TENANT_TABLE_AUDIT, engine, isolation_problems


async def main() -> int:
    try:
        async with engine.connect() as conn:
            user, bypasses = (await conn.execute(text(_ROLE_BYPASS_QUERY))).one()
            tables = (await conn.execute(text(_TENANT_TABLE_AUDIT))).all()
    except Exception as exc:  # noqa: BLE001 — any failure to check is a failed check
        print(f"could not check RLS: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    if not tables:
        print("no tenant tables found — wrong database?", file=sys.stderr)
        return 1
    problems = isolation_problems(user, bypasses, tables)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        return 1
    print(f"role {user!r} is NOBYPASSRLS and all {len(tables)} tenant tables are policed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
