# ADR 0001 — Where the Postgres system-of-record runs

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** Dmitry Fadeev
- **Decision:** **Stay on Supabase, upgrade to Pro.** Start on Micro, move to Small if
  benchmarks require it (~$30/mo). Do not migrate to Railway Postgres.
- **Related:** [`ARCHITECTURE.md`](../../ARCHITECTURE.md) §2 data classification, §4 SOC 2

> A first draft of this ADR recommended Railway Postgres. It was wrong on three points
> of fact and is corrected here; see §9.

---

## 1. Context

The system-of-record is Postgres on **Supabase Free**. On 2026-09-05 corpus search became
unusable and then took the API down. Investigation produced the measurements below.

### 1.1 What was measured

| probe | measured | healthy Postgres |
|---|---|---|
| `select count(*) from generate_series(1,1000000)` — no table, no disk, pure CPU | **8,284 ms** | ~80 ms |
| `count(*)` on `hub_companies` (81,540 rows) | **timed out at 180 s** | ~30 ms |
| 81 rows by primary key, fully cached (`Buffers: shared hit=298`) | **2,054 ms** | ~2 ms |

Roughly **100× slower than a healthy Postgres on pure CPU work**. `generate_series`
touches no user data, so this is not a query problem.

### 1.2 Why — and what it does *not* prove

Supabase Free provides *Shared CPU · 500 MB RAM* with a **500 MB database quota**. The
database measured **654 MB** — 31% over. The billing page states plainly:

> Projects may become unresponsive when this organization exceeds its included usage quota.

Spend Cap is enabled, so the response to exceeding quota is **degradation, not billing**.

**This is a quota-breach symptom, not evidence that Supabase cannot serve the workload.**
The first draft of this ADR treated it as the latter and reached the wrong conclusion.

### 1.3 The asymmetry that shapes durability requirements

| class | tables | size | if lost |
|---|---|---|---|
| **Re-crawlable** | `hub_companies`, `hub_job_postings`, `hub_observations` | **630.9 MB (98.2%)** | re-crawl from public sources |
| **Irreplaceable** | `candidate_documents` (9.1 MB), `receipts` (1.4 MB), `candidates`, `applications`, `jobs`, `enrichment_records`, `hub_company_link`, `saved_searches`, `tenants` | **11.5 MB (1.8%)** | unrecoverable — includes the append-only hash-chained receipt ledger behind ARCHITECTURE.md §4 |

98.2% of the bytes are disposable; the part that must never be lost is 11.5 MB. This is
why an independent dump layer (§6.6) is cheap enough to run regardless of host.

### 1.4 Composition of the bulk — the real cost driver

Within `hub_job_postings` (488 MB table + 80 MB indexes):

| column | size | queried? |
|---|---|---|
| `raw` (archived source JSON) | 174 MB | **never** |
| `description` | 176 MB | not currently (`SEARCH_AD_TEXT = False`) |
| `title` | 7.4 MB | yes |
| `occupation` | 4.4 MB | yes |

**~12 MB of the corpus is actually searched. 350 MB is archive ballast in the hot
database**, paid for twice: storage price, and the RAM needed to cache past it. This is
host-independent and matters more than the hosting choice (§7).

---

## 2. Decision drivers

1. **Founder engineering time is the scarce resource**, not dollars. At 10–15 GB,
   storage is inexpensive on every candidate platform.
2. **No unplanned degradation.** A database that silently becomes unresponsive is
   disqualifying.
3. **Durability of the 11.5 MB**, especially `receipts`.
4. **Low operational burden** — effectively a one-person team.
5. **Compliance trajectory.** GDPR now; SOC 2 later, including subprocessor attestations.
6. **Connection behaviour.** The shared session pooler exhausted (`ECHECKOUTTIMEOUT`)
   under slow queries, taking down endpoints unrelated to search.

---

## 3. Options considered

### Option A — Supabase Pro **(chosen)**

| | |
|---|---|
| **Cost** | $25/mo including 8 GB disk; **automatic disk expansion** beyond that at $0.125/GB. Compute: Micro (1 GB) included, **Small (2 GB) ≈ $30/mo**, Medium (4 GB) ≈ $75/mo. |
| **Backups** | Managed daily, 7-day retention, plus managed database maintenance. |
| **Upgrades** | Managed, including major versions. |
| **Compliance** | **Supabase is SOC 2 Type 2 compliant as a vendor.** Access to the audit *report* requires Team/Enterprise — relevant later for HR-sector customer security reviews. |
| **Connections** | Direct connection (or paid dedicated pooler) recommended for persistent backends; the shared session pooler is the component that failed here. |

