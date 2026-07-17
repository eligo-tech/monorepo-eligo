# eligo-tech — AI-native Recruiting Platform

A verified-AI recruiting CRM. The system-of-record stays deliberately simple and
reliable; a layer of narrow agents continuously reads, enriches, matches and
explains — and **every claim an agent makes is checked against a real source
before a recruiter or client ever sees it.** The moat is not "we have AI" — it is
*verified* AI: everyone else logs what the agent said; we check whether it's true.

The product a recruiter experiences is a living **Candidate-360** dashboard:
status, collected documents, an evidence-backed analysis, and a prioritized list of
matching jobs — kept current by agents, traceable down to the evidence.

## Monorepo layout

```
monorepo-eligo/
├── CLAUDE.md          # ← you are here — product thesis + how the halves relate
├── backend/           # FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Postgres/pgvector
│   └── CLAUDE.md       # layered architecture + invariants (agents propose / verification commits)
└── frontend/          # React · TypeScript · Vite · Tailwind — the CRM mockup
    └── CLAUDE.md       # feature-first structure + design system
```

Backend and frontend are developed **independently** — each has its own toolchain,
own `CLAUDE.md`, and own run instructions. They meet at one contract: the HTTP API
under `/api/v1`. The frontend dev server proxies `/api` to the backend on `:8000`.

## The six layers (where the differentiator lives)

1. **Sources & ingestion** — existing ATS export, mailbox/calendar, job boards,
   public career pages, document uploads. Parse → normalize to the canonical schema
   → entity-resolve (three "J. Schmidt" become one person).
2. **Canonical data & storage** — Postgres is the single system-of-record;
   pgvector holds embeddings; object storage holds raw documents; an append-only
   event log records every agent action.
3. **Agent layer** — five narrow workers (document extraction, enrichment,
   market-map, matching, outreach). Each has a defined I/O contract and **cannot
   write to the record directly** — it *proposes*.
4. **Intelligence** — the matching/analysis engine. Rule: **deterministic code
   decides hard criteria; the model decides fuzzy fit.** Work permit, location
   radius, salary band, certifications are checked in plain code and are
   non-negotiable. The LLM only ranks and explains *within* the set that already
   passed those filters.
5. **Verification & governance** — the differentiating layer. Before any agent
   claim reaches the record or the recruiter: postcondition re-check against the
   real source, provenance + confidence on every field, human-in-the-loop approval
   for consequential actions, and a signed, append-only **Receipt**.
6. **Application** — the Candidate-360 dashboard, a private API, and (later) an MCP
   server so recruiters can query their own data from Claude/ChatGPT.

## Non-negotiable invariants (hold across the whole system)

- **Agents propose, verification commits, receipts are append-only.** No agent
  writes to the system-of-record without passing verification and leaving a receipt.
- **Deterministic hard filters vs. LLM soft ranking.** Never let the model decide a
  legally-hard criterion (work permit, location, salary cap, required cert).
- **Every displayed claim is evidence-backed.** Match reasons, enrichments, and
  analysis all link to a source; unverifiable/low-confidence output goes to a human
  review queue, never silently into the record.
- **Multi-tenant from day one.** Every core row carries a `tenant_id`; strict tenant
  isolation is a hard requirement, not a later refactor.

## Compliance is part of the product (EU market)

The verification / receipt / human-oversight layer maps almost one-to-one onto what
an EU-AI-Act **high-risk** hiring system must have. Enrichment/market-map agents must
respect GDPR **Art. 14** (notify when personal data is collected from third parties),
matching honors **Art. 22** (human oversight of consequential automated decisions),
and the market-map agent is limited to **public** job/company data. Lead with this —
it's the moat, not overhead.

## Build order (design-partner first, revenue before breadth)

Phase 0 ingest & read-only Candidate-360 → 1 document intelligence → 2 matching →
3 enrichment (with Art. 14 workflow) → 4 market map & BD signals → 5 outreach &
presentation. The verification/receipt backbone runs through every phase from day one.