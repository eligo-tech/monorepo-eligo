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