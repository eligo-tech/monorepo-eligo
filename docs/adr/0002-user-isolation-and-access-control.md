# ADR 0002 — Who may see what: membership, roles and per-user scope

- **Status:** Proposed
- **Date:** 2026-10-21
- **Deciders:** Dmitry Fadeev
- **Decision:** Keep **one tenant per Clerk organization** and keep isolation in the
  **database**. Split authorization into three independent questions — *which
  workspace*, *is this person admitted to it*, *what may they see inside it* — and
  answer each with its own mechanism. Make admission **explicit** instead of
  automatic (Phase 1), and add a **company-grained scope** for restricted members
  on the client side of the record only (Phase 2). **Never scope the candidate
  pool**, because hiding rows from the matcher silently degrades its output.
- **Related:** [`ARCHITECTURE.md`](../../ARCHITECTURE.md) RULE 3 + §4 · `backend/CLAUDE.md` §2.3 ·
  [ADR 0001](0001-database-hosting.md) · Linear **ELI-12**

---

## 1. Context

Two users of one design partner — Thomas Bausch and Jonas Albrecht — must work the
same jobs and candidates. Their organization has further people who should see
**only certain areas or certain client companies**. Separately, a person who signs
up but has not been admitted must be able to reach **nothing**.

Three different questions hide inside that sentence, and the system today answers
one of them well, one by accident, and one not at all.

| Question | Mechanism today | State |
|---|---|---|
| Which workspace is this request in? | Clerk `org_id` → `tenants.id` → Postgres RLS on `app.current_tenant` | **Works, fail-closed** |
| Is this person admitted to that workspace? | Clerk org membership, and a tenant is minted for any org that presents itself | **Automatic — nobody approves anything** |
| What may this person see inside the workspace? | Nothing exists. Every member sees the whole workspace. | **Absent** |

### 1.1 What is actually enforced today — measured, not assumed

**Tenant isolation is real and it is in the database.** `get_current_actor`
(`backend/app/core/auth.py`) verifies the Clerk JWT, requires an active
organization (403 without one), maps `org_id` → `tenant_id`, and sets
`app.current_tenant` as a per-transaction GUC. The policy on every tenant table is

```sql
tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
```

with `FORCE ROW LEVEL SECURITY`, so an unset GUC yields NULL and therefore **zero
rows** rather than all of them. The deployment connects as `eligo_app`, a
`NOBYPASSRLS` **login** role (verified in `backend/.env`:
`ELIGO_DB_APP_ROLE=eligo_app`, password set, and the connection user is
`eligo_app.<project>`). That is the strong configuration — the connection itself
cannot bypass RLS, so an un-pinned query returns nothing even if application code
forgets its `WHERE`.

**All 17 tenant-scoped tables carry a policy** — I checked each migration rather
than trusting the one list in the repo:

| migration | tables given `tenant_isolation` |
|---|---|
| 0003 | `candidates` `jobs` `companies` `applications` `receipts` `enrichment_records` |
| 0005 | `candidate_documents` `match_receipts` |
| 0008 | `hub_company_link` |
| 0010 | `saved_searches` |
| 0019 | `managers` `manager_interactions` |
| 0025 | `projects` `project_companies` |
| 0026 | `process_steps` |
| 0028 | `application_assessments` |
| 0031 | `tenant_sources` |
| 0037 | `tenant_feature_consents` `interviews` |

**But `scripts/apply_rls.py` lists only 8 of those 17.** Deployed databases are
safe because the Dockerfile runs `alembic upgrade head` on every deploy. A database
brought up the *other* documented way — `create_all` on startup, then
`python -m scripts.apply_rls` — gets tables with no policy for the nine tables the
script does not name, including `managers`, `manager_interactions` and
`candidate_documents`'s siblings. That is the path a second customer's own database
would take. The list is hardcoded where it could be derived from the model
registry.

**`auth_enabled=false` cannot reach production.** `assert_auth_configured` refuses
to boot a Postgres deployment with authentication off. Good.

**Ingestion is machine-only.** `get_ingest_tenant` has no fallback to the user path
and `tests/test_operator_endpoints.py` attacks every operator route with a valid
user session. Good.

### 1.2 The four gaps

