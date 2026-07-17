# eligo-tech

**AI-native recruiting platform.** A simple, reliable system-of-record with a layer
of narrow agents that read, enrich, match and explain — where **every agent claim is
verified against a real source before anyone sees it.** Verified AI, not bolted-on AI.

> Full product thesis, the six-layer architecture, and the non-negotiable invariants
> live in [`CLAUDE.md`](./CLAUDE.md).

## Repository

```
monorepo-eligo/
├── CLAUDE.md      # product thesis + architecture + invariants
├── backend/       # FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Postgres/pgvector
└── frontend/      # React · TypeScript · Vite · Tailwind — the CRM mockup
```

Backend and frontend are independent apps that meet at one contract: the HTTP API
under `/api/v1`.

## Quick start

**Frontend** (the CRM mockup — runs standalone on mock data):

```bash
cd frontend
npm install
npm run dev        # → http://localhost:5173
```

**Backend** (API + system-of-record):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload   # → http://localhost:8000  (docs at /docs)
```

The frontend dev server proxies `/api` → `http://localhost:8000`, so run both for a
live end-to-end setup. Each folder has its own `CLAUDE.md` with conventions.

## The four product surfaces

The frontend mockup realises the four tabs of the recruiter cockpit:

| Tab | What it shows |
|-----|---------------|
| **Kandidaten** | Canonical candidate list with skills + a **verification score** per record |
| **Matching** | Candidate-360 with an AI summary and an evidence-backed *"Warum wir gematcht haben"* panel |
| **Pipeline** | Kanban board per job — Bewerbung → Long List → Short List → Benchmark |
| **Reporting** | Funnel, dwell-time per stage, jobs created, and fee share |

## The recruiting process it models

`Auftrag gewonnen → Briefing (KI) → Job anlegen → Sourcing/Outreach → Screening
(transcript → DB) → Vorstellung beim Kunden → Pipeline-Tracking → Feedback-Loops →
Vermittlung`. The pipeline board and reporting funnel make this flow — and where each
candidate sits in it — visible at a glance.