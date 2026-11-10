# Architecture & compliance rules

Binding rules for how data moves through Eligo Labs. `CLAUDE.md` says *what* the
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
   Anything a tenant brought in (ATS imports, CVs, mailbox, notes,
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

An AI client's **proposal** (MCP, ADR 0003 §3.7) is not routed through
`verify_and_commit` either, and that is deliberate: confirming it is a *human*
edit, made by a person clicking in Eligo, so it runs the same domain write a
manual edit runs, attributed to that person, with a WRITE receipt naming who
asked, through which client, and who confirmed. The AI client itself only
ever creates a pending row in `agent_proposals`.

---

## 2. Data classification

Everything stored must fall into exactly one row of this table. If it doesn't,
the model is wrong.

| Class | Contains | Where | Tenant-scoped | Personal data |
|---|---|---|---|---|
| **Public corpus** | company identity, address, postings, fetch evidence, persons as named by a public source | `hub_companies`, `hub_job_postings`, `hub_observations` | no | **only as published, with provenance** (RULE 2) |
| **Corpus, derived** | the agency finder's ranked agencies: verdict, score, evidence counts, company mail domains — rebuilt nightly, readable only by `agency_finder_tenants` (fail-closed) | `hub_agency_profiles` | no | **as the corpus**: a sole trader's trading name, as published; removed with the company by the opt-out list |
| **Corpus, site checks** | one row per agency website candidate checked against its Impressum: outcome, Impressum URL, fetch, and COMPANY facts as published (register, VAT, company phone, function mailboxes) | `hub_site_checks` | no | **no** — people named in an Impressum are parsed but not stored until the GDPR Art. 14 question is answered (decision 2026-11-04) |
| **Corpus, ad contacts** | one row per person one open job ad names as its contact: name, role, and the phone / e-mail the ad itself gives, `phone_kind`, the quoted ad line, which text (ad / partner page) and its fetch time — read nightly by `hub/ad_contacts.py` (deterministic parser, ELI-22) | `hub_ad_contacts` | no | **yes, as published** (RULE 2, decision 2026-09-18) — never enriched; removed with the ad text (closed ad, suppressed person or company). Whether Art. 14 is owed at collection is still open (`docs/plans/info_hub.md`) |
| **Corpus, employer boards** | one row per discovered ATS job board (Personio): its status, its offices' postal addresses as the board publishes them, and the last snapshot of open job ids | `hub_ats_boards` | no | **no** — company offices only; ads themselves land in `hub_job_postings` |
| **Opt-out list** | normalized company names, folded person names, reason | `hub_suppressions` | no | **minimal** — only what is needed to recognise the record again; app role read-only |
| **Tenant overlay** | tracked/prospect flags, notes, adoption link | `hub_company_link` | yes | no |
| **Tenant record** | clients, mandates, pipeline | `companies`, `jobs`, `applications` | yes | no |
| **Personal data** | candidates, managers/contacts (incl. anything enriched or tenant-sourced) | `candidates`, `managers` | yes | **yes** |
| **Tenant record (accountability)** | that an erasure request was handled: when asked, when done, by whom, counts | `erasure_requests` | yes | no — names nobody, not even the erased row's id |
| **Personal data (pseudonymous)** | HMAC fingerprints of an erased person's import ids and e-mails, so the next import does not re-create them | `tenant_suppressions` | yes | **yes, while the key exists** — kept because honouring the request needs it (Art. 17(3)(b)); lifted, never deleted |
| **Personal data (transient)** | changes an AI client proposed, waiting for a person: candidate name in the title, a drafted note | `agent_proposals` | yes | **yes** — text and name erased on every decision and nightly after 7 days |
| **Provenance** | each proposed field value, its source, confidence and the postcondition reasons | `enrichment_records` | yes | **yes** — the value itself; deletable, so an erasure removes it. Trade-off, deliberate: values and reasons here are not tamper-evident (the chain names the record, not its content) — erasable and tamper-evident cannot both hold for the same text |
| **Audit** | receipts | `receipts` | yes | references only — field names and record ids, never a value or an address (`tests/test_receipts_hold_no_personal_data.py`). ⚠ Receipts written before 2026-11-02 still carry values in `summary`/`payload` (`write email='…'`, Art. 14 recipient); they are immutable, and erasure will black them out |

---

## 3. GDPR — obligation → architectural requirement

Company registry data about a legal entity (a GmbH) is **not** personal data.
Everything involving a *person* is. The rules above are what keep those two
apart at the schema level.

| Obligation | What the architecture must do | Status |
|---|---|---|
| **Art. 5(1)(b)** purpose limitation | each source adapter records why it exists and what it may be used for | ⚠ adapters have docstrings, no machine-readable purpose |
| **Art. 5(1)(c)** minimisation | corpus holds persons only as a public source published them (RULE 2); raw payloads pruned | ⚠ `hub_job_postings.raw` retains full source records indefinitely |
| **Art. 5(1)(e)** storage limitation | postings deactivate + expire; observations have a retention window | ⚠ partial — ads the source took down are closed and their payload (ad text, raw copy, partner page) deleted by the nightly liveness job (`hub/liveness.py`, only on the source's own not-found for that ad, after a live control); open ads keep `raw` indefinitely and observations have no window yet. `agent_proposals` erases its free text and the candidate's name on every decision, and a nightly job (`POST /proposals/maintenance/expire`) does the same for proposals older than 7 days in every workspace |
| **Art. 6(1)(f)** lawful basis | documented Legitimate Interest Assessment per source | ❌ not written |
| **Art. 14** third-party collection notice | any *person* ingested from a public source flags an Art. 14 duty | ✅ `agents/enrichment.py`; must extend to `managers` |
| **Art. 15/16** access & rectification | provenance per field, so we can say where a value came from | ✅ `EnrichmentRecord`, `hub_observations`, `resolution_basis` |
| **Art. 17/21** erasure & objection | **a suppression list, not a delete** — see below | ⚠ corpus: `hub_suppressions` by company and person name, no VAT/register/domain keys yet. Workspace: erasure of a candidate or contact with suppression, receipt blackout and request log (`domain/erasure/`, 0050) — no UI yet, backups not covered |
| **Art. 22** human oversight of decisions | hard filters deterministic; LLM only ranks | ✅ `matching/service.py` |
| **Art. 28** processors | inventory of sub-processors + DPAs (Railway, Supabase, Vercel, OpenAI) | ❌ not written |
| **Art. 30** records of processing | source inventory: what we fetch, how often, on what basis | ⚠ `hub_observations` is the evidence; no RoPA document |
| **Art. 32** security | tenant isolation in the DB (RLS), TLS, no secrets in logs | ✅ RLS fail-closed, `db_ssl`, tokens never logged |
| **Art. 44+** transfers | EU-hosted Postgres; US LLM providers need SCC/DPF cover | ⚠ verify Supabase region + OpenAI terms |

### The suppression list (Art. 17 / Art. 21)

Deleting a corpus row does not satisfy an erasure or objection request: **the
next scheduled crawl re-inserts it.** Erasure in a re-ingesting system requires a
tombstone that ingestion consults.

Built (migration 0047, `app/domain/hub/suppression.py`): `hub_suppressions`
holds a scope, a key and the reason (`erasure` | `objection` | `legal`), with
its date.

- **company** — keyed by the normalized company name, so it covers every site
  and both employer and agency rows. Ingest refuses the record before the gate,
  counts it in the summary and on the observation note, and never names it.
- **person** — keyed by the folded full name. The name (full form, "Frau
  <Surname>", and personal e-mail addresses) is cut from every ad text before
  it is stored — ingest, the description pass, the partner-page pass — and the
  contacts read redacts again as a backstop.
- **writes** — only `scripts/hub_suppress.py` on the owner connection, which
  also removes what is already stored. The app role may read the list and is
  refused every write by a SELECT-only policy (proved in
  `tests/test_rls_postgres.py`).

**Inside a workspace** (migration 0050, `app/domain/erasure/`). The
workspace is the controller and decides; an admin carries it out.

- **erase** — `POST /erasure/candidates/{id}` or `/erasure/managers/{id}`,
  admins only, the name typed to confirm. One transaction removes the person
  and every row that refers to them **by id** (CVs, processes and their
  steps, assessments, match results, notices, notes, interviews, provenance,
  AI proposals). Deliberately broad: a client note that names the candidate
  goes with them, and so do briefings linked to an erased contact. A
  contact's mandates stay and lose the link. Free text elsewhere that names
  the person without an id (a note on another record, a transcript) is not
  found — that remains a manual search.
- **receipts** — every receipt naming the person or one of those rows is
  blacked out whole (backend/CLAUDE.md §2.1), including AI-read receipts
  that listed them among others; one ERASE receipt lists them with their
  hashes, and the chain still verifies. **Trust boundary:** the app role
  carries out erasures, so a stolen app credential can erase too — what it
  cannot do is erase unseen. Every blackout needs an ERASE receipt (chained,
  never removable) backed by an `erasure_requests` row (insert-only for the
  app role); `verify_chain` reports an ERASE receipt without one. A forgery
  that also writes its own log row is **visible** in `GET /erasure/requests`
  and can never be removed, but nothing **detects** it as fake. The same holds
  for lifting a suppression: the app role may, it is recorded (`lifted_at`,
  `lifted_by_*`), nothing alerts on it yet. A blacked-out row's other columns
  are no longer under any hash: someone with DDL rights who drops the trigger
  could change them undetected.
- **suppression** — `tenant_suppressions` holds HMAC fingerprints (key:
  `ELIGO_SUPPRESSION_KEY`) of their import id (`source:external_id`, plus
  `merged_identities` should anything ever fill it) and their e-mail. The
  ATS import skips and counts a match before creating anyone, and refuses to
  run in a workspace with erasures if the key is missing. Creating the
  person again by hand, or editing someone to their address, is refused
  (409, with the date they asked) unless the recruiter confirms they came
  back; that lifts only the e-mail fingerprint, so the old ATS record stays
  out. Insert-and-lift only for the app role: a suppression cannot be
  deleted. **A person with neither an e-mail nor an import id gets no
  fingerprint and nothing stops them coming back** (`counts.suppressions_written
  == 0`; the UI must say so).
- **log** — `erasure_requests`: when asked, when done, by whom, how much.

Not covered, by design or not yet: copies outside the database (Supabase
backups for their retention period, exports already downloaded, the person
in the customer's own ATS — the import cannot delete there), the public
corpus (operator step, above), VAT/register/domain corpus keys (Impressum
adapter), and the UI (next).

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

1. The rest of Art. 17/21: identifier-keyed corpus suppressions (VAT,
   register, domain) and the erasure UI. Corpus opt-outs and workspace
   erasure are built (§3).
2. Retention/pruning of `raw` payloads of OPEN postings and of observations (Art. 5(1)(e)); closed postings are pruned by the liveness job
3. A written LIA + RoPA + sub-processor list (Art. 6/28/30)
4. **Sending** the Art. 14 notice. The tracking exists — `managers` carries
   `art14_notified_at`, `art14_outstanding` derives from the source, and
   `GET /managers/art14-outstanding` is the queue — but nothing delivers a
   notice; today that is a human with an e-mail client.
5. Roles inside a workspace. Every member of a Clerk org has full access, and
   the UI does not send `editor`, so a receipt cannot say WHO made a change.

**Done since this list was written:** the scheduled ingestion job exists
(`.github/workflows/hub-ingest.yml`, nightly, machine credential only) and
judges itself by measured coverage, failing the run — and mailing — below the
threshold.

**Schema debt:** `candidates.industry` is no longer read or written by any
code (migration 0030 moved the truth to `candidates.industries`). The column
itself still exists and must be dropped in a migration *after* the deploy that
removed the code — the container still serving during a rollout would select
it. One `op.drop_column`, nothing else.

Nothing here should be described to a customer as "GDPR compliant" or "SOC 2
compliant" until 1–3 exist. The architecture is *shaped* to make them
straightforward; that is not the same as having them.