**G1 — Production runs on a Clerk *development* instance.** The publishable key is
`pk_test_…` (frontend `.env`, and the Clerk dashboard header reads
"development"). A development instance is not a hardened sign-in surface: it is
capped at 100 users, its sign-up is open to anyone who reaches the Frontend API,
and its issuer and JWKS are the development ones. The production database sits
behind it. This is the single largest exposure on the list and it is a
configuration change, not code.

**G2 — A tenant is created for any organization that asks.**
`tenants.get_or_create` mints a workspace on first sight of an `org_id`. Combined
with `AuthGate`, which renders Clerk's `<OrganizationList>` with
`afterCreateOrganizationUrl` for anyone signed in, the product today says: sign up,
create an organization, receive a workspace in the production database. Such a
person cannot read Thomas's rows — RLS holds, their tenant is different and empty —
but "they get nothing" is true only because their workspace is empty, not because
anything refused them. **Nobody approves a new workspace.** That is the literal
answer to "how do I stop unapproved users", and it is the gap.

**G3 — Clerk's own joining rules are the real door, and they are not in this
repo.** If *Verified domains → automatic enrollment* is enabled on the
organization, anyone who signs up with a matching email address joins Thomas's
organization and therefore his tenant, with full access, without an invitation.
Equally, "members may create organizations" governs G2. These are dashboard
settings; the code cannot compensate for them, so they must be written down as part
of the decision and checked.

**G4 — There is no per-user identity in the record at all.** One column in
seventeen tenant tables references a user: `tenant_feature_consents
.accepted_by_user_id`. Receipts carry an `agent` string and a *display name*, never
the stable Clerk `sub`. Two people with the same name are indistinguishable in the
audit trail, and a rename rewrites history. Worse, `POST /applications/{id}/status`
and `/stage` still take `actor` **from the request body**
(`StatusTransition.actor: str = "recruiter"`) — the browser is asked who it is,
which is the exact pattern `core/auth.py`'s own docstring says was removed. Access
control per user is not meaningful without attribution per user.

### 1.3 Why ELI-12 probably is not a code bug

"Jonas should see same data as Thomas" has the shape of a configuration symptom:
if the two are in **different Clerk organizations**, each resolves to a different
`tenant_id` and they correctly see different, separate workspaces. The fix is then
one action in Clerk — one organization, both as members — and no code at all. The
Clerk screenshot shows the *Users* tab, which cannot distinguish the two cases.
**Check Organizations → is there one organization with both as members?** Only if
they already share one organization and still see different data is there a bug,
and I would then look at whether the frontend is sending the right active
organization rather than at the backend.

---

## 2. Decision drivers

1. **Isolation belongs in the database.** ARCHITECTURE.md already states it, RLS
   already implements it, and the pattern survives a forgotten `WHERE`. A
   per-user scheme enforced only in service code would be weaker than the tenant
   scheme sitting underneath it, and the weaker layer is the one that decides.
2. **Fail-closed, including on the new axis.** An unresolvable member must see
   zero rows, exactly as an unset tenant does.
3. **Clerk is identity; authorization is ours.** Clerk answers *who signed in* and
   *which organization is active*. Whether that person is admitted, and what they
   may see, is product state with an audit trail — it cannot live only in a SaaS
   dashboard where a mis-click silently grants access to personal data.
4. **Do not invent roles nobody has.** `core/auth.py` is deliberate about this:
   "Every role scheme grows, and the ones that start with five are guesses about a
   workload nobody has run yet." Two roles exist. Add the third axis only where a
   real user needs it, and make the default *unrestricted*.
5. **Personal data raises the cost of a mistake.** `candidates` and `managers`
   hold personal data under GDPR. An over-broad grant is a disclosure, and Art. 30
   wants to know who accessed what.
6. **The matcher must see the whole pool.** This constrains the design more than
   anything else in this list — see §4.3.

---

## 3. Options considered

### Option A — Clerk roles and permissions only, enforced from the JWT **(rejected)**

Put everything in Clerk: custom roles, custom permissions, read them from
`org_permissions` in the token.

Cheap, and it is already how `require_admin` works. But it cannot express "Petra
sees only Linde and Wiemann": Clerk permissions are a flat capability set, not a
row predicate, and the identifiers of our companies are not Clerk's to hold.
Enforcement would also be back in application code, below the standard the tenant
axis already meets. Keep Clerk for identity and for the two coarse roles; do not
grow it into the authorization store.

