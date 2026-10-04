"""The Kandidatenauswertung as a parser: the recruiter's document → fields.

The document (`data/examples/KandidatenInfo.txt`) is the recruiter's own
template, written after the Qualifikationsgespräch, four sections deep:

    A. Passungsbewertung zur Position           → the assessment (per mandate)
    B. Gesprächszusammenfassung für die Datenbank → the CANDIDATE's columns
    C. Kandidatenzusammenfassung für den Kunden → the client-facing text
    D. Relevante Technologien                   → the technology list

A/C/D describe a fit and belong to one application; B describes the person
and holds across every mandate they run on, so it lands on `candidates`.

This is a **pure function over text** and writes nothing. It is used twice:
by `scripts/import_assessment.py`, which loads a file onto a named
application, and by `POST /pipeline/auswertung/parse`, which fills the form
in the cockpit so a recruiter can paste the document they just wrote, read
back what was understood, correct it, and only then save. Nothing is
committed by parsing — the recruiter is the one who commits, which is also
why the salary numbers it lifts are safe to guess at: they land in a form
field in front of the person who said them, not in a hard filter.

Unknown or missing sections come back empty rather than raising. A file that
stops after section A is still worth importing, and a parser that insists on
all four would simply never be used.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

#: "Gesamtbewertung: 8 / 10" — the score, on the document's own scale.
SCORE = re.compile(r"Gesamtbewertung:\s*(\d{1,2})\s*/\s*10")
#: "Grundlage: CV (Kurzversion) + Gesprächstranskript (18.09.2026)"
BASIS = re.compile(r"^Grundlage:\s*(.+)$", re.MULTILINE)
GERMAN_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")

#: Section headings, as the template writes them. Matched at the start of a
#: line so a mention inside a paragraph cannot split the document.
_SECTIONS = (
    ("A", re.compile(r"^A\.\s", re.MULTILINE)),
    ("B", re.compile(r"^B\.\s", re.MULTILINE)),
    ("C", re.compile(r"^C\.\s", re.MULTILINE)),
    ("D", re.compile(r"^D\.\s", re.MULTILINE)),
)

#: Single labelled lines of section B → the candidate column each belongs in.
#: Everything here describes the PERSON, not their fit for one position.
_B_FIELDS: dict[str, str] = {
    "Zusammenfassung des Profils": "profile_summary",
    "Technisches Know-how": "technical_profile",
    "Kündigungsfrist / Verfügbarkeit": "notice_period",
    "Wechselmotivation": "motivation",
    "Verfügbarkeit für Interviews": "interview_availability",
}

#: Every label section B may use, so a value is never swallowed by the one
#: above it. Used as the terminator when reading a multi-line block.
_B_LABELS = (
    "Zusammenfassung des Profils",
    "Schwerpunkte",
    "Technisches Know-how",
    "Kündigungsfrist / Verfügbarkeit",
    "Gehaltsvorstellung",
    "Wechselmotivation",
    "Höchster Abschluss",
    "Verfügbarkeit für Interviews",
    "Weitere relevante Punkte",
)

#: "92.000–95.000 €", "~100.000", ">105k". German thousands separators and
#: the k-suffix both appear in the same document.
_AMOUNT = re.compile(r"(\d{2,3})(?:[.\s](\d{3})|k\b)", re.IGNORECASE)


def _split_sections(text: str) -> dict[str, str]:
    """The document as {"A": …, "B": …, "C": …, "D": …}, text before A dropped."""
    marks: list[tuple[str, int]] = []
    for name, pattern in _SECTIONS:
        match = pattern.search(text)
        if match:
            marks.append((name, match.start()))
    marks.sort(key=lambda m: m[1])
    out: dict[str, str] = {}
    for index, (name, start) in enumerate(marks):
        end = marks[index + 1][1] if index + 1 < len(marks) else len(text)
        out[name] = text[start:end].strip()
    return out


def _lines_between(block: str, start_label: str, stop_labels: tuple[str, ...]) -> list[str]:
    """The bullet lines under `start_label:` up to the next labelled line.

    The template writes its lists as one item per line with no bullet
    character, so the terminator is the next label rather than a marker.
    """
    out: list[str] = []
    collecting = False
    for raw in block.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.rstrip(":") == start_label:
            collecting = True
            continue
        if collecting:
            if any(line.startswith(stop) for stop in stop_labels):
                break
            out.append(line.lstrip("-•* ").strip())
    return out


def _labelled(block: str, label: str) -> str | None:
    """The text after `Label:` — the paragraph it introduces, one line."""
    for raw in block.splitlines():
        line = raw.strip()
        if line.startswith(f"{label}:"):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def _split_items(value: str) -> list[str]:
    """"A, B (x → y), C" → three items. Commas inside brackets do not split.

    The Schwerpunkte line is read as items, not as a sentence, and the
    qualifier in brackets belongs to the item it follows.
    """
    out: list[str] = []
    depth = 0
    current: list[str] = []
    for char in value:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            out.append("".join(current))
            current = []
            continue
        current.append(char)
    out.append("".join(current))
    return [item.strip().rstrip(".").strip() for item in out if item.strip(" .")]


def _amount(text: str) -> int | None:
    """The first euro figure in a phrase, as a number. None if there is none."""
    match = _AMOUNT.search(text)
    if match is None:
        return None
    head, thousands = match.group(1), match.group(2)
    return int(head) * 1000 if thousands is None else int(head + thousands)


def _salary(line: str | None) -> dict[str, int]:
    """"Aktuell >105.000 €; Minimum 92.000–95.000 €, Wunsch ~100.000 €" → ints.

    Each number is taken from the clause that names it, never from position:
    a document that gives only a Wunsch must not have it read as a minimum.
    The result is shown in a form field before anything is stored.
    """
    if not line:
        return {}
    out: dict[str, int] = {}
    for clause in re.split(r"[;,.]\s+|\s+(?=Minimum|Wunsch|Aktuell)", line):
        lowered = clause.lower()
        value = _amount(clause)
        if value is None:
            continue
        if "minimum" in lowered and "salary_minimum" not in out:
            out["salary_minimum"] = value
        elif "wunsch" in lowered and "salary_expectation" not in out:
            out["salary_expectation"] = value
        elif "aktuell" in lowered and "current_salary" not in out:
            out["current_salary"] = value
    return out


def _body(block: str) -> str:
    """A section without its heading line."""
    lines = block.splitlines()
    return "\n".join(line.strip() for line in lines[1:] if line.strip())


def parse_auswertung(text: str) -> dict[str, Any]:
    """The document as data. Pure: takes the text, returns what to store."""
    sections = _split_sections(text)
    a, b = sections.get("A", ""), sections.get("B", "")

    score = SCORE.search(a)
    basis_match = BASIS.search(text)
    basis = basis_match.group(1).strip() if basis_match else None
    assessed_at = None
    if basis:
        date = GERMAN_DATE.search(basis)
        if date:
            day, month, year = (int(g) for g in date.groups())
            assessed_at = dt.datetime(year, month, day, tzinfo=dt.UTC)

    # The Kurzfazit is the headline; the "Fachliche & professionelle Passung"
    # paragraph is the same verdict argued out. Both are section A's prose and
    # are kept together — splitting them across fields would leave the cockpit
    # showing a conclusion with its reasoning elsewhere. The cockpit renders
    # the first paragraph large and the rest behind "Begründung".
    verdict_parts = [
        part
        for part in (
            _labelled(a, "Kurzfazit"),
            _labelled(a, "Fachliche & professionelle Passung"),
        )
        if part
    ]

    technologies = _split_items(
        _body(sections.get("D", "")).replace(";", ",")
    )

    candidate: dict[str, Any] = {
        field: value
        for label, field in _B_FIELDS.items()
        if (value := _labelled(b, label))
    }
    if focus := _labelled(b, "Schwerpunkte"):
        candidate["focus_areas"] = _split_items(focus)
    if degree := _labelled(b, "Höchster Abschluss"):
        # `education` is a list; the document gives one line naming the degree
        # and the certifications around it. One entry, kept as written.
        candidate["education"] = [degree]
    if notes := _lines_between(b, "Weitere relevante Punkte", ("C.",)):
        candidate["other_notes"] = "\n".join(notes)
    candidate.update(_salary(_labelled(b, "Gehaltsvorstellung")))

    return {
        "assessment": {
            "fit_score": int(score.group(1)) if score else None,
            "verdict": "\n\n".join(verdict_parts) or None,
            "strengths": _lines_between(a, "Stärken", ("Lücken/Risiken",)),
            "risks": _lines_between(
                a, "Lücken/Risiken", ("Fachliche & professionelle Passung",)
            ),
            "client_summary": _body(sections.get("C", "")) or None,
            "technologies": technologies,
            "basis": basis,
            "assessed_at": assessed_at,
        },
        "candidate": candidate,
    }
