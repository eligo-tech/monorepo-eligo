---
name: using-superpowers
description: Bootstrap for feature work in this repository: the dispatch table naming which rule applies, and the four gates that are never skipped. Loaded automatically at session start by .claude/hooks/session-start.sh; invoke it directly to re-read the rules after a long session or a compaction.
tools: Read, Glob, Grep
---

# Start here

Nine skills, adapted from the Superpowers plugin (`docs/setup/3_agent_use_2.pdf`)
to the defects **this** repository has actually shipped. Each one names the
incident that bought it, because a rule without a scar gets argued away.

This file is injected at every session start. **The other eight are skills:
invoke them by name** (`brainstorming`, `test-driven-development`, …) — either
because the table below says to, or because the user asks for one.

**The rules are not advice. They are entry conditions.** A feature that skips
one is not "done faster", it is untested, unverified, or unreviewed.

## Dispatch

| If the work is… | Load |
|---|---|
| a vague ask, no agreed shape yet | `brainstorming` |
| an agreed shape, no task list yet | `writing-plans` |
| about to touch files | `using-git-worktrees` |
| new behaviour or a bug fix | `test-driven-development` |
| something is broken and the cause is unclear | `systematic-debugging` |
| code written, not yet reviewed | `requesting-code-review` |
| about to say "done" / "working" / "fixed" | `verification-before-completion` |
| green and reviewed | `finishing-a-development-branch` |

Domain rules are separate and still binding: `ARCHITECTURE.md`,
`backend/CLAUDE.md` §2, and `.claude/skills/architecture-review`. This file
governs *how* you work; those govern *what is allowed to exist*.

## The four gates — never skipped, never "just this once"

1. **Design before code.** No implementation until the user approves a shape.
   (`brainstorming`)
2. **A failing test before a fix.** The test must fail for the stated reason
   against the unfixed code, and you must have *seen* it fail. (`test-driven-development`)
3. **Evidence before "done".** A claim of success names the command and quotes
   its output. "Should work", "looks right", and a green suite that never
   exercised the path are not evidence. (`verification-before-completion`)
4. **Review before merge.** Against the plan, not against vibes. (`requesting-code-review`)

## The two failure modes this repo keeps hitting

**Asserting instead of checking.** `repopulate_cvs.py` was described three
different ways in one session — "unfiltered cross-tenant DELETE", then "inert
dead code", then finally the truth — because `git ls-files` showed nothing and
nobody ran `ls`. The directory was gitignored and held 46 real CVs.
→ Before describing what code does, read it and run it. `systematic-debugging`.

**A check that cannot fail.** `GET /register → 200` was reported as
"registration is open" four times. GlitchTip is an SPA; every unknown path
returns 200 with the shell. The check could not distinguish open from closed.
→ Before trusting a check, make it fail on purpose. `verification-before-completion`.

## Scope

"ANY feature" means any change to `backend/app/`, `frontend/src/`,
`backend/migrations/`, CI, or deploy configuration. A typo fix in a comment is
not a feature. If you are unsure, it is a feature.
