---
name: add-domain
description: Add a new backend domain to eligo-tech (models, schemas, service, router, migration, RLS, tests) following the layered per-domain convention. Use when creating a new entity such as managers/contacts, notes, activities, or any new table — and when a change needs a migration with Row-Level Security.
tools: Read, Glob, Grep, Bash, Edit, Write
---

# Adding a domain — eligo-tech

`backend/CLAUDE.md` §3 and §5 are the contract; this is the executable version.
Before starting, decide **where the data belongs** using the `architecture-review`
skill's classification table. Getting that wrong is expensive to undo.

---

## The per-domain file convention

`backend/app/domain/<name>/` contains exactly:

| file | responsibility |
|---|---|
| `models.py` | SQLAlchemy ORM. Compose `IDMixin`, `TenantMixin`, `TimestampMixin`. |
| `schemas.py` | Pydantic v2 wire contracts. `ConfigDict(from_attributes=True)` on read models. |
| `service.py` | Business logic. **No FastAPI imports.** Takes `tenant_id` explicitly. |
| `router.py` | Thin `APIRouter`. Validates input, calls the service, nothing else. |

A router never contains business logic; a service never touches
`Request`/`Response`. Cross-domain enums go in `domain/common/enums.py`, portable
column types in `domain/common/types.py` (`JSONDict`/`JSONList` — JSONB on
Postgres, TEXT on SQLite; never branch on the dialect in domain code).

## Steps

1. Create the four files above.
2. **Every core row carries `tenant_id`** via `TenantMixin`, and every query
   filters on it. The one documented exception is the shared hub corpus — do not
   add a second without updating `ARCHITECTURE.md`.
3. Import the new `models` module in `app/domain/registry.py`. This is
   load-bearing, not cosmetic: `create_all` and Alembic autogenerate both rely
   on it, and a foreign key to a table that was never imported raises
   `NoReferencedTableError` on the first flush.
4. `include_router(...)` in `app/api/routes.py`.
5. Write the migration (below).
6. Tests. New behaviour without a test does not land.

## The migration

```bash
cd backend && .venv/bin/python -m alembic revision -m "create <name>"
```

Requirements, all of which have real precedent in `migrations/versions/`:

- **Idempotent w.r.t. `create_all`** — skip if the table already exists
  (`0004` shows the shape). Fresh databases are bootstrapped by `create_all`;
  existing ones are evolved by Alembic, and both must be safe.
- **RLS for every tenant-scoped table.** Copy the policy from `0003`/`0005`:
  ```sql
  ALTER TABLE t ENABLE ROW LEVEL SECURITY;
  ALTER TABLE t FORCE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation ON t
    USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
    WITH CHECK (…same…);
  ```
  Postgres-only; return early on other dialects. `NULLIF(...)::uuid` makes an
  unset GUC resolve to NULL → zero rows → **fail-closed**.
- **Guard destructive steps.** `0008` refuses to run if the tables it reshapes
  hold rows, because the operation would silently merge data. If a migration can
  lose or merge data, it must check first and raise with an explanation.
- **Verify on both dialects** — SQLite cannot ALTER constraints at all, so
  prefer drop-and-recreate for empty tables over a pile of dialect-specific ops.

```bash
rm -f /tmp/mig.db
ELIGO_DATABASE_URL="sqlite+aiosqlite:////tmp/mig.db" \
ELIGO_ADMIN_DATABASE_URL="sqlite+aiosqlite:////tmp/mig.db" \
ELIGO_AUTH_ENABLED=false ELIGO_DB_SSL=false \
  .venv/bin/python -m alembic upgrade head
```

## If the domain stores personal data

A `manager`, a `candidate`, any natural person:

- It is **tenant-scoped, never shared corpus** (`architecture-review` RULE 2).
- Carry provenance from the first migration, not as a retrofit: `source`,
  `ConfidenceSource`, and the source detail. Retrofitting provenance onto rows
  that already exist is not possible — you cannot recover where they came from.
- A value collected from a third party or public page owes a **GDPR Art. 14**
  notification. `agents/enrichment.py` already raises that flag; wire the new
  domain into the same path rather than inventing a second one.
- Plan for erasure: a `DELETE` is not enough anywhere data is re-ingested.

## If agents will write to it

They do not write. They emit `ProposedChange`s with `entity_type="<name>"` and
go through `verification.verify_and_commit`, which records a receipt. Give the
agent deterministic `postconditions()` — format, deliverability, allowed
provenance — that any write must pass.

## Definition of done

```bash
cd backend && .venv/bin/python -m pytest -q     # all green
.venv/bin/python -m alembic upgrade head        # clean from scratch
cd ../frontend && npx tsc --noEmit && npm run build
```

Plus: the new table appears in `registry.py`, the router in `routes.py`, the
migration carries an RLS policy, and the PR says which layer and domain the
change belongs to (`backend/CLAUDE.md` §0).