**Pros:** no migration; managed backups and upgrades; storage cost negligible at the
projected 10–15 GB; vendor SOC 2 posture already in place; the workload was never shown
to exceed its capability.

**Cons:** the quota cliff persists **if Spend Cap stays enabled**; the shared pooler must
be deliberately avoided.

### Option B — Railway Postgres **(rejected)**

**Pros:** colocated with the API; usage-based billing; direct private connection with no
pooler in the path. **Railway does offer snapshots and PITR** — the first draft of this
ADR claimed otherwise and was wrong.

**Cons:**
- Railway's own guidance still recommends an **additional portable `pg_dump` layer**, so
  disaster-recovery design remains partly the team's responsibility.
- More of the database lifecycle is owned by us — it is a deployed Postgres container,
  not a managed database platform.
- Pricing is $10/GB-month RAM, $20/vCPU-month, $0.15/GB-month storage. At this size the
  saving is **modest and unpredictable** — nowhere near enough to justify taking on
  additional database ownership.

**Rejected because** its apparent advantage was cost, and that advantage does not survive
contact with the actual numbers.

### Option C — Neon (rejected for now)

Managed, autoscaling, branching, PITR, scale-to-zero, pgvector. Storage priced
significantly higher per GB — the wrong shape for a deliberately large corpus. Strong
candidate for **dev/staging branches**, not the primary store.

### Option D — AWS RDS (deferred, not rejected)

Best-in-class durability: automated backups, PITR to 35 days, managed major upgrades,
Multi-AZ. Strongest compliance story. Adds a third cloud and real setup complexity for a
pre-revenue project. **This is the comparison to run at the §8 revisit triggers** — not
Railway.

### Option E — Self-managed (Hetzner or similar) — rejected

Cheapest per GB and per core, EU-domiciled. But patching, backups, upgrades, monitoring
and security all become manual, which harms the SOC 2 trajectory (patch management and
change control become manual evidence) and consumes the scarcest resource.

---

## 4. Decision

**Upgrade to Supabase Pro. Remain on Supabase.**

Reasoning, in order:

1. The outage was a **quota breach**, not a capability ceiling. Removing the quota
   removes the cause.
2. **Storage is cheap on every candidate** at 10–15 GB. Choosing a platform to save on
   storage optimises the wrong variable.
3. Railway's cost advantage is **modest and unpredictable**, and is paid for in database
   ownership — the wrong trade when founder time is the constraint.
4. Managed backups, managed maintenance and managed major-version upgrades are worth more
   than colocation at this stage.
5. Supabase's existing **SOC 2 Type 2** posture supports the compliance trajectory in
   ARCHITECTURE.md §4 in a way self-managed Postgres does not.

Railway Postgres should be chosen **only if colocation produces a demonstrated latency or
throughput advantage that Supabase Pro cannot meet.** No such measurement exists.

---

## 5. Consequences

### Positive
- Immediate: throttling ends, no migration, no data movement, no downtime.
- Managed backups and upgrades stay off the team's plate.
- Storage growth is a small predictable line item, not an architectural event.

### Negative — accepted, with mitigations
| consequence | mitigation |
|---|---|
| Quota cliff persists if Spend Cap remains enabled | **Disable the spend cap and configure billing alerts** (§6.3). Paid projects auto-expand past 8 GB; leaving the cap on recreates the exact failure this ADR responds to. |
| Managed backups are still someone else's process | Keep an independent periodic `pg_dump` — 11.5 MB for the irreplaceable slice (§1.3) makes this trivial. |
| Shared session pooler remains available and is a footgun | Use a **direct connection** (or the paid dedicated pooler) from the persistent FastAPI backend. |
| Vendor SOC 2 *report* needs Team/Enterprise | Not required until a customer security review demands it; a revisit trigger (§8). |

---

## 6. Implementation

1. **Upgrade to Supabase Pro immediately.** Requires adding a payment method — the
   account currently has none and $0 credit.
2. **Start on Micro, benchmark, move to Small if searches still struggle.** Expected
   production budget ≈ **$30/mo**.
