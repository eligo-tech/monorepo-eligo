# eligo-tech backend — architecture & contributor guide

AI-native recruitment platform. This document is the contract: it tells you
where code goes and which invariants you may **never** break.

---

## 0. Design principles — and exactly where each is enforced

These are not aspirations; each maps to a concrete, checkable mechanism in the
codebase. If a change violates one of these, it is wrong by definition.

| Principle | How it is enforced here (not just claimed) |
|-----------|--------------------------------------------|
| **Separation of concerns** | The six layers below, and the per-domain file split (§3): `router` (HTTP only) → `service` (business logic, **no FastAPI imports**) → `models` (persistence) → `schemas` (wire contracts). A router never contains business logic; a service never touches `Request`/`Response`. |
| **Encapsulation** | Business logic lives *inside* a domain's `service.py`; other layers call it, never its internals. Persistence is reached only through services — routers and agents never build queries. The write path is sealed: agents **cannot** call `session.add`/`commit`; the *only* door to the record is `verification.verify_and_commit` (§2.1). |
| **Abstraction / dependency inversion** | Volatile details sit behind stable interfaces: the `CVExtractor` **protocol** + `factory.py` (OpenAI today, any provider tomorrow — callers depend on the interface, not OpenAI); `JSONList`/`JSONDict` **portable column types** (JSONB on Postgres, TEXT on SQLite) so domain code never branches on the DB; the laufwise gate expresses checks as declarative predicates, not inline `if`s. Providers/DBs are injected via `settings`, not hard-wired. |
| **Single source of truth** | The field set is defined once in `CV_FIELDS` (labels, order, schema enum all derive from it); the model registry (`registry.py`) is the one place every table is listed; design tokens live once in the frontend's `tailwind.config.js`. Add a thing in one place, not three. |
| **Single responsibility** | One module = one job. Extraction (`documents/extraction`), grounding/verification (`gate.py`, `verification/`), matching hard-filters vs. LLM ranking (§2.2) are separate units with narrow I/O contracts, each independently testable. |
| **Fail-closed / least surprise** | Unverifiable or low-confidence output never enters the record silently — it routes to review (§2.4) or is dropped with a receipt. Tenant isolation defaults on (RLS). Missing LLM/provider degrades to the heuristic fallback rather than 500-ing. |

When adding code, state (in the PR or a comment) which layer and domain it belongs
to; if it doesn't fit one, the abstraction is wrong — fix the boundary, don't
smuggle logic across it.

---

## 1. The layered architecture

Six conceptual layers, top to bottom:

1. **API** (`app/api`) — HTTP surface, versioned under `/api/v1`. Thin: it
   validates input and calls services.
2. **Domain** (`app/domain/*`) — the business. Each domain is self-contained.
3. **Agents** (`app/agents`) — narrow AI workers. They *propose*, never write.
4. **Verification** (`app/domain/verification`) — the trust boundary. The ONLY
   path from a proposal to the system-of-record. Records receipts.
