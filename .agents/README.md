# Agent rules — index

Nine process skills, adapted from the Superpowers plugin
(`docs/setup/3_agent_use_2.pdf`, "Nine Skills in Superpowers") to the defects
this repository has actually shipped.

They live in **`.claude/skills/`**, because that is the directory an agent
discovers and can invoke by name. This file is the human-readable index.

| Skill | Responsibility | How it is reached |
|---|---|---|
| [`using-superpowers`](../.claude/skills/using-superpowers/SKILL.md) | Dispatch table and the four gates | injected every session by the hook |
| [`brainstorming`](../.claude/skills/brainstorming/SKILL.md) | Turns a request into an approved design | by name |
| [`writing-plans`](../.claude/skills/writing-plans/SKILL.md) | Decomposes the design into verifiable tasks | by name |
| [`using-git-worktrees`](../.claude/skills/using-git-worktrees/SKILL.md) | Isolated workspace, never `main` | by name |
| [`test-driven-development`](../.claude/skills/test-driven-development/SKILL.md) | Red, green, refactor — and watch it fail | by name |
| [`systematic-debugging`](../.claude/skills/systematic-debugging/SKILL.md) | Root cause before fix | by name |
| [`requesting-code-review`](../.claude/skills/requesting-code-review/SKILL.md) | Review against the plan | by name |
| [`verification-before-completion`](../.claude/skills/verification-before-completion/SKILL.md) | Evidence before "done" | by name |
| [`finishing-a-development-branch`](../.claude/skills/finishing-a-development-branch/SKILL.md) | Merge, PR, cleanup | by name |

## Why they load, instead of merely existing

The source deck's own warning:

> Installing skills makes them available — availability alone does not
> guarantee the agent check them.

So availability is not the mechanism. Three things carry it:

1. **A `SessionStart` hook** (`.claude/hooks/session-start.sh`, wired in
   `.claude/settings.json`) injects `using-superpowers` at startup, and again
   after `/clear` and after compaction — the points where an agent would
   otherwise forget.
2. **`CLAUDE.md`** names all nine, so they survive with hooks disabled.
3. **Each skill's `description` says *when* it applies**, which is what makes
   it discoverable rather than merely present — and any of them can be
   invoked explicitly, by the dispatch table or by the user.

## Relationship to the other rule sets

- These nine — *how* to work. Process, gates, evidence standards.
- `ARCHITECTURE.md` + `backend/CLAUDE.md` §2 — *what is allowed to exist*.
  Binding, and unchanged by these.
- `architecture-review`, `add-hub-source`, `add-domain` — domain procedures in
  the same directory. `requesting-code-review` invokes the first by name.

## Editing

One topic per file, under 200 lines, concrete rules only. Every skill carries
the incident that motivated it — a rule without a scar gets argued away. If an
incident stops being true, delete the rule rather than letting it rot.