### Option B — Service-layer filtering, a `visible_company_ids` argument everywhere **(rejected)**

Pass the member's scope into every service function and add it to every query.

Correct where it is applied and absent where it is forgotten, with no backstop.
There are ~17 tenant tables and dozens of query sites; the first missed one is a
silent disclosure of personal data that no test would notice. This is precisely
the design RLS exists to replace.

### Option C — A second RLS axis: `app.current_member`, scope held in our tables **(chosen)**

Mirror what already works. The request sets a second GUC alongside
`app.current_tenant`; the policy on the client-side tables gains a disjunct that
is `true` for unscoped members and an `EXISTS` against an indexed scope table for
scoped ones. Membership and scope are ordinary tenant-scoped tables with receipts
on change.

Costs one extra `EXISTS` per scoped query, needs the scope to be expressible as a
company id on (or one join from) each row, and needs the member row resolved once
per request. All three are acceptable; §4.3 and §6 state where the model does not
reach.

### Option D — Separate workspaces per sub-team **(rejected)**

Give the restricted people their own Clerk organization.

It already works and needs no code. It is also the wrong product: separate tenants
cannot share a candidate pool, a mandate or a process, which is the collaboration
Thomas and Jonas asked for. Worth remembering as the answer for a genuinely
separate business unit; not an answer for "same team, narrower view".

---

## 4. Decision

### 4.1 Three questions, three mechanisms — do not conflate them

```
WHICH WORKSPACE    Clerk org_id → tenants.clerk_org_id → app.current_tenant
                   enforced by: RLS policy tenant_isolation       [exists]

ADMITTED?          workspace_members row, status='active'
                   enforced by: get_current_actor → 403           [Phase 1]
                   Clerk membership is NECESSARY, never SUFFICIENT

WHAT INSIDE?       role (capability)  +  scope (rows)
                   enforced by: require_area / require_admin      [Phase 2]
                             +  RLS disjunct on app.current_member
```

The second line is the rule that makes the whole thing safe:
**Clerk can only take access away, never grant it.** A request is admitted when the
token carries a valid organization **and** our own `workspace_members` row for that
`(tenant, user)` is `active`. A membership added in the Clerk dashboard by itself
grants nothing; a membership removed there revokes immediately, because the org
claim disappears from the next token.

### 4.2 Schema

```sql
-- Admission and capability. One row per person per workspace.
workspace_members
  id            uuid pk
  tenant_id     uuid not null                      -- RLS as every other table
  clerk_user_id text not null                      -- the stable `sub`, not a name
  role          text not null  -- 'admin' | 'recruiter'      (the two that exist)
  status        text not null  -- 'invited' | 'active' | 'suspended'
  areas         jsonb not null default 'null'      -- null = every area; else a list
  scope_mode    text not null default 'all'        -- 'all' | 'companies'
  display_name  text,  email text                  -- cached from the token, for lists
  approved_by   text,  approved_at timestamptz     -- who admitted them, when
  unique (tenant_id, clerk_user_id)

-- Row scope. Consulted only when scope_mode='companies'.
member_company_scopes
  id            uuid pk
  tenant_id     uuid not null
  member_id     uuid not null references workspace_members(id) on delete cascade
  company_id    uuid not null references companies(id)         on delete cascade
  unique (member_id, company_id)
```

Both carry `tenant_id` and the standard `tenant_isolation` policy — they are
tenant record rows like any other (ARCHITECTURE.md classification: *tenant record*,
not *personal data*; they hold a Clerk id and a role, not a profile).

Three deliberate choices:

- **`areas` defaults to NULL meaning "all".** A new member is unrestricted within
  their workspace. Restriction is something an admin does on purpose, which keeps
  the common case free of configuration and makes the restricted case visible.
- **Scope is stored at the `companies` grain, not the project grain**, even though
  `projects`/`project_companies` already exist and read like the natural unit. A
  project points at **corpus** companies (`hub_company_id`), while everything that
  needs scoping — `jobs.client_company_id`, `managers.company_id` — points at the
  tenant's own `companies` row, reachable only through `hub_company_link`. Making
  the policy traverse that is three joins inside an `EXISTS` on every query, and it
  silently widens a member's view whenever someone adds a company to a project.
  "Grant every company in project X" stays a **UI convenience that expands at grant
  time** into explicit rows: the admin sees exactly what they granted, and a later
  addition to the project does not quietly extend it.
