---
name: architecture-review
description: Review a change against eligo-tech's binding architecture and compliance rules — layering, the shared-corpus/tenant boundary, agents-propose-verification-commits, GDPR/SOC 2 obligations. Use before opening a PR, when reviewing one, when adding a table or a column, when deciding where data lives, or whenever a change touches app/domain/hub, verification, tenancy, RLS, ingestion, or anything storing personal data.
tools: Read, Glob, Grep, Bash
---

# Architecture review — eligo-tech

`ARCHITECTURE.md` at the repo root is binding, and `backend/CLAUDE.md` §2 states
the same invariants in enforcement terms. Read both before reviewing. This skill
is the checklist for applying them; it does not replace them.

**A change that breaks a rule below is wrong by definition. Fix the boundary,
do not route around it.**

---

## The four layers

```
INGESTION      scheduled job (cron). NO USER. NO UI.
                 ↓
DATA           SHARED corpus (hub_*, no tenant_id, company facts only)
               TENANT record (companies · managers · jobs · candidates)
                 ↓
BUSINESS LOGIC domain/*/service.py — no FastAPI imports, no outbound crawling
                 ↓
PRESENTATION   routers (thin) + frontend. READS the corpus. NEVER fills it.
```

## The rules, and how to check each

### RULE 1 — Ingestion is a scheduled job. No user, no UI.

No button, no request handler, no page load may cause an outbound crawl of a
public source. Ingestion runs unattended, authenticated by a machine credential.

```bash
# Any client CALL that can trigger ingestion is a violation. The filter drops
# comment lines — `types.ts` legitimately documents the endpoint it never calls,
# and a check that flags prose is a check people learn to ignore.
grep -rn "/hub/ingest" frontend/src | grep -vE ":[[:space:]]*(\*|//)" \
  && echo "VIOLATION: the UI can crawl"

# Legitimate callers: the router, the scheduled job, operator scripts.
grep -rn "service.ingest\|\"/hub/ingest\"" backend/app backend/scripts
```

Why it is a rule: a presentation control performing an outbound crawl collapses
four layers into one; N users × one button = N calls to a free public API for
data already held; GDPR Art. 30 / SOC 2 CC7 require collection to be a
*described, scheduled, logged* activity; and "which user triggered this crawl?"
has no good answer while "the nightly job ran at 03:17" is auditable.

### RULE 2 — The shared corpus holds company-level facts only. Never natural persons.

`hub_companies`, `hub_job_postings`, `hub_observations` may hold legal name,
address, geo, register/VAT identifiers, industry, postings, and retrieval
evidence. They may **not** hold names, e-mails, phone numbers or profiles of
people — no hiring managers, no Geschäftsführer, no ad authors.

```bash
# A person-shaped column on a shared table is a violation.
grep -nE "first_name|last_name|email|phone|person|contact" backend/app/domain/hub/models.py
# Shared tables must not carry tenant_id (see RULE 3).
grep -n "TenantMixin" backend/app/domain/hub/models.py   # only HubCompanyLink may
```

Why: a shared table of personal data makes one data subject's erasure reach
across every customer, and makes us controller of personal data we are
simultaneously distributing. Persons live only in tenant-scoped tables, carry
provenance, and route through the GDPR Art. 14 flow.

Edge case that must stay handled: **sole traders** (Einzelunternehmen,
Freiberufler) whose company name *is* a person's name. Personal data despite
sitting in a company field — must be flaggable and suppressible.

### RULE 3 — The tenant boundary is a table, not a column on shared data.

A tenant's relationship to a corpus company is a row in `hub_company_link`.
**Never add `tenant_id` back onto a `hub_*` corpus table.** If something must be
stored per tenant about a corpus company, it belongs in the link table.

### RULE 4 — Agents propose · verification commits · receipts are append-only.

Agents return `ProposedChange`s and must never call `session.add`/`commit` on
domain models. The only bridge is `verification.verify_and_commit`.

```bash
# base.py is EXCLUDED on purpose: `Agent.commit` is the sanctioned bridge — it
# routes every proposal through verify_and_commit and only then commits. Any
# OTHER agent module touching the session is the violation.
grep -rn "session.add\|session.commit" backend/app/agents/ --exclude=base.py
```

Ingestion into the corpus is **not** an agent commit — it asserts nothing about
anyone's record and owes no receipt. The crossing that *does* owe one is
adoption of a corpus company into a tenant's `companies`.

### RULE 5 — Deterministic hard criteria, model only for soft ranking.

`matching.apply_hard_filters` is plain Python. The LLM may re-rank what already
passed; it may never override a hard filter (GDPR Art. 22).

The same rule governs **identity**: `hub/resolution.py` decides company identity
by a deterministic ladder (VAT → register → domain → normalized name + PLZ).
Fuzzy or LLM similarity belongs in a human review queue, never in an auto-merge.

---

## Data classification

Every stored field must fall into exactly one row. If it does not, the model is
wrong.

| Class | Where | tenant_id | personal data |
|---|---|---|---|
| Public corpus | `hub_companies`, `hub_job_postings`, `hub_observations` | no | **must be no** |
| Tenant overlay | `hub_company_link` | yes | no |
| Tenant record | `companies`, `jobs`, `applications` | yes | no |
| Personal data | `candidates`, `managers` | yes | **yes** |
| Audit | `receipts`, `enrichment_records` | yes | references only |

---

## Compliance checks that are architectural, not paperwork

- **Erasure needs a suppression list, not a DELETE.** In a re-ingesting system
  the next crawl re-inserts a deleted row. A tombstone keyed on the same
  deterministic identity must be checked as an ingest **precondition**. Not yet
  built — flag any change that assumes deletion works.
- **Retention.** `hub_job_postings.raw` accumulates source payloads indefinitely;
  stale postings need pruning (GDPR Art. 5(1)(e)). Not yet built.
- **Provenance.** Every corpus row must trace to a `hub_observations` row. A new
  write path that does not record its retrieval is a violation of the
  "every displayed claim is evidence-backed" invariant.
- **Tenant isolation is enforced by the DATABASE** (RLS, `FORCE`, fail-closed on
  an unset GUC), not by app code. A new tenant-scoped table needs an RLS policy
  in its migration — see `migrations/versions/0003` and `0005` for the shape.

Never describe the system to a customer as "GDPR compliant" or "SOC 2
compliant" while the gaps in `ARCHITECTURE.md` §5 are open.

---

## Review procedure

1. Read `ARCHITECTURE.md` and `backend/CLAUDE.md` §2.
2. `git diff main...HEAD --stat` — which layers does this touch?
3. Run the greps above for every rule the diff plausibly touches.
4. For each new table or column, place it in the classification table. State
   where it landed and why.
5. For each new migration: does it carry an RLS policy? Is it idempotent w.r.t.
   `create_all`? Does it guard destructive steps?
6. For each new claim in docs or a PR body: is it **measured** or assumed?
   This codebase has been wrong twice by trusting a source's documentation over
   its behaviour — prefer a number you produced to a number you read.
7. Report violations as: rule → the specific line → the concrete failure it
   causes. Not "this seems inconsistent".
