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

### RULE 1 — Ingestion is a scheduled job. No user, no UI.

**Filling the corpus is never a user action.** No button, no request handler, and
no page load may cause an outbound crawl of a public source. Ingestion runs on a
schedule, unattended, authenticated by a machine credential.

Why this is a rule and not a preference:

* **Layering.** A presentation control that performs an outbound HTTP crawl
  collapses four layers into one. Presentation reads; ingestion writes.
* **Third-party load.** N users × one button = N calls to a free public API for
  data already held. Politeness to a public service is a design constraint.
* **GDPR Art. 30 / SOC 2 CC7.** Collection must be a described, scheduled,
  logged activity with a named lawful basis — not an unpredictable side effect
  of someone clicking around.
* **Attribution.** "Which user triggered this crawl?" is a question with no good
  answer. "The nightly job ran at 03:00 and fetched these slices" is auditable.

The tenant identity of whoever *would* have triggered it is irrelevant: ingest
writes shared rows and must never tag them with a tenant.

Consequence: a recruiter who wants fresher data does not get a crawl button.
They get a corpus that is already current, and they *search* it.

### RULE 2 — The shared corpus holds company-level facts only. Never natural persons.

`hub_*` tables may contain: legal name, address, geo, register/VAT identifiers,
industry, job postings, and the evidence of how each was retrieved.

They may **not** contain: names, e-mail addresses, phone numbers, or profiles of
people — no hiring managers, no Geschäftsführer, no authors of a job ad.

Why: a shared table holding personal data means one data subject's erasure or
objection reaches across every customer, and it makes us controller of personal
data we are simultaneously distributing to third parties. Keeping persons out of
the shared layer keeps that entire class of problem in the tenant layer, where
consent, purpose and retention are already per-customer.

**Persons live only in tenant-scoped tables** (`managers`, `candidates`), carry
provenance, and route through the GDPR Art. 14 flow when sourced from a third
party.

Edge case that must be handled explicitly: **sole traders** (Einzelunternehmen,
Freiberufler) whose company name *is* a person's name. These are personal data
despite sitting in a company field. They must be flaggable and suppressible.

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
| **Public corpus** | company identity, address, postings, fetch evidence | `hub_companies`, `hub_job_postings`, `hub_observations` | no | **must be no** |
| **Tenant overlay** | tracked/prospect flags, notes, adoption link | `hub_company_link` | yes | no |
| **Tenant record** | clients, mandates, pipeline | `companies`, `jobs`, `applications` | yes | no |
| **Personal data** | candidates, managers/contacts | `candidates`, `managers` | yes | **yes** |
| **Audit** | receipts, enrichment records | `receipts`, `enrichment_records` | yes | references only |

---

## 3. GDPR — obligation → architectural requirement

Company registry data about a legal entity (a GmbH) is **not** personal data.
Everything involving a *person* is. The rules above are what keep those two
apart at the schema level.

| Obligation | What the architecture must do | Status |
|---|---|---|
| **Art. 5(1)(b)** purpose limitation | each source adapter records why it exists and what it may be used for | ⚠ adapters have docstrings, no machine-readable purpose |
| **Art. 5(1)(c)** minimisation | corpus stores no persons (RULE 2); raw payloads pruned | ⚠ `hub_job_postings.raw` retains full source records indefinitely |
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
| **PI1.1** processing integrity | outputs traceable to inputs; tamper-evident | ✅ hash-chained receipts, `verify_chain` |
| **P (Privacy)** | data classification and retention documented | ⚠ classification here; retention missing |

Note for auditors: the shared corpus is **not** a tenant-isolation gap. It holds
no personal data and no customer data — only public facts about companies, which
would be identical for any observer. Customer data remains RLS-isolated.

---

## 5. Honest status

Built: shared corpus, deterministic identity, ingest gate with pre/postconditions,
append-only fetch evidence, RLS everywhere, hash-chained receipts, machine
credential for ingestion.

**Known incomplete:** the nightly crawl shards by Bundesland and reaches ~83% of
German postings, because the source's `wo=` parameter matches place names rather
than regions. Exhaustive coverage needs PLZ-level sharding (~8,200 shards). The
job measures and prints its own coverage every run rather than assuming it.

**Not built, and required before this handles real customer data:**

1. `hub_suppressions` + a precondition in the ingest gate (Art. 17/21)
2. Retention/pruning of `raw` payloads and stale postings (Art. 5(1)(e))
3. The scheduled ingestion job itself, with failure alerting (RULE 1, CC7.2)
4. A written LIA + RoPA + sub-processor list (Art. 6/28/30)
5. Art. 14 wiring for `managers` once that domain exists

Nothing here should be described to a customer as "GDPR compliant" or "SOC 2
compliant" until 1–4 exist. The architecture is *shaped* to make them
straightforward; that is not the same as having them.