- **`role` keeps the two values that exist.** Scope is orthogonal: a recruiter may
  be scoped or not. Resist a third role until someone needs one.

### 4.3 What is scoped, and the one thing that must not be

| table | scope key | policy disjunct |
|---|---|---|
| `companies` | `id` | direct |
| `jobs` | `client_company_id` | direct · **NULL ⇒ invisible to scoped members** |
| `managers`, `manager_interactions` | `company_id` (via `manager_id`) | one join |
| `applications` | `jobs.client_company_id` | one join |
| `process_steps`, `application_assessments` | via `applications` | two joins |
| `projects`, `project_companies` | — | by `areas`, not by company |
| **`candidates`, `candidate_documents`, `interviews`** | — | **never row-scoped** |

**The candidate pool is never row-scoped, and this is the most important line in
the ADR.** `matching.apply_hard_filters` and the LLM re-rank run over the pool. If
RLS hides half of it from a scoped recruiter, the matcher returns a shortlist that
*looks* complete and is not — a silent, invisible degradation of the one output the
product exists to produce, in a system whose stated invariant is that an
unverifiable claim must never look verified. The candidate side is governed by the
**area** axis instead: a member either has `kandidaten` or does not. `interviews`
hangs off `candidate_id` with no job, so it follows candidates; `manager_interactions`
may have a null `manager_id` (migration 0034) and those rows follow the same
fail-closed rule as a company-less job — invisible to a scoped member.

`jobs.client_company_id` being nullable deserves the same emphasis: 
a mandate with no client company resolves to no scope, and **fail-closed means a
scoped member does not see it.** An admin who wants it seen assigns the company.

### 4.4 Capability (role and area) is enforced in the router, not the UI

Hiding a screen in `CockpitShell` is cosmetic — the API is reachable with curl.
Each router gains `Depends(require_area("kandidaten"))`; the UI hides what the
member's `areas` exclude so the product does not show doors that will not open.
`require_admin` widens from data sources to also cover member and scope management.

---

## 5. Consequences

### Positive

- A new user who has not been admitted reaches **403 at the door**, not an empty
  workspace by luck.
- The per-user axis is enforced where the per-tenant axis already is, so a
  forgotten `WHERE` in a new service function fails closed instead of disclosing.
- The audit trail finally names a person (`clerk_user_id`), which Art. 30 wants and
  which makes "who moved this candidate to Offer" answerable.
- Membership and scope changes leave receipts, so a widened grant is visible after
  the fact.

### Negative — accepted, with mitigations

- **One extra `EXISTS` per scoped query.** Only for members with
  `scope_mode='companies'`; the unscoped path short-circuits on a boolean. Indexed
  on `(member_id, company_id)`. Measure before scoping a hot table.
- **Two sources of membership truth (Clerk and ours) can drift.** Mitigated by the
  direction rule — Clerk can only revoke — plus `organizationMembership.*` webhooks
  to create the `invited` row, with the request-time check as the backstop. Never
  rely on a webhook alone; they are missed.
- **An admin can lock a workspace out of itself** by suspending the last admin.
  Refuse the last active admin's demotion or suspension, in the service, with a
  test.
- **Scope is a maintenance burden** that grows with the client list. That is the
  real cost of the feature and it belongs to whoever asks for it; the "expand a
  project at grant time" affordance is the mitigation.

---

## 6. Explicitly not decided here

- **Field-level redaction** (e.g. a member who sees a candidate but not their
  salary expectation). Not asked for; it is a different mechanism (column
  privileges or a view) and should not be smuggled into the row axis.
- **Sharing one candidate pool across tenants.** Still forbidden; RULE 3 stands.
- **Erasure.** A suppression list is still unbuilt (ARCHITECTURE.md §3) and nothing
  here changes that.
- **Whether the matcher should *present* only in-scope results to a scoped member.**
  §4.3 says the pool is never hidden from the matcher. Whether the ranked output is
  then filtered on the way out is a product question, and the honest answer must
  show the count it withheld rather than silently shortening the list.

---

## 7. Implementation

