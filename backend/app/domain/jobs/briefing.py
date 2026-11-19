"""Briefing-Bewertung (ELI-47): how much of the briefing is geklärt.

Ten points a recruiter needs from the client before a search is worth
running. The check is plain code over the mandate's own fields — no model:
a point is geklärt when its field holds a real value, and "fehlt" means
nothing is stored, never that the client has no answer.

This is the ONE definition of the ten points. The frontend gets the result
with every job payload (`JobRead.briefing`) and only maps the keys to labels,
so the list cannot drift between the score and the screen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

#: Placeholders that read as "nothing written down". An import or a hand
#: edit that stores a dash has not clarified anything.
_EMPTY = frozenset({"", "-", "—", "–", "n/a", "k. a.", "k.a."})


def _text(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() not in _EMPTY


def _items(value: object) -> bool:
    return isinstance(value, list) and any(_text(v) for v in value)


@dataclass(frozen=True)
class Point:
    key: str
    check: Callable[[object], bool]


def _field(name: str, test: Callable[[object], bool]) -> Callable[[object], bool]:
    return lambda job: test(getattr(job, name, None))


POINTS: tuple[Point, ...] = (
    Point("tasks", _field("tasks", _text)),
    Point("must_have", _field("must_have_skills", _items)),
    Point("nice_to_have", _field("nice_to_have_skills", _items)),
    # One side of the band is already a frame: "bis 95k" is an answer.
    Point(
        "salary",
        lambda job: getattr(job, "salary_min", None) is not None
        or getattr(job, "salary_max", None) is not None,
    ),
    # Standort/Remote is one field: "München · 2 Tage remote" or "Remote".
    Point("location", _field("location", _text)),
    Point("start", _field("start_date", _text)),
    Point("team_size", _field("team_size", _text)),
    Point("contact", lambda job: getattr(job, "manager_id", None) is not None),
    Point("interview_process", _field("interview_process", _text)),
    Point("vacancy_reason", _field("vacancy_reason", _text)),
)


class BriefingScore(BaseModel):
    """`done` of `total` points geklärt; `missing` in the briefing's order."""

    done: int
    total: int
    missing: list[str]


def assess(job: object) -> BriefingScore:
    missing = [p.key for p in POINTS if not p.check(job)]
    return BriefingScore(done=len(POINTS) - len(missing), total=len(POINTS), missing=missing)
