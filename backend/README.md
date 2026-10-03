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

### Two settings a production deployment must get right

| variable | why it matters |
|---|---|
| `ELIGO_AUTH_ENABLED=true` | With auth off, every anonymous request is served as the **default tenant** — real data, read and write, to whoever asks. The app now **refuses to start** in that configuration against Postgres (`ELIGO_ALLOW_INSECURE_NO_AUTH=true` overrides it for a local database you own). |
| `ELIGO_SECRET_KEY` | Fernet key encrypting the credentials workspaces store for their own sources. Unset means no workspace can connect its ATS at all — storing a password in the clear is not the fallback. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Rotating it invalidates every stored credential, and each workspace is told so in plain words. |

## Onboarding a workspace's own data

Two doors, and the first needs no configuration at all.

**A file** (`Einstellungen · Daten übernehmen`) — CSV or .xlsx exported from
whatever the customer used before. The server reads the file (semicolons,
cp1252, a title row above the table and duplicate headers are all handled),
guesses what each column means from its header, and shows **what importing
would do** — created, updated, skipped and why — before anything is written.
The recruiter corrects the mapping if a guess is wrong, then imports.
Candidates, companies, contacts and mandates; re-running the same file
updates rather than duplicates, which is what makes a messy first import
survivable. `POST /imports/preview` and `/imports/commit`, both tenant-scoped
and both in-request — there is no outbound call and no credential involved.

**An ATS account**, for a system that stays in use. A customer connects it
themselves under **Einstellungen · Verbundene Systeme**:
username and password, encrypted on arrival and never returned by the API.
Pressing *Import anfordern* writes a request; it does not import.

The import is performed by the scheduled job — `Workspace · imports`
(`.github/workflows/tenant-imports.yml`, nightly at 05:40, or by hand), which
calls the machine-only endpoint:

```bash
ELIGO_API_BASE=https://…/api/v1 ELIGO_INGEST_TOKEN=… \
  python -m scripts.tenant_imports --limit 3 [--no-details]
```

Why the split: an aiFind import is hundreds of outbound calls, which gives a
request no retry and no backpressure and makes a timeout indistinguishable
from a failure; collection stays a scheduled, logged activity (GDPR Art. 30);
and a password is decrypted only in the job process, never in a request a
recruiter can reach. The endpoint takes the machine token only — a valid Clerk
session gets 401, and `tests/test_operator_endpoints.py` attacks it to prove it.

The old path still works for a one-off, with the credential in the operator's
environment: `python -m scripts.aifind_import --tenant <uuid>`.

## Who is acting, and what they may do

Identity comes from the Clerk token, never from the client. `get_current_actor`
returns the workspace, the user, the name a receipt should show and the role;
`get_current_tenant` is now a thin read of the same thing, so every existing
caller is unchanged.

| role | mapped from | may |
|---|---|---|
| `admin` | Clerk `org:admin` / `org:owner` | everything, plus the Einstellungen: connect or disconnect a data source, request an ATS import, commit a file import |
| `recruiter` | everything else, **and a token with no role claim** | the whole day job — candidates, mandates, processes, assessments, Markt, documents, import *preview* |

Least privilege when the role is unknown, and the UI says so: the command bar
shows `Admin ?` / `Recruiter ?` when the token carried no role, so a locked
panel is explicable rather than mysterious. With `ELIGO_AUTH_ENABLED=false`
the demo actor is an admin, so a local stack is never locked out of itself.

**Names in receipts need one Clerk setting.** A default session token carries
`sub` and little else, so a receipt may read `user_3Gj…`. Add `name` (or
`email`) to the session-token template in the Clerk dashboard and the ledger
starts showing people.

Every verified change is readable per record:
`GET /verification/history/{entity_type}/{entity_id}` — the same ledger the
receipts guarantee, surfaced in the candidate drawer and the mandate
workspace as **Änderungsverlauf**.

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