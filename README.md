# eligo-tech

[![CI](https://github.com/eligo-tech/monorepo-eligo/actions/workflows/ci.yml/badge.svg)](https://github.com/eligo-tech/monorepo-eligo/actions/workflows/ci.yml)

**AI-native recruiting platform.** A simple, reliable system-of-record with a layer
of narrow agents that read, enrich, match and explain — where **every agent claim is
verified against a real source before anyone sees it.** Verified AI, not bolted-on AI.

> Full product thesis, the six-layer architecture, and the non-negotiable invariants
> live in [`CLAUDE.md`](./CLAUDE.md).

## Repository

```
monorepo-eligo/
├── CLAUDE.md      # product thesis + architecture + invariants
├── backend/       # FastAPI · SQLAlchemy 2.0 async · Postgres/pgvector · OpenAI · laufwise
└── frontend/      # React · TypeScript · Vite · Tailwind — the recruiter cockpit
```

Backend and frontend are independent apps that meet at one contract: the HTTP API
under `/api/v1`.

## Tech stack (what's actually running)

**Backend** — Python 3.11+
| Concern | Choice |
|---|---|
| Web framework | **FastAPI** + **Uvicorn** |
| Schemas / config | **Pydantic v2** + **pydantic-settings** |
| ORM | **SQLAlchemy 2.0** (async) |
| Database | **Postgres** (Supabase) via **asyncpg** · **SQLite**/aiosqlite for zero-setup dev |
| Vectors | **pgvector** (embeddings column) |
| Migrations | **Alembic** (`create_all` bootstraps fresh DBs; Alembic evolves existing ones) |
| CV parsing | **pypdf** + a letter-spacing normalizer |
| LLM extraction | **OpenAI** `gpt-4o-mini` **structured outputs** (one call → flat fields + structured history) |
| Verification | **[laufwise](https://github.com/dfadeeff/laufwise)** pre/postcondition gate (pure predicates over real state) |
| Auth / tenancy | **Clerk** JWT (RS256 via JWKS) → `tenant_id`; **Postgres Row-Level Security** |
| Tests | **pytest** + httpx (runs on SQLite, no external services) |

**Frontend** — React 18 + TypeScript
| Concern | Choice |
|---|---|
| Build tool | **Vite** |
| Styling | **Tailwind CSS** (design tokens in `tailwind.config.js`) |
| Icons | **lucide-react** |
| Data | typed `fetch` client → `/api/v1` (Vite proxies to `:8000`), mock fallback offline |

**Deploy** — backend via **Docker** (Railway; `alembic upgrade head` on boot) · frontend static build on **Vercel**.

## Quick start

**Backend** (API + system-of-record):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[postgres,llm,dev]"     # or just "pip install -e ." for the SQLite/heuristic scaffold
uvicorn app.main:app --reload             # → http://localhost:8000  (docs at /docs)
```

Runs with **no external services** by default (SQLite + a heuristic CV parser). Set
`ELIGO_DATABASE_URL` (Postgres) and `OPENAI_API_KEY` to enable the full stack; see
`backend/app/core/config.py` for all `ELIGO_*` settings.

**Frontend** (the recruiter cockpit):

```bash
cd frontend
npm install
npm run dev        # → http://localhost:5173  (proxies /api → :8000)
```

Each folder has its own `CLAUDE.md` with architecture and conventions.

## What works today

- **CV upload → verified extraction.** A PDF is parsed, de-spaced, and sent to the
  LLM in a **single** structured-output call that returns the flat aiFind fields
  *and* a structured work history (per role: title, company, dates, achievement
  highlights) + education.
- **Verified AI, not trusted AI.** The LLM only *proposes*. Deterministic checks
  decide: a **confidence gate**, a **laufwise** pre/postcondition contract, and a
  **grounding guardrail** that drops any role/employer/degree not found in the source
  CV text (anti-hallucination). Every committed write leaves an append-only,
  hash-chained **Receipt**.
- **Candidate dossier.** Click a candidate to see the **original CV** (the attached
  PDF) side-by-side with the **parsed CV** — the structured record extracted from it,
  traceable back to the source.
- **Multi-tenant + isolated.** Clerk organizations map to tenants; every row carries
  `tenant_id` and Postgres RLS enforces isolation at the database layer.

## The four product surfaces

| Tab | What it shows |
|-----|---------------|
| **Kandidaten** | Live candidate list — search, sort (arrival / A–Z), filter by technology, CSV export, and the full dossier |
| **Matching** | Candidate-360 with an evidence-backed *"Warum wir gematcht haben"* panel (deterministic hard filters, LLM soft ranking) |
| **Pipeline** | Kanban board per job — Bewerbung → Long List → Short List → Benchmark |
| **Reporting** | Funnel, dwell-time per stage, jobs created, and fee share |

## The recruiting process it models

`Auftrag gewonnen → Briefing (KI) → Job anlegen → Sourcing/Outreach → Screening
(transcript → DB) → Vorstellung beim Kunden → Pipeline-Tracking → Feedback-Loops →
Vermittlung`. The pipeline board and reporting funnel make this flow — and where each
candidate sits in it — visible at a glance.
