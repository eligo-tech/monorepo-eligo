---
name: requesting-code-review
description: Review the implementation against the plan before merge.
---

# Code review — against the plan, not against taste

## Entry conditions
Code written, tests green, not yet merged.

## Procedure
1. Run `/review-changes` (harsh reviewer: correctness, complexity, blast
   radius, coverage, consistency, YAGNI).
2. If the diff touches the hub, tenancy, RLS, ingestion, a migration, or
   personal data — also run `.claude/skills/architecture-review` and report
   each new table/column's row in the classification table.
3. Re-read the **full** changed files, not the diff. A diff hides what it is
   adjacent to.
4. Check the diff against the plan from `02-writing-plans`: anything in the
   diff that is not in the plan must be justified or removed.

## Checks this repo specifically needs
- **Migration**: does it carry an RLS policy? Is it idempotent against
  `create_all`? Has it been exercised `upgrade → re-run → downgrade →
  re-upgrade` on real Postgres, not SQLite?
- **New dependency**: are both `requirements.lock` and `requirements-dev.lock`
  recompiled with `--no-header`, and do they agree?
- **Error paths**: would a crash here carry a candidate's data into a log or a
  crash report? (`backend/app/core/observability.py`)
- **i18n**: new UI strings added to `frontend/src/i18n/en.ts` **in place**.
  Never re-sort the file — a 5-line addition once became a 515-line diff.
- **Tenant scope**: does every new query run under RLS, or does it use an
  admin session that bypasses it?

## Prohibited
- Approving your own work by restating the plan as if it were evidence.
- "Minor, will fix in follow-up" on anything touching tenancy or personal data.

## The incident
A reviewer's check confirmed the frontend had no path to ingestion and stopped
there — while the backend dependency still fell back to the human path. The
rule was stated in a way the code visibly contradicted, so it read as
aspiration. `ARCHITECTURE.md` RULE 1 was rewritten in three parts, and
enforcement moved into `backend/tests/test_operator_endpoints.py`, which
introspects the route set rather than grepping for it.
