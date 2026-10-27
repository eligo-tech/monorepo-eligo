---
name: using-superpowers
description: Bootstrap. Which rule applies to the work in front of you, and the gates that are never skipped.
loads: every session (via .claude/hooks/session-start.sh)
---

# Start here

Nine rules, adapted from the Superpowers plugin (`docs/setup/3_agent_use_2.pdf`)
to the defects **this** repository has actually shipped. Each one names the
incident that bought it, because a rule without a scar gets argued away.

**The rules are not advice. They are entry conditions.** A feature that skips
one is not "done faster", it is untested, unverified, or unreviewed.

## Dispatch

| If the work is… | Load |
|---|---|
| a vague ask, no agreed shape yet | `01-brainstorming` |
| an agreed shape, no task list yet | `02-writing-plans` |
| about to touch files | `03-using-git-worktrees` |
| new behaviour or a bug fix | `04-test-driven-development` |
| something is broken and the cause is unclear | `05-systematic-debugging` |
| code written, not yet reviewed | `06-requesting-code-review` |
| about to say "done" / "working" / "fixed" | `07-verification-before-completion` |
| green and reviewed | `08-finishing-a-development-branch` |

Domain rules are separate and still binding: `ARCHITECTURE.md`,
`backend/CLAUDE.md` §2, and `.claude/skills/architecture-review`. This file
governs *how* you work; those govern *what is allowed to exist*.

## The four gates — never skipped, never "just this once"

1. **Design before code.** No implementation until the user approves a shape.
   (`01`)
2. **A failing test before a fix.** The test must fail for the stated reason
   against the unfixed code, and you must have *seen* it fail. (`04`)
3. **Evidence before "done".** A claim of success names the command and quotes
   its output. "Should work", "looks right", and a green suite that never
   exercised the path are not evidence. (`07`)
4. **Review before merge.** Against the plan, not against vibes. (`06`)

## The two failure modes this repo keeps hitting

**Asserting instead of checking.** `repopulate_cvs.py` was described three
different ways in one session — "unfiltered cross-tenant DELETE", then "inert
dead code", then finally the truth — because `git ls-files` showed nothing and
nobody ran `ls`. The directory was gitignored and held 46 real CVs.
→ Before describing what code does, read it and run it. `05`.

**A check that cannot fail.** `GET /register → 200` was reported as
"registration is open" four times. GlitchTip is an SPA; every unknown path
returns 200 with the shell. The check could not distinguish open from closed.
→ Before trusting a check, make it fail on purpose. `07`.

## Scope

"ANY feature" means any change to `backend/app/`, `frontend/src/`,
`backend/migrations/`, CI, or deploy configuration. A typo fix in a comment is
not a feature. If you are unsure, it is a feature.
