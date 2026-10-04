"""The nine process steps, in the order `docs/process_design` sets out.

One process instance = one candidate on one job, and the steps are a checklist
ticked in order. The order matters and is not the one the cockpit mock used:
the process doc says **Termin vor Vorbereitung** — you agree the appointment,
then you prepare the candidate for it. The mock had preparation first, which
would have a recruiter preparing someone for a meeting that does not exist.

Two feedback steps carry both parties. After the presentation only the CLIENT
has an opinion (the candidate has not met them yet); after the interview both
do, and the sheet's green/red cell is the client's verdict.
"""

from __future__ import annotations

from typing import Literal

#: Outcome of a step: the tracker's uncoloured / green / red cell.
Outcome = Literal["open", "pass", "out"]
OUTCOMES: frozenset[str] = frozenset({"open", "pass", "out"})


class Step:
    """A canonical step: its key, German label, and whether it carries a date."""

    __slots__ = ("key", "label", "kind")

    def __init__(self, key: str, label: str, kind: str) -> None:
        #: "appointment" (has a scheduled date/time), "feedback" (pass/out),
        #: or "milestone" (done or not).
        self.key, self.label, self.kind = key, label, kind

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"Step({self.key})"


PROCESS_STEPS: tuple[Step, ...] = (
    Step("vorgestellt", "Vorgestellt", "milestone"),
    Step("feedback-1", "Feedback Kunde", "feedback"),
    Step("interview", "Interviewtermin", "appointment"),
    Step("vorbereitung", "Interview-Vorb.", "milestone"),
    Step("feedback-2", "Feedback", "feedback"),
    Step("finaltermin", "Finaltermin", "appointment"),
    Step("final-vorb", "Final-Vorb.", "milestone"),
    Step("offer", "Offer & Zusage", "milestone"),
    Step("vertrag", "Vertrag", "milestone"),
)

PROCESS_STEP_KEYS: tuple[str, ...] = tuple(s.key for s in PROCESS_STEPS)
STEP_BY_KEY: dict[str, Step] = {s.key: s for s in PROCESS_STEPS}
#: Positions leave gaps so an extra round ("interviewtermin_3") sorts directly
#: after the round it follows without renumbering the canonical nine.
POSITION: dict[str, int] = {s.key: i * 10 for i, s in enumerate(PROCESS_STEPS)}

#: Extra interview rounds: the tracker's third appointment column ("IvT" — the
#: recruiter's shorthand for Interviewtermin). Stored as its own step so a
#: third round is visible rather than squeezed into a note.
EXTRA_ROUND_PREFIX = "interviewtermin_"

#: A step this process added for itself — "Probearbeitstag", "Assessment
#: Center", "Kennenlernen Team". The nine are what every placement shares;
#: the tenth is what this one needs, and a product that cannot hold it sends
#: the recruiter back to the spreadsheet for exactly one row.
CUSTOM_PREFIX = "custom_"


def custom_key(label: str, taken: set[str]) -> str:
    """A stable, readable key for a custom step: "custom_probearbeitstag".

    Collisions get a counter rather than a random suffix, so the key stays
    legible in the database and in a receipt.
    """
    slug = "".join(
        c if c.isalnum() else "-" for c in label.strip().lower()
    ).strip("-")
    slug = "-".join(part for part in slug.split("-") if part)[:28] or "schritt"
    key = f"{CUSTOM_PREFIX}{slug}"
    if key not in taken:
        return key
    for n in range(2, 100):
        candidate = f"{key}-{n}"
        if candidate not in taken:
            return candidate
    raise ValueError("too many steps with that name")


def is_custom(step_key: str) -> bool:
    return step_key.startswith(CUSTOM_PREFIX)


def label_for(step_key: str, stored: str | None = None) -> str:
    """The canonical label, or the one a custom step brought with it."""
    step = STEP_BY_KEY.get(step_key)
    if step is not None:
        return step.label
    if step_key.startswith(EXTRA_ROUND_PREFIX):
        return f"Interviewtermin {step_key.removeprefix(EXTRA_ROUND_PREFIX)}"
    if stored:
        return stored
    return step_key


def kind_for(step_key: str) -> str:
    step = STEP_BY_KEY.get(step_key)
    if step is not None:
        return step.kind
    if step_key.startswith(EXTRA_ROUND_PREFIX):
        return "appointment"
    # A custom step takes a date like any other: "Probearbeitstag am 14.10."
    # is the whole point of adding one.
    return "appointment" if is_custom(step_key) else "milestone"


def position_for(step_key: str) -> int:
    """Sort position, including for extra rounds.

    An extra round sits between the finaltermin and its preparation, which is
    where a repeat interview actually happens.
    """
    if step_key in POSITION:
        return POSITION[step_key]
    if step_key.startswith(EXTRA_ROUND_PREFIX):
        nth = step_key.removeprefix(EXTRA_ROUND_PREFIX)
        return POSITION["finaltermin"] + (int(nth) if nth.isdigit() else 1)
    return len(PROCESS_STEPS) * 10


def is_known(step_key: str) -> bool:
    return (
        step_key in STEP_BY_KEY
        or step_key.startswith(EXTRA_ROUND_PREFIX)
        or is_custom(step_key)
    )
