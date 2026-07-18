"""laufwise pre/postcondition gate for CV extraction.

Every check is a pure predicate over *real state* — the extracted result, a
syntactic validation, or a re-queried DB row — never over the model's own text.
That is the laufwise invariant (checks read the system-of-record, not agent
output) and it is what makes the extraction "verified": the LLM proposes fields;
these deterministic checks decide what may be trusted or written.

Flow mirrors laufwise's runbook order:
    precondition (vs the document) -> extract -> postcondition (vs the result)
    -> persist -> postcondition (re-query the DB and prove the row landed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from laufwise.contract.evaluator import BuiltinEvaluator
from laufwise.state.base import StateView

_EVAL = BuiltinEvaluator()
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class PreconditionFailed(Exception):
    """A blocking precondition did not hold — the step must not proceed."""


@dataclass
class GateOutcome:
    expr: str
    ok: bool
    detail: str
    reason: str | None

    def as_note(self) -> str:
        mark = "✓" if self.ok else "✗"
        return f"{mark} {self.expr} — {self.detail}"


def evaluate(checks: list[tuple[str, str | None]], fixture: dict) -> list[GateOutcome]:
    """Evaluate each `(expr, reason)` against a StateView snapshot of `fixture`."""
    state = {key: StateView(value) for key, value in fixture.items()}
    outcomes: list[GateOutcome] = []
    for expr, reason in checks:
        try:
            result = _EVAL.evaluate(expr, state)
            outcomes.append(GateOutcome(expr, result.ok, result.detail, reason))
        except Exception as exc:  # unparseable/unknown binding → treat as failed check
            outcomes.append(GateOutcome(expr, False, f"uncheckable: {exc}", reason))
    return outcomes


def email_is_valid(value: str | None) -> bool:
    """Deterministic postcondition input: syntactic validity (a real check on the
    extracted value, not the model's claim). Deliverability would extend this."""
    return bool(value and _EMAIL_RE.match(value.strip()))


# ── Check definitions (declarative; the domain contract lives here, not in code)

PRECONDITIONS: list[tuple[str, str | None]] = [
    ("document.text_chars > 0",
     "PDF has no extractable text (scanned/image PDF) — OCR required before extraction"),
]

# Postconditions over the extraction result. `email.valid` is a real syntactic
# check; `accepted.count` guards against creating an empty candidate.
POSTCONDITIONS: list[tuple[str, str | None]] = [
    ("email.valid == true", "extracted e-mail failed syntactic validation"),
    ("accepted.count >= 1", "no field cleared the confidence threshold"),
]

# Persist gate: refuse to write a candidate with nothing identifying.
PERSIST_PRECONDITION: list[tuple[str, str | None]] = [
    ("identifiers.count >= 1",
     "no name or e-mail accepted — refusing to create an empty candidate"),
]