**Phase 1 — close the door. Small, and none of it needs the new tables.**

1. **Move Clerk to a production instance** (`pk_live_…`). The backend derives JWKS
   and issuer from the publishable key, so this is environment variables on Vercel
   and Railway plus a re-verification of sign-in. *(G1)*
2. **Set the Clerk organization rules, and record them here once chosen:**
   members **may not** create organizations; verified-domain **automatic enrollment
   off**; joining by invitation only. *(G3)*
3. **Stop auto-provisioning tenants.** `tenants.get_or_create` becomes
   `tenants.get` on the request path: an organization with no tenant row is
   **403 "workspace not provisioned"**. Provisioning becomes an explicit operator
   action. *(G2 — this is the direct answer to "unapproved users see nothing")*
4. **Remove the client-supplied `actor`** from `StatusTransition` and `StageMove`;
   take it from `get_current_actor` like every other router already does. Persist
   `clerk_user_id` alongside the display name wherever an actor is recorded. *(G4)*
5. **Derive `apply_rls.TABLES` from the model registry** instead of hardcoding, and
   add a test asserting every `TenantMixin` table is covered. *(§1.1)*
6. **Write the isolation test that does not exist.** `tests/test_tenant_isolation.py`:
   two tenants, each with a candidate, job, manager and application; then drive
   every GET and LIST route from the router table with tenant B's identity and
   assert tenant A's ids never appear — table-driven, so a new domain is covered
   the day it is added. Plus a Postgres-only pair: the GUC unset returns zero rows,
   and `eligo_app` cannot `SET ROLE` out of itself.
7. Optionally verify `azp` against the known frontend origins.

**Phase 2 — the scope axis. Build when a real member must see less.**

8. Migration: `workspace_members`, `member_company_scopes`, both with
   `tenant_isolation`. Backfill one `active` admin row per existing tenant.
9. `get_current_actor` resolves the member row, sets `app.current_member`, and
   carries `areas`/`scope_mode` on `Actor`. No row ⇒ 403.
10. Extend the policies in §4.3. One migration per table group, each with a test
    that a scoped member sees exactly the granted companies and that a null scope
    key is invisible.
11. `require_area` on the routers; member management under `require_admin`; a
    receipt on every membership and scope change.
12. Settings screen: members, their role, their areas, their companies — and
    "grant every company in project X" expanding to explicit rows.

**Order matters.** Steps 1–3 remove a live exposure and take hours. Steps 8–12 are
a feature and should wait for the user who needs it.

---

## 8. Revisit triggers

- A customer asks for field-level redaction → §6 reopens.
- A scoped query shows up in slow logs → reconsider a materialised
  `member_visible_companies`.
- A second customer onboards onto their own database → re-check §1.1's
  `create_all` + `apply_rls` path before anything else.
- Clerk ships organization-scoped row permissions → re-read Option A.

---

## 9. Evidence

Read on 2026-10-21 at `685b5e0`.

| claim | where |
|---|---|
| Tenant GUC, fail-closed predicate, `FORCE` | `backend/app/core/auth.py:_set_tenant_guc`, `backend/scripts/apply_rls.py:PREDICATE` |
| App role is `NOBYPASSRLS` login-mode | `backend/.env` (`ELIGO_DB_APP_ROLE=eligo_app`, password set, URL user `eligo_app.…`) |
| 17 tenant tables, all with policies in migrations | §1.1 table; `grep TenantMixin backend/app/domain/*/models.py` |
| `apply_rls.TABLES` names 8 | `backend/scripts/apply_rls.py:TABLES` |
| Tenant minted on first sight of an org | `backend/app/domain/tenants/service.py:get_or_create` |
| Anyone signed in may create an organization | `frontend/src/auth/AuthGate.tsx:OrgGate` |
| Clerk instance is `pk_test_` | `frontend/.env`, `backend/.env` |
| `require_admin` covers only sources, imports, feature consent | `grep -rn require_admin backend/app` → 3 routers |
| Client-supplied actor | `backend/app/domain/pipeline/schemas.py:43,50`, `router.py:75,95` |
| Only user column in the record | `backend/app/domain/features/models.py:29` |
| No cross-tenant isolation test | `ls backend/tests | grep -iE 'rls|tenant|isolation'` → config tests only |
