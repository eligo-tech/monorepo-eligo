# Architecture & compliance rules

Binding rules for how data moves through eligo-tech. `CLAUDE.md` says *what* the
product is; this says *where code and data are allowed to live*, and why the
boundaries are shaped by EU-AI-Act / GDPR / SOC 2 obligations rather than taste.

If a change breaks a rule here, the change is wrong. Fix the boundary, do not
route around it.

---

## 1. The four layers

```
┌─ INGESTION ───────────────────────────────────────────────────────────┐
│  Scheduled job (cron). NO USER. NO UI.                                │
│  public sources → adapters → gate → upsert into the shared corpus     │
└───────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─ DATA ────────────────────────────────────────────────────────────────┐
│  SHARED corpus: hub_companies · hub_job_postings · hub_observations   │
│    no tenant_id · company-level facts ONLY · no natural persons       │
│  TENANT record: companies · managers · jobs · candidates · pipeline   │
│    every row carries tenant_id · RLS fail-closed                      │
└───────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─ BUSINESS LOGIC ──────────────────────────────────────────────────────┐
│  domain/*/service.py — no FastAPI imports, no outbound crawling       │
│  search the corpus · import a subset · verify · match · rank          │
└───────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─ PRESENTATION ────────────────────────────────────────────────────────┐
│  routers (thin) + frontend. READS the corpus. NEVER fills it.         │
└───────────────────────────────────────────────────────────────────────┘
```

### RULE 1 — Ingestion is machine-triggered only.

**No human-authenticated request may cause an outbound crawl of a public
source.** Not from the UI, and not from a logged-in user calling the API.

The rule previously read "no request handler may crawl", which was false: the
design *is* a request handler — the scheduler calls `POST /hub/ingest` and the
crawl runs synchronously inside that request. A rule the code visibly
contradicts gets read as aspiration, and that is how a critical hole shipped
past a review that claimed to check for it.

Three parts:

1. **No human-authenticated or UI trigger.** A valid Clerk session is refused on
   every operator endpoint.
2. **Operator endpoints exist, machine credentials only.** `ELIGO_INGEST_TOKEN`,
   no fallback, fail-closed: with no token configured and auth enabled, ingestion
   returns 503 rather than accepting whoever asks.
3. **Scheduler → job is HTTP today; a known deviation.** Holding a request open
   across dozens of external calls gives no retry, no backpressure, and makes a
   timeout indistinguishable from a failure. A queue would be better. Do not
   resolve it by moving the crawl into a user-facing path.

Enforced by `backend/tests/test_operator_endpoints.py`, which derives the
machine-only route set from the app, requires it to match an explicit
declaration, and attacks each route with a valid session for a real
organisation. Verified by reintroducing the original bug and watching it fail.

Reasons, in order of weight: N users × one trigger = N calls to a free public
API for data already held; GDPR Art. 30 / SOC 2 CC7 require collection to be a
described, scheduled, logged activity; "which user triggered this crawl?" has no
good answer while "the nightly job ran at 03:17" is auditable; and an operator
endpoint reachable by any tenant leaks `/hub/crawl-profiles` — the union of every
workspace's saved-search terms.

### RULE 2 — The shared corpus holds public facts. Persons are allowed only as a public source published them.

