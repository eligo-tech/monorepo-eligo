---
name: brainstorming
description: Turns a request into an approved design. Load before any creative or structural work.
---

# Brainstorming — agree the shape before writing code

## Entry conditions
The user described an outcome, not an implementation. Or they described an
implementation and it is not obviously the right one.

## Procedure
1. **Inspect first.** Read the code that already does something adjacent.
   This repo is layered (`ARCHITECTURE.md`); most "new" features are a new
   adapter, not a new layer.
2. **Classify the scope.** Which of the six layers does it touch? If it touches
   the hub, tenancy, RLS, ingestion or personal data, load
   `.claude/skills/architecture-review` *now*, not at review time.
3. **Clarify only what changes the work.** Ask questions whose different
   answers produce different code. Do not ask what you can read.
4. **Compare at least two approaches**, with the trade-off stated in one line
   each. One option is not a choice.
5. **Present the design** — what changes, what does not, what it costs, what it
   risks.
6. **Wait for approval.** ← gate
7. Then `02-writing-plans`.

## Prohibited
- Writing implementation code before step 6.
- Expanding scope beyond the ask because "while I'm here".
- Proposing a shape that routes around a boundary in `ARCHITECTURE.md`.
  Fix the boundary or argue for changing it — never route around it.

## The incident
The aiFind connector hardcoded one customer's Keycloak realm and host. Nobody
designed that; it accreted. Undoing it took a migration (`0043`), a new
`config` column, changes to four call sites, and 15 tests — for something a
five-minute design conversation would have caught, because the question "whose
instance is this?" has exactly one sensible answer and it is not "ours".
