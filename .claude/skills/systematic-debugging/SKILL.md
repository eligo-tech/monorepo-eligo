---
name: systematic-debugging
description: Reproduce and explain before fixing. Use whenever something is broken, a test fails unexpectedly, CI goes red, or a result is surprising — including when the measurement itself may be the thing that is wrong.
tools: Read, Glob, Grep, Bash, Edit
---

# Systematic debugging — reproduce, then explain, then fix

## Procedure
1. **Reproduce it.** A bug you cannot reproduce is a bug you cannot prove you
   fixed. Write the reproduction down as a command.
2. **Read the actual code**, not what you remember it doing. Open the file.
3. **Form one hypothesis** that explains *all* of the symptoms. A hypothesis
   explaining some of them is the wrong one.
4. **Test the hypothesis cheaply** before building on it.
5. Only then fix — via `test-driven-development`.
6. Ask what **class** of bug this is, and whether siblings exist.

## Prohibited
- Proposing a fix before step 1.
- Describing what code does from its name, its docstring, or memory.
- Treating absence of evidence as evidence. `git ls-files` returning nothing
  means the path is untracked **or gitignored**.
- Trusting a tool's documentation over its behaviour. This codebase has been
  wrong twice that way — prefer a number you produced.

## Verify your tools before your theory
Three wrong conclusions in one session came from broken instruments, not
broken code:
- `grep -v "^20"` silently ate every row of a tenants query, because the dates
  started with "20".
- An unquoted `--include=*.ts` was glob-expanded by zsh, aborting every loop
  iteration and zeroing all hit counts — producing **30 false positives** in a
  dead-code scan.
- `Row.t` returned the whole tuple, turning a count query into
  `SELECT count(*) FROM ('alembic_version', False)`.

When a result is surprising, suspect the measurement first.

## The incident
`repopulate_cvs.py` was called an "unfiltered cross-tenant DELETE / loaded
gun", then "inert dead code", then finally described correctly: `CV_DIR`
resolves to the repo root, the directory holds 46 real CV PDFs, and the wipe
*is* tenant-scoped. Each wrong claim was confident and each was built on the
previous one instead of on the file. A PR was opened and closed on the strength
of a falsehood.