`hub_*` tables may contain: legal name, address, geo, register/VAT identifiers,
industry, job postings, the evidence of how each was retrieved — **and persons
named in a public source**, such as the contact in a job ad ("Ihre
Ansprechpartnerin: Frau Sophie Bennicke, Personalreferentin").

**Decision (product owner, 2026-09-18):** a person the employer names in a public
job ad was published for exactly this purpose: to be contacted about the
vacancy. Storing and showing that in the shared corpus is intended, not a
violation. Do not flag it as a red flag and do not redact it from ad texts.

The conditions that make it hold:

1. **Public source only.** The value must arrive through scheduled ingestion
   from a public source: job ad, partner job board, career page, Impressum.
   Anything a tenant brought in (ATS/aiFind imports, CVs, mailbox, notes,
   recruiter edits) is tenant data and never enters `hub_*` (RULE 3). This
   includes a person a tenant adopted into `managers`; that row does not flow
   back.
2. **Provenance per person.** Every person in the corpus traces to the posting /
   URL and fetch time it came from (`hub_observations`). No public source, no
   place in the shared corpus.
3. **As published, nothing more.** Store what the source says: name, title, and
   the contact route the ad itself gives. Enrichment (email/phone from a data
   provider, a LinkedIn/XING profile) is tenant work and lands in `managers`,
   not in the shared layer.
4. **Still personal data under GDPR.** Public does not mean exempt: the
   suppression list (§3) must be able to hold a person back from re-ingestion,
   and adopting a person into a tenant's `managers` sets `source=third_party`
   and owes the Art. 14 notice.

**Sole traders** (Einzelunternehmen, Freiberufler) trade under their own name, so
`hub_companies.name` can be a person — "Andreas Uwe Weiss". That is public
register/posting data and allowed under the same conditions.
`resolution.looks_like_natural_person` screens at ingest and sets
`suspected_natural_person` so such rows stay findable for the suppression list;
the flag marks, it does not forbid.

### RULE 3 — The tenant boundary is a table, not a column on shared data.

A tenant's interest in a corpus company is a row in `hub_company_link`
(`tenant_id`, `hub_company_id`, relationship, note, adopted `company_id`).
Never add `tenant_id` back onto a `hub_*` corpus table.

### RULE 4 — Agents propose, verification commits, receipts are append-only.

Unchanged from `backend/CLAUDE.md` §2.1. Ingestion into the corpus is *not* an
agent commit (it asserts nothing about anyone's record). The crossing that owes
a receipt is adoption of a corpus company into a tenant's `companies`.

---

## 2. Data classification

Everything stored must fall into exactly one row of this table. If it doesn't,
the model is wrong.

| Class | Contains | Where | Tenant-scoped | Personal data |
|---|---|---|---|---|
| **Public corpus** | company identity, address, postings, fetch evidence, persons as named by a public source | `hub_companies`, `hub_job_postings`, `hub_observations` | no | **only as published, with provenance** (RULE 2) |
| **Tenant overlay** | tracked/prospect flags, notes, adoption link | `hub_company_link` | yes | no |
| **Tenant record** | clients, mandates, pipeline | `companies`, `jobs`, `applications` | yes | no |
| **Personal data** | candidates, managers/contacts (incl. anything enriched or tenant-sourced) | `candidates`, `managers` | yes | **yes** |
| **Audit** | receipts, enrichment records | `receipts`, `enrichment_records` | yes | references only |

---

## 3. GDPR — obligation → architectural requirement

Company registry data about a legal entity (a GmbH) is **not** personal data.
Everything involving a *person* is. The rules above are what keep those two
apart at the schema level.

| Obligation | What the architecture must do | Status |
|---|---|---|
| **Art. 5(1)(b)** purpose limitation | each source adapter records why it exists and what it may be used for | ⚠ adapters have docstrings, no machine-readable purpose |
| **Art. 5(1)(c)** minimisation | corpus holds persons only as a public source published them (RULE 2); raw payloads pruned | ⚠ `hub_job_postings.raw` retains full source records indefinitely |
| **Art. 5(1)(e)** storage limitation | postings deactivate + expire; observations have a retention window | ❌ not implemented — no retention job |
| **Art. 6(1)(f)** lawful basis | documented Legitimate Interest Assessment per source | ❌ not written |
| **Art. 14** third-party collection notice | any *person* ingested from a public source flags an Art. 14 duty | ✅ `agents/enrichment.py`; must extend to `managers` |
| **Art. 15/16** access & rectification | provenance per field, so we can say where a value came from | ✅ `EnrichmentRecord`, `hub_observations`, `resolution_basis` |
| **Art. 17/21** erasure & objection | **a suppression list, not a delete** — see below | ❌ not implemented |
| **Art. 22** human oversight of decisions | hard filters deterministic; LLM only ranks | ✅ `matching/service.py` |
| **Art. 28** processors | inventory of sub-processors + DPAs (Railway, Supabase, Vercel, OpenAI) | ❌ not written |
| **Art. 30** records of processing | source inventory: what we fetch, how often, on what basis | ⚠ `hub_observations` is the evidence; no RoPA document |
| **Art. 32** security | tenant isolation in the DB (RLS), TLS, no secrets in logs | ✅ RLS fail-closed, `db_ssl`, tokens never logged |
| **Art. 44+** transfers | EU-hosted Postgres; US LLM providers need SCC/DPF cover | ⚠ verify Supabase region + OpenAI terms |

### The suppression list (Art. 17 / Art. 21)

Deleting a corpus row does not satisfy an erasure or objection request: **the
next scheduled crawl re-inserts it.** Erasure in a re-ingesting system requires a
tombstone that ingestion consults.

Required: a `hub_suppressions` table keyed by the same deterministic identity as
the corpus (`dedupe_key`, VAT, register number, or normalized domain), carrying
the reason (`erasure` | `objection` | `legal`) and the date. The ingest gate must
check it as a **precondition** and refuse the record, leaving an observation note
so the refusal is auditable.

This is the single most important missing piece for GDPR, because it is the one
that cannot be retrofitted by a script — it must live in the ingest path.

---

## 4. SOC 2 — criterion → architectural requirement

| Criterion | Requirement | Status |
|---|---|---|
| **CC6.1** logical access | tenant isolation enforced by the **database**, not app code | ✅ RLS, `FORCE`, fail-closed on unset GUC |
| **CC6.1** documented exception | the shared corpus is an intentional exception, justified in writing | ✅ RULE 2 + `backend/CLAUDE.md` §2.6 |
| **CC6.3** least privilege | ingest credential may write shared rows only, never tenant data | ✅ `get_ingest_tenant` discards the tenant |
| **CC6.6** secrets | machine credentials rotatable, never logged, minimum strength enforced | ✅ 32-char floor, constant-time compare; ❌ no rotation policy |
| **CC7.2** monitoring | the scheduled job must alert on failure, not fail silently | ❌ not implemented |
| **CC7.3** evidence of operation | proof of what ran, when, and what it retrieved | ✅ `hub_observations` is exactly this |
| **CC8.1** change management | migrations reviewed, CI green before merge | ✅ Alembic + PR + GitHub Actions |
| **PI1.1** processing integrity | outputs traceable to inputs; tamper-evident | ✅ hash-chained receipts with DB-enforced immutability (triggers + revoked grants); `verify_chain` checks hashes and contiguity. ⚠ head truncation still needs an external anchor |
| **P (Privacy)** | data classification and retention documented | ⚠ classification here; retention missing |

Note for auditors: the shared corpus is **not** a tenant-isolation gap. It holds
no customer data — only public facts, including persons as a public job ad names
them, which would be identical for any observer. Customer data remains RLS-isolated.

---

## 5. Honest status

Built: shared corpus, deterministic identity, ingest gate with pre/postconditions,
append-only fetch evidence, RLS everywhere, hash-chained receipts, machine
credential for ingestion.

**Known incomplete:** the receipt ledger detects modification, mid-chain
insertion and deletion, but not truncation at the head — nothing inside the
database can distinguish "ten receipts" from "twelve, with the last two
removed". That requires periodically anchoring the signed chain head somewhere
the application cannot reach.

**Known incomplete:** the nightly crawl shards by Bundesland and reaches ~83% of
German postings, because the source's `wo=` parameter matches place names rather
than regions. Exhaustive coverage needs PLZ-level sharding (~8,200 shards). The
job measures and prints its own coverage every run rather than assuming it.

**Not built, and required before this handles real customer data:**

1. `hub_suppressions` + a precondition in the ingest gate (Art. 17/21)
2. Retention/pruning of `raw` payloads and stale postings (Art. 5(1)(e))
3. The scheduled ingestion job itself, with failure alerting (RULE 1, CC7.2)
4. A written LIA + RoPA + sub-processor list (Art. 6/28/30)
5. Art. 14 wiring for `managers` (incl. persons adopted from the corpus)

Nothing here should be described to a customer as "GDPR compliant" or "SOC 2
compliant" until 1–4 exist. The architecture is *shaped* to make them
straightforward; that is not the same as having them.
