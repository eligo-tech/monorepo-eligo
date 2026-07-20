"""Apply (or verify) Row-Level Security on every tenant-scoped table.

Idempotent — safe to run repeatedly. Enforces at the DATABASE layer what the app
already does at the query layer: a row is visible/writable only when its
`tenant_id` equals the per-transaction `app.current_tenant` GUC the backend sets
from the authenticated org. FORCE makes the policy apply even to the table owner
(the role the app connects as). An unset GUC → NULL → zero rows (fail-closed).

    .venv/bin/python -m scripts.apply_rls          # apply
    .venv/bin/python -m scripts.apply_rls --status # just report

Postgres only. Deploys get the same via Alembic (0003 + 0005).
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.core.config import settings
from app.core.database import admin_engine, current_tenant_var
from app.domain import registry  # noqa: F401 — register all models

# Every table carrying a tenant_id.
TABLES = [
    "candidates", "jobs", "companies", "applications",
    "receipts", "enrichment_records", "candidate_documents", "match_receipts",
]
PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


async def _status() -> None:
    async with admin_engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT relname, relrowsecurity, relforcerowsecurity "
            "FROM pg_class WHERE relname = ANY(:t) ORDER BY relname"
        ), {"t": TABLES})).all()
    for name, enabled, forced in rows:
        print(f"  {name:22} rls={'on' if enabled else 'OFF':3} force={'on' if forced else 'OFF'}")


async def _ensure_app_role(conn) -> None:
    """Provision the NOBYPASSRLS app role RLS is enforced through, and grant it
    DML. Idempotent.

    Two operating modes, selected by whether ``ELIGO_DB_APP_ROLE_PASSWORD`` is set:

    * password set → the role is made a **LOGIN** role so the app can connect
      *as* it (`ELIGO_DATABASE_URL`). The connection then can never bypass RLS →
      an un-pinned query returns zero rows (fail-closed). This is preferred.
    * password unset → the role is left **NOLOGIN**; the app connects as the
      owner and drops to it per transaction via `SET LOCAL ROLE` (legacy mode,
      only fail-closed for tenant-pinned transactions).
    """
    role = settings.db_app_role
    if not role or not role.replace("_", "").isalnum():
        print("! ELIGO_DB_APP_ROLE unset — RLS will NOT be enforced for the app "
              "(the connection role bypasses RLS). Set it to a NOBYPASSRLS role.")
        return
    await conn.execute(text(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') "
        f"THEN CREATE ROLE {role} NOLOGIN NOBYPASSRLS; END IF; END $$;"
    ))
    # Always pin the security-critical attribute, even for a pre-existing role.
    await conn.execute(text(f"ALTER ROLE {role} NOBYPASSRLS"))

    pw = settings.db_app_role_password
    if pw:
        # Single-quote-escape the operator-supplied password for the DDL literal
        # (role name is already validated as an identifier above).
        pw_literal = "'" + pw.replace("'", "''") + "'"
        await conn.execute(text(f"ALTER ROLE {role} WITH LOGIN PASSWORD {pw_literal}"))
        login = "LOGIN — point ELIGO_DATABASE_URL at this role (fail-closed)"
    else:
        login = "NOLOGIN — legacy SET-LOCAL-ROLE mode (set ELIGO_DB_APP_ROLE_PASSWORD to harden)"

    await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
    await conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"))
    await conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"))
    await conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"))
    await conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}"))
    await conn.execute(text(f"GRANT {role} TO CURRENT_USER"))  # so the owner can SET ROLE to it (legacy mode)
    print(f"  ✓ app role {role} ready (NOBYPASSRLS) + DML grants · {login}")


async def main() -> None:
    if not settings.is_postgres:
        sys.exit("RLS is Postgres-only; current DB is not Postgres.")
    if "--status" in sys.argv:
        await _status()
        return

    async with admin_engine.begin() as conn:
        await _ensure_app_role(conn)
        for t in TABLES:
            await conn.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
            await conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {t}"))
            await conn.execute(text(
                f"CREATE POLICY tenant_isolation ON {t} "
                f"USING ({PREDICATE}) WITH CHECK ({PREDICATE})"
            ))
            print(f"  ✓ RLS enforced on {t}")
    print("\nRow-Level Security is ON. Every query must set app.current_tenant.")
    await _status()


if __name__ == "__main__":
    # Belt: never leave a stray tenant pinned in this admin process.
    current_tenant_var.set(None)
    asyncio.run(main())
