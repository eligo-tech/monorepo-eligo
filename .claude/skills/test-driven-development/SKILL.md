---
name: test-driven-development
description: Red, green, refactor — write the failing test first and watch it fail for the reason you intend. Use for any new behaviour or bug fix, and whenever a fix must be proven rather than asserted, such as a security fix.
tools: Read, Glob, Grep, Bash, Edit, Write
---

# TDD — the test fails first, and you watch it fail

## The cycle, non-negotiable
1. **Red.** Write the test. Run it. **See it fail, and read the failure
   message.** It must fail for the reason you intend, not because of a typo,
   a missing import, or a fixture that was never wired.
2. **Green.** Write the least code that passes it.
3. **Refactor.** With the test still green.

A test written after the fix proves the fix is *present*. It does not prove the
fix *works*, because it never saw the broken state. For a security fix that
distinction is the whole point.

## This repo's standard of proof
For a bug fix, the test must fail against the **unfixed** code:

```bash
git stash && .venv/bin/pytest tests/test_<x>.py -q   # expect failures
git stash pop && .venv/bin/pytest tests/test_<x>.py -q  # expect pass
```

Quote both outputs in the PR. PR #179 did exactly this: 15 new tests, all 15
failing against `origin/main`, all 15 green after. That is what made the SSRF
fix believable rather than merely plausible.

## Assert on the observable, not the internal
The SSRF tests do not assert "the validator was called". They assert on
**requests that actually left the process**, via a recording transport. An
internal request that is refused *after* being sent is still a breach — only
the outbound record shows that.

Ask: if the implementation were wrong in the way I fear, would this test go
red? If not, the test is decoration.

## Run the suite
```bash
cd backend && ELIGO_DATABASE_URL=sqlite+aiosqlite:///./ci_test.db \
  ELIGO_DB_SSL=false ELIGO_DB_SSL_VERIFY=true ELIGO_LLM_PROVIDER=heuristic \
  .venv/bin/pytest -q
cd frontend && npm run typecheck && npm run build
```

## The incident
An observability test asserted a candidate's salary never reached the wire. It
passed. It was wrong: the value was a **literal in the test helper's body**,
and Sentry ships `pre_context`/`context_line`/`post_context` separately from
locals — so the leak travelled through the *source*, not the variables. The
helper was rewritten to take the values as arguments, and a second test was
added to record that source lines are sent deliberately.
→ A green test is evidence only if you know what would turn it red.
