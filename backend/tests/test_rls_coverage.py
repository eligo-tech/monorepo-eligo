"""Every tenant-scoped table must be isolated by the DATABASE, not just by code.

`test_tenant_isolation.py` proves the query layer. This proves the backstop
underneath it: that a table carrying a `tenant_id` also carries a Postgres
policy, so a query that forgets its `WHERE` returns nothing instead of
everything.

Neither check can run against a real Postgres in CI (the suite is SQLite), so
both are static — and each catches a different way of getting it wrong:

* `apply_rls.TABLES` must equal the set of `TenantMixin` tables. It is derived
  now, so this mostly guards against someone hardcoding it again. It was
  hardcoded, and it had drifted to eight entries while the models had grown to
  nineteen.
* Every `TenantMixin` table must be named in a migration that enables RLS. This
  is the one that catches a new domain whose migration created the table and
  forgot the policy — the deployed path, since the Dockerfile runs
  `alembic upgrade head` on every deploy.

What the second check cannot prove: that the policy is *correct*, or that it
was applied to a database somebody bootstrapped by hand. Only a run against a
real Postgres shows that — `python -m scripts.apply_rls --status`.
"""

from __future__ import annotations

import ast
import pathlib
import re

from app.core.database import Base
from app.domain.common.mixins import TenantMixin

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


def _tenant_tables() -> set[str]:
    from app.domain import registry  # noqa: F401 — registers every model

    return {
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantMixin)
    }


def _tables_named_in_rls_migrations() -> set[str]:
    """Table names appearing in any migration that enables RLS.

    Read as literals via `ast` rather than by regex over SQL, because the
    statements are f-strings built over a loop variable
    (`f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"`) — the table name is
    never adjacent to the SQL in the source. So the unit is the FILE: a
    migration that enables RLS at all, and names this table somewhere, is
    taken to cover it.

    That is deliberately loose in one direction (a table merely mentioned in
    an RLS migration counts) and exact in the one that matters: a migration
    that creates a table and never mentions row-level security does not
    count, which is the mistake this exists to catch.
    """
    found: set[str] = set()
    for path in _MIGRATIONS.glob("[0-9]*.py"):
        source = path.read_text()
        if "ENABLE ROW LEVEL SECURITY" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                if _IDENTIFIER.match(value):
                    found.add(value)
    return found


def test_apply_rls_covers_every_tenant_table() -> None:
    """The hardening script must not be able to fall behind the models again."""
    from scripts.apply_rls import TABLES

    assert set(TABLES) == _tenant_tables()


def test_every_tenant_table_has_rls_in_a_migration() -> None:
    """A new domain cannot ship a tenant table with no database-level policy."""
    missing = sorted(_tenant_tables() - _tables_named_in_rls_migrations())
    assert not missing, (
        "these tables carry a tenant_id but no migration enables row-level "
        f"security for them: {missing}. Add it to the table's own migration "
        "(see 0019 or 0037 for the shape) — `create_all` does not install "
        "policies, so without it the table is readable across tenants by any "
        "query that forgets its WHERE."
    )


def test_the_shared_corpus_is_still_excluded() -> None:
    """The three corpus tables are shared ON PURPOSE (ARCHITECTURE.md RULE 2).

    If one of them ever acquires a `tenant_id`, the check above would start
    demanding a policy for it — and the right response is to remove the
    column, not to add the policy. Stating it here means the next person meets
    the rule instead of the symptom.
    """
    assert _tenant_tables().isdisjoint(
        {"hub_companies", "hub_job_postings", "hub_observations"}
    )
