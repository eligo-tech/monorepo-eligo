# `.agents/` — how this repo expects an agent to work

Nine rules, adapted from the Superpowers plugin
(`docs/setup/3_agent_use_2.pdf`, "Nine Skills in Superpowers") to the defects
this repository has actually shipped.

| # | Rule | Responsibility |
|---|---|---|
| 00 | `using-superpowers` | Dispatch table and the four gates. Loaded every session. |
| 01 | `brainstorming` | Turns a request into an approved design |
| 02 | `writing-plans` | Decomposes the design into verifiable tasks |
| 03 | `using-git-worktrees` | Isolated workspace, never `main` |
| 04 | `test-driven-development` | Red, green, refactor — and watch it fail |
| 05 | `systematic-debugging` | Root cause before fix |
| 06 | `requesting-code-review` | Review against the plan |
| 07 | `verification-before-completion` | Evidence before "done" |
| 08 | `finishing-a-development-branch` | Merge, PR, cleanup |

## Why these load, instead of merely existing

The source deck's own warning:

> Installing skills makes them available — availability alone does not
> guarantee the agent check them.

So availability is not the mechanism here. Three things carry it:

1. **A `SessionStart` hook** (`.claude/hooks/session-start.sh`, wired in
   `.claude/settings.json`) injects `00-using-superpowers.md` into context at
   startup, and again after `/clear` and after compaction — the points where
   an agent would otherwise forget.
2. **`CLAUDE.md`** points here, so the rules survive with hooks disabled or in
   a tool that does not run them.
3. **Rules 01–08 are loaded on demand** from 00's dispatch table, keeping
   per-session context small.

## Relationship to the other rule sets

- `.agents/` — *how* to work. Process, gates, evidence standards.
- `ARCHITECTURE.md` + `backend/CLAUDE.md` §2 — *what is allowed to exist*.
  Binding, and unchanged by this directory.
- `.claude/skills/` — invocable procedures (`architecture-review`,
  `add-hub-source`, `add-domain`). Rule 06 invokes them by name.

## Editing

One topic per file, under 200 lines, concrete rules only. Every rule carries
the incident that motivated it — a rule without a scar gets argued away. If an
incident stops being true, delete the rule rather than letting it rot.
