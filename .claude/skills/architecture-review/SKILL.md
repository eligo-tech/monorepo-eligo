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

### RULE 1 — Ingestion is machine-triggered only.

**No human-authenticated request may cause an outbound crawl of a public source.**
Not from the UI, and not from a logged-in user calling the API directly.

The earlier wording — "no request handler may crawl" — was false, and its
falseness had a cost. The actual design *is* a request handler: the scheduler
calls `POST /hub/ingest` over HTTP, and the crawl runs synchronously inside that
request. Stating a rule the code visibly contradicts trains people to read it as
aspiration, and it is precisely how F1 shipped: the reviewer's check confirmed
the frontend was clean and stopped there, while the backend dependency fell back
to the human path.

State it in three parts instead:

1. **No human-authenticated or UI trigger.** A valid Clerk session must be
   refused on every operator endpoint.
2. **Operator endpoints are allowed, with machine credentials only.** The
   scheduler authenticates with `ELIGO_INGEST_TOKEN`; there is no fallback.
3. **The scheduler → job boundary is HTTP today, and that is a known
   deviation.** A crawl that holds a request open across dozens of external
   calls is fragile — a timeout is indistinguishable from a failure, and there
   is no retry or backpressure. A queue would be better. Do not "fix" this by
   moving the crawl into a user-facing path.

**Enforcement is `backend/tests/test_operator_endpoints.py`, not a grep.** It
derives the machine-only route set by introspecting which routes depend on
`get_ingest_tenant`, requires that set to match an explicit declaration, and
then attacks each one with a *valid session for a real organisation*. Verified:
reintroducing the F1 fallback fails four of its cases.

```bash
# The enforcement itself. If you change ingestion, this must still pass.
cd backend && .venv/bin/python -m pytest tests/test_operator_endpoints.py -q

# Adding an operator endpoint? Declare it, or the first test fails:
grep -n "DECLARED_OPERATOR_ROUTES" -A 8 backend/tests/test_operator_endpoints.py

# The UI must still have no path to ingestion (comment lines excluded — a
# docstring naming the endpoint is not a call, and a check that flags prose is
# one people learn to ignore).
grep -rn "/hub/ingest" frontend/src | grep -vE ":[[:space:]]*(\*|//)" \
  && echo "VIOLATION: the UI can crawl"
```

Reasons the rule exists, in order of weight: N users × one trigger = N calls to
a free public API for data already held; GDPR Art. 30 / SOC 2 CC7 require
collection to be a *described, scheduled, logged* activity; "which user
triggered this crawl?" has no good answer while "the nightly job ran at 03:17"
is auditable; and an operator endpoint reachable by any tenant leaks
`/hub/crawl-profiles`, the union of every workspace's saved-search terms.

### RULE 2 — The shared corpus holds company-level facts only. Never natural persons.

`hub_companies`, `hub_job_postings`, `hub_observations` may hold legal name,
address, geo, register/VAT identifiers, industry, postings, and retrieval
evidence. They may **not** hold names, e-mails, phone numbers or profiles of
people — no hiring managers, no Geschäftsführer, no ad authors.

```bash
# A person-shaped COLUMN on a shared table is a violation.
grep -nE "first_name|last_name|email|phone|person|contact" backend/app/domain/hub/models.py
# Shared tables must not carry tenant_id (see RULE 3).
grep -n "TenantMixin" backend/app/domain/hub/models.py   # only HubCompanyLink may
```

**A grep over column names is not sufficient, and assuming it was is how the
live violation survived.** A sole trader IS the company, so `hub_companies.name`
holds personal data while every column stays company-shaped — "Andreas Uwe
Weiss" was in the corpus with no flag. No check over the word `name` finds a
person inside a column called `name`.

The value-level screen is `resolution.looks_like_natural_person`, applied at
ingest and surfaced as `suspected_natural_person`. When reviewing a change that
adds a shared column or a new source, ask what the *values* can contain, not
just what the column is called:

```bash
# (-k "flagg" matches all three screening tests; a selector that silently
#  deselects everything is the same false green this rule exists to prevent)
cd backend && .venv/bin/python -m pytest tests/test_hub_resolution.py -q -k flagg
# And for a new adapter: does anything person-shaped reach `raw`?
grep -n "raw=" backend/app/domain/hub/adapters/*.py
```

The screen flags; it does not remedy. Erasure still needs a suppression list
(ARCHITECTURE.md §3) — deleting a row does not help while tonight's crawl
re-inserts it.

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
