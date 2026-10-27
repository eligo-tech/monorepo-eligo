---
name: finishing-a-development-branch
description: Merge, PR, and cleanup. Load once the work is green and reviewed.
---

# Finishing — integrate without leaving debris

## Before opening the PR
- `git status --porcelain` — read every line. Nothing unrelated is staged.
- `git diff origin/main --stat` — does the shape match the plan?
- Full suite green locally (backend pytest, frontend typecheck + build).
- Secrets: nothing committed. `/data/` is gitignored and stays that way.

## The PR body states
1. What changed and **why** — the defect or the need, not the diff.
2. The evidence: the commands run and what they printed (see `07`).
3. What is deliberately **not** done, and why.
4. Anything needed after merge (a Railway variable, a migration, a rotation).

Claims in the PR body are held to the same standard as claims in chat. If an
"action needed after merge" turns out to be unnecessary, correct it before
merging — PR #180 shipped with a comment doing exactly that, after a probe
showed `tenant_sources` was empty in production and the stated follow-up was
moot.

## Merging
- CI green on **every** job before merge. A cancelled job is not a pass:
  matrix fail-fast cancels siblings, and Railway reports "Failed to build an
  image" with no logs when a newer merge cancelled the build.
- Squash merge.
- **After a squash merge the branch is dead.** Do not push to it again. Cut a
  new branch from the updated `origin/main` for follow-ups.
- Delete the merged branch locally and on the remote.

## After merging
- Watch the deploy. A merge is not a deploy, and a deploy is not a working
  deploy — check the log line that proves the new code is running.
- Update `data/design/TODOS.md` if the change opened or closed an item.

## Prohibited
- Merging with a red or cancelled job and "it's unrelated".
- Leaving a branch half-merged across two PRs.
- Reporting "merged and deployed" without having seen the deploy succeed.