5. **System-of-record** (`app/core/database` + each domain's `models.py`) —
   Postgres in prod (SQLite in the scaffold).
6. **Core** (`app/core`) — config, database engine/session, logging.

The differentiator is layer 4 sitting *between* agents (3) and the record (5).

---

## 2. Non-negotiable invariants

These are enforced in code. Do not route around them.

### 2.1 Agents propose · verification commits · receipts are append-only
- Agents (`app/agents/*`) return an `AgentResult` carrying `ProposedChange`
  objects. **They must never call `session.add`/`commit` on domain models.**
- The only bridge to persistence is
  `app.domain.verification.service.verify_and_commit`, invoked via
  `Agent.commit`. It runs postconditions, checks confidence, writes an
  `EnrichmentRecord`, and appends `Receipt`s.
- `Receipt`s are **append-only and hash-chained per tenant**. There is no
  update/delete path and no endpoint to create one directly. `verify_chain`
  can recompute the chain to prove it hasn't been tampered with.
- Rationale: EU AI Act traceability + GDPR Art. 22 (a human-contestable trail
  behind every automated action).

### 2.2 Deterministic hard filters vs. LLM soft ranking (matching)
- `matching/service.apply_hard_filters` is **plain Python, no LLM**: work
  permit, location radius, salary cap, required certifications, must-have
  skills. A candidate failing any is excluded with an explicit reason.
- `matching/service.rerank_and_explain` is **the LLM boundary** — the only
  place a model plugs in. It returns `(score, strength, reasons)` where each
  `MatchReason` has `title / strength / evidence`.
- The LLM may re-rank candidates that already passed the hard filters. It may
  **never** override a hard filter, and its output is a recommendation for a
  human, never an automated decision (GDPR Art. 22).

### 2.3 Multi-tenancy
- Every core table has a `tenant_id` (via `TenantMixin`). **Every query filters
  by `tenant_id`.** Services take `tenant_id` explicitly; never query
  cross-tenant.

### 2.4 Human-in-the-loop gates
- Low-confidence extraction → human review queue (not auto-committed).
- Enrichment from a third-party/public source → GDPR Art. 14 notification is
  flagged on the result.
- Outreach/presentations → **nothing is sent without explicit human approval**;
  the outreach agent only ever produces drafts.

### 2.5 LLM proposes, checks decide (CV extraction)
- **Extraction is vendor-neutral.** `domain/documents/extraction/` is a factory
  over a `CVExtractor` protocol (`text → ExtractedField[]`). `settings.llm_provider`
  selects the impl (`openai` today); **any provider falls back to the heuristic
  parser** when unavailable, so the feature runs offline and in CI. Add a provider
  = new module + one line in `factory.py`.
- **The LLM never decides — it proposes.** Every extracted value is gated by the
  confidence threshold *and* the **laufwise** pre/postcondition gate
  (`domain/documents/gate.py`), whose checks are **pure predicates over real
  state** (the [laufwise](https://github.com/dfadeeff/laufwise) invariant), never
  over model text: precondition (document has text) → extract → postcondition
  (e-mail syntactically valid; ≥1 field accepted) → persist → **re-query the DB
  and prove the row landed** (`candidate.exists == true`). A blocking precondition
  raises `PreconditionFailed` → HTTP 422; failed postconditions route to review.
  The gate's verdicts are surfaced in the result `notes` as the verification trace.

---

## 3. Per-domain file convention

Every domain package under `app/domain/<name>/` has exactly:

| file | responsibility |
|------|----------------|
| `models.py`  | SQLAlchemy ORM (system-of-record tables). Compose `IDMixin`, `TenantMixin`, `TimestampMixin`. |
| `schemas.py` | Pydantic v2 request/response contracts. `model_config = ConfigDict(from_attributes=True)` for read models. |
| `service.py` | Business logic. No FastAPI imports. Takes/returns models + schemas. |
| `router.py`  | `APIRouter` exposing the service. Thin. |

Shared primitives live in `app/domain/common/` (`mixins`, `enums`, `types`).
Cross-domain enums (`PipelineStage`, `ApplicationStatus`, `MatchStrength`,
`ConfidenceSource`, `ReceiptAction`, `WorkPermitStatus`) belong there.

Portable column types are in `common/types.py`: `JSONDict`/`JSONList` map to
`JSONB` on Postgres and TEXT on SQLite. Embeddings are JSON lists in the
scaffold; swap to a `pgvector` `Vector` column in the Postgres profile.

---

## 4. How to run

```bash
pip install -e ".[dev]"      # ".[postgres]" adds asyncpg + pgvector
python -m app.seed           # optional demo data
alembic upgrade head         # apply DB migrations (reads ELIGO_DATABASE_URL)
uvicorn app.main:app --reload
pytest                       # tests (SQLite, no external deps)
```

**Schema.** Fresh databases are bootstrapped by `create_all` on startup (it reads
the current model metadata, so new columns are included). Existing databases
(e.g. Supabase) are evolved with **Alembic migrations** in `migrations/versions/`
— `create_all` never alters an existing table. Adding/altering a column: change
the model, then `alembic revision -m "…"` (autogenerate compares against
`Base.metadata`) and `alembic upgrade head`. Migrations are idempotent w.r.t.
`create_all` (they skip columns that already exist). The Dockerfile runs
`alembic upgrade head` before the server on every deploy.
`app/domain/registry.py` imports every domain's models so both `create_all` and
Alembic autogenerate see all tables — **update it when you add a domain.**

---

## 5. Adding a new domain

1. `mkdir app/domain/<name>/` and add `__init__.py`, `models.py`, `schemas.py`,
   `service.py`, `router.py` (follow §3).
2. Compose the mixins on every model; give it a `tenant_id`.
3. Import the new `models` module in `app/domain/registry.py`.
4. `include_router(...)` your router in `app/api/routes.py`.
5. If agents will modify your entity, they emit `ProposedChange`s with
   `entity_type="<name>"` and go through `verify_and_commit` — never a direct
   write.
6. Add a test.

---

## 6. Adding a new agent

1. Subclass `app.agents.base.Agent` in `app/agents/<name>.py`.
2. Implement `run(payload) -> AgentResult`. **No DB writes.** Emit
   `ProposedChange`s and/or `review_items`.
3. Override `postconditions()` with deterministic checks any write must pass
   (format, deliverability, allowed provenance, …).
4. Persist only via `agent.commit(session, result)` — it records receipts.