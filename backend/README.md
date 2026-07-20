# eligo-tech — backend

AI-native recruitment platform backend. FastAPI + Pydantic v2 + async
SQLAlchemy 2.0. Postgres (+ pgvector) is the production system-of-record, but
the scaffold **runs on SQLite with zero external services**.

## Quickstart

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # add ".[postgres]" for asyncpg + pgvector

# optional: load demo data for the frontend
python -m app.seed

uvicorn app.main:app --reload
```

Then:

- Health:  `GET http://127.0.0.1:8000/api/v1/health` → `{"status":"ok"}`
- Docs:    `http://127.0.0.1:8000/docs`

## Configuration

Copy `.env.example` → `.env`. Everything is prefixed `ELIGO_`. The default
`ELIGO_DATABASE_URL` is async SQLite; point it at
`postgresql+asyncpg://…` to use Postgres.

## Tenant isolation — fail-closed RLS

Tenant isolation is enforced at the **database**, not just in app code. Every
tenant-scoped table has a Row-Level-Security policy keyed on a per-request GUC
(`app.current_tenant`) that the backend sets from the authenticated Clerk org.
The guarantee only holds if the **runtime connection role cannot bypass RLS** —
so the app connects as a dedicated `NOBYPASSRLS` role (`eligo_app`), while DDL
and cross-tenant admin work use a separate owner connection.

Two connection URLs make this work:

| Var | Role | Used for |
|-----|------|----------|
| `ELIGO_DATABASE_URL` | `eligo_app` (NOBYPASSRLS) | all request traffic — RLS always applies |
| `ELIGO_ADMIN_DATABASE_URL` | owner (`postgres`) | migrations, `create_all`, ops scripts |

`ELIGO_ADMIN_DATABASE_URL` falls back to `ELIGO_DATABASE_URL` when unset (single
connection dev / SQLite). With a `NOBYPASSRLS` runtime role, an **un-pinned query
returns zero rows** (fail-closed) instead of every tenant's — regardless of any
app-code mistake.

**One-time provisioning** (run once, from a host that can reach Postgres as the
owner):

```bash
export ELIGO_ADMIN_DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<pw>@…pooler.supabase.com:5432/postgres'
export ELIGO_DB_SSL=true ELIGO_DB_SSL_VERIFY=false
export ELIGO_DB_APP_ROLE=eligo_app
export ELIGO_DB_APP_ROLE_PASSWORD='<generate-a-strong-password>'   # makes eligo_app a LOGIN role
.venv/bin/python -m scripts.apply_rls            # enable RLS + provision the login role
.venv/bin/python -m scripts.apply_rls --status   # confirm rls=on / force=on on every table
```

Then set `ELIGO_DATABASE_URL` to connect **as `eligo_app`** (username
`eligo_app.<ref>` through the Supabase pooler) using that password, and keep
`ELIGO_ADMIN_DATABASE_URL` on `postgres`.

**Verify** — on startup the app logs one of:
- ✅ `RLS enforced: runtime role 'eligo_app' is NOBYPASSRLS (fail-closed).`
- ❌ `SECURITY: runtime DB role 'postgres' has BYPASSRLS …` → still on the owner
  connection; fix `ELIGO_DATABASE_URL`.

> **Legacy mode.** Without `ELIGO_DB_APP_ROLE_PASSWORD`, `eligo_app` stays
> `NOLOGIN` and the app connects as the owner, dropping to it per transaction via
> `SET LOCAL ROLE`. Isolation still holds for every request (all endpoints pin the
> tenant), but an un-pinned query on the owner connection would fail *open*. The
> login-role setup above is what makes the database itself refuse to leak.

## Layout

```
app/
  core/        config, async database, logging
  domain/      candidates, jobs, companies, pipeline, matching, verification
               (+ common: mixins, enums, types)
  agents/      narrow workers that PROPOSE changes (never write directly)
  api/         routes aggregated under /api/v1
```

Each domain package is `models.py` / `schemas.py` / `service.py` / `router.py`.

## Key endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/api/v1/health` | liveness |
| GET/POST | `/api/v1/candidates` | candidate list / create |
| GET/POST | `/api/v1/jobs` | jobs |
| GET/POST | `/api/v1/companies` | companies |
| GET  | `/api/v1/pipeline/board` | Kanban board |
| POST | `/api/v1/pipeline/applications/{id}/status` | state-machine transition |
| POST | `/api/v1/matching/job` | rank candidates for a job (+ Match Receipts) |
| GET  | `/api/v1/matching/pair` | explain one candidate↔job match |
| GET  | `/api/v1/verification/receipts` | append-only receipt ledger |

## Tests

```bash
pytest
```

See [`CLAUDE.md`](./CLAUDE.md) for architecture and the non-negotiable
invariants before contributing.