3. **Disable the spend cap; add billing alerts.** Non-optional — the cap is the mechanism
   that produced the outage.
4. **Move unqueried `raw` JSON (174 MB) to object storage**, and eventually the CV
   binaries in `candidate_documents`. ~350 MB of current bulk is not part of the active
   search path.
5. **Use a direct connection, not the shared session pooler**, from the backend.
6. **Keep an independent portable dump** on a schedule despite managed backups, and
   **rehearse a restore once.**

---

## 7. Explicitly not decided here

Independent of hosting, and more consequential at scale:

- **`raw` → object storage** (§6.4).
- **`tsvector` + GIN replacing trigram** for word matching — smaller, faster, handles
  German compounds.
- **Nightly-refreshed employer roll-up table**, so search stops aggregating the whole
  corpus per query. At the ~709,700-posting target this matters more than hardware.
- **Whether `SEARCH_AD_TEXT` returns to `True`** — depends on benchmarks against an
  unthrottled instance.

---

## 8. Revisit triggers

Reopen when any of these becomes true — and compare against **managed Postgres such as
AWS RDS**, not Railway:

1. Database approaches **~50 GB**.
2. A customer requires an **SLA or PITR guarantee**.
3. An **enterprise security review** demands the SOC 2 report (needs Team/Enterprise).
4. The **irreplaceable slice stops being small** — if tenant data approaches corpus size,
   §1.3 no longer holds and the durability analysis must be redone.

---

## 9. Corrections to the first draft

Recorded because the errors changed the recommendation:

| claim in first draft | correction |
|---|---|
| "Railway has volume snapshots but **no PITR**." | **Wrong.** Railway offers snapshots and PITR; it still recommends an additional portable `pg_dump` layer. |
| "**No SOC 2 at this tier** — SOC 2 appears only on Team ($599)." | **Conflated two things.** Supabase is SOC 2 Type 2 compliant *as a vendor*; Team/Enterprise gates access to the audit *report*. The vendor posture exists at Pro. |
| "Pro just moves the quota cliff from 500 MB to 8 GB." | **Misleading.** Paid projects **auto-expand** past 8 GB at $0.125/GB. The cliff is a consequence of the **spend cap**, not the plan. |
| "Railway lands in the tens of dollars vs Supabase's ~$110+." | **Overstated.** Supabase Small (2 GB) ≈ $30/mo. Railway's saving at this size is modest and unpredictable. |

The first draft also over-weighted colocation — a real but unmeasured benefit — against
managed backups and upgrades, which are concrete and immediate.

---

## 10. Evidence appendix

Measured 2026-09-05 against the live database.

```
TOTAL DATABASE: 654 MB          (Free quota: 500 MB)
  hub_job_postings   567 MB   (488 MB table + 80 MB indexes)
    raw          174 MB   never queried
    description  176 MB   unused while SEARCH_AD_TEXT=False
    title        7.4 MB
    occupation   4.4 MB
  hub_companies       61 MB
  candidate_documents  9.1 MB
  receipts             1.4 MB

RE-CRAWLABLE   630.9 MB  (98.2%)
IRREPLACEABLE   11.5 MB   (1.8%)

select count(*) from generate_series(1,1000000)  ->  8,284 ms   (healthy ~80 ms)
81 rows by primary key, fully cached             ->  2,054 ms   (healthy ~2 ms)
count(*) hub_companies (81,540 rows)             ->  timeout at 180 s
```

Trigram indexes from migration 0016 work and are **not** the bottleneck:

```
Bitmap Index Scan on ix_hub_posting_title_trgm       actual time=0.085 ms  rows=96
Bitmap Index Scan on ix_hub_posting_occupation_trgm  actual time=0.030 ms  rows=37
```

### Sources
- Supabase pricing — https://supabase.com/pricing
- Supabase backups — https://supabase.com/docs/guides/platform/backups
- Supabase SOC 2 — https://supabase.com/docs/guides/security/soc-2-compliance
- Supabase database size / disk expansion — https://supabase.com/docs/guides/platform/database-size
- Supabase connection guidance — https://supabase.com/docs/guides/database/connecting-to-postgres
- Railway backups & restores — https://docs.railway.com/guides/postgres-backups-restores
- Railway pricing — https://docs.railway.com/pricing/plans
