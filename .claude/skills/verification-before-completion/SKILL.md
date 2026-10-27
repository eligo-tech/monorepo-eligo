---
name: verification-before-completion
description: Require evidence before reporting success. Use before writing done, fixed, working, deployed or verified, and before any claim about production behaviour — a claim names the command it ran and what that command printed.
tools: Read, Glob, Grep, Bash
---

# Verification — a claim names its evidence

## The rule
Before writing "done", "fixed", "working", "deployed" or "verified", state:
**what command you ran, and what it printed.** If you cannot, you have not
verified it — say what you actually know instead.

## Make the check fail on purpose
A check you have never seen fail is not a check. Before trusting one, break the
thing deliberately and confirm it goes red. The CI cross-lock assertion in
`.github/workflows/ci.yml` was mutation-tested this way; the lock staleness
guard was not, and shipped unable to pass.

## Banned forms of "evidence"
| Not evidence | Why |
|---|---|
| "The tests pass" | Which tests? Do they exercise this path? |
| "Should work" | Then it is unverified. Say so. |
| HTTP 200 from an SPA | Every unknown path returns the shell. |
| A green frontend suite proving the English UI | It does not. Check the deployed site. |
| A number read from documentation | This repo has been wrong twice that way. |
| Absence in `git ls-files` | The path may be gitignored. |

## Production claims need production checks
- Backend behaviour → the deploy log or a read-only probe against the real
  database (`python -I`, `AdminSessionLocal`, **SELECT only**).
- Config → read it back from Railway, do not assume the value you set.
- Anything user-visible → open the deployed site.

## Report faithfully
If part of the work is incomplete, blocked, or skipped, say which part and
why — in the same message as the parts that succeeded. Scaling the work down is
the user's decision, not yours. A partial success reported as a success is the
most expensive kind of mistake, because it stops anyone else from looking.

## The incident
`GET /register → 200` was reported as "registration is still open" four
separate times. GlitchTip is a single-page app: `/api/settings`,
`/profile/settings` and every other unknown path also returned 200 with the
same shell. The check was incapable of distinguishing open from closed. The
answer came from `ENABLE_USER_REGISTRATION='False'` in the service config —
one authoritative read, after four confident wrong ones.
