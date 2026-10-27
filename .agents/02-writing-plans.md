---
name: writing-plans
description: Decomposes an approved design into concrete, verifiable tasks.
---

# Writing plans — tasks that can be checked off honestly

## Entry conditions
A design the user approved (`01-brainstorming` step 6).

## Procedure
1. Decompose into tasks that are each **independently verifiable**. A task you
   cannot prove is finished is not a task, it is a hope.
2. For each task name: the files it touches, the test that proves it, and the
   command that runs that test.
3. Order so the **riskiest unknown is resolved first**. If something will sink
   the design, find out on day one.
4. Mark every task that needs a migration, touches RLS, or changes a public
   contract — those get `.claude/skills/architecture-review` before they merge.
5. State explicitly what is **out of scope**, so scope creep is visible.

## Prohibited
- A task called "fix tests" or "cleanup". Name what and why.
- Bundling an unrelated improvement into a feature branch. Open a second PR.
- Planning work whose verification step is "check manually" when a test could
  do it.

## The incident
Pinning dependencies (PR #181) began as "add a lock file". The real plan had
four parts — lock, Dockerfile, CI staleness guard, and a cross-lock assertion —
and three of them were discovered *during* implementation. The CI guard shipped
broken on the first attempt because `uv` stamps `--output-file` into the lock
header, so the comparison could never pass. A plan that had named "prove the
guard fails when the lock is stale" as its own task would have caught it before
CI did.
