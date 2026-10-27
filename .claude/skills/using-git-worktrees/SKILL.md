---
name: using-git-worktrees
description: Set up an isolated branch or worktree before editing anything. Use before the first edit of any change: branching from the latest origin/main, never re-pushing to a squash-merged branch, never staging with git add -A, and never committing under /data/.
tools: Read, Bash
---

# Branches and worktrees — never work on main

## Hard constraints
- **Always cut from the latest `origin/main`:**
  `git fetch origin && git checkout -b <type>/<slug> origin/main`
- **Never re-push to a branch that was squash-merged.** Its commits no longer
  exist upstream; pushing recreates them. Cut a new branch.
- **Never commit to `main` directly.**
- **Never `git add -A`.** Stage named paths. `git add -A` once swept two
  unrelated PDFs into a dependency-pinning PR.
- Run `git status --porcelain` before committing and read every line.

## When a worktree earns its keep
Use `git worktree add ../eligo-<slug> -b <type>/<slug> origin/main` when the
change is long-running, or when you need the old tree available at the same
time (comparing behaviour before/after, running two test suites). For a normal
feature a branch is enough.

## Before the first edit
- `git fetch origin && git log --oneline -3 origin/main` — know what you are on
  top of.
- Confirm the working tree is clean. Uncommitted work from a previous task
  silently becomes part of yours.

## Prohibited
- Committing anything under `/data/` (gitignored — it holds real CVs and
  tenant exports).
- Committing a file you have not read in full.
