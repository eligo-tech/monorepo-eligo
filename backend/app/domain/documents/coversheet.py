"""Read a partner's filled cover sheet — deterministically (ELI-19).

A profile from a partner recruiter arrives with our own "Kandidatenprofil"
cover sheet already filled in. The template is labelled — "Zusammenfassung:",
"Gehaltsvorstellung:", "Kündigungsfrist:" … — so it is read by its labels, not
by a model: every value is the text between its label and the next one, and
its evidence is that row as written. Grounding is then by construction, and
the service checks it again anyway.

What is NOT read: the "Kontakt:" block (the partner's own recruiter, not the
candidate) and the AGB footer. Both end the segment before them, and nothing
after "Kontakt:" is ever a value.

A sheet with none of the labels yields nothing, and the caller falls back to
the configured model (`extract_reference(text, "coversheet")`).
"""

from __future__ import annotations

import re
import unicodedata

from app.domain.documents.extraction.base import ReferenceField

#: Field → its label. Order does not matter: segments are cut by position.
_LABELS: dict[str, str] = {
    "desired_position": r"Angestrebte\s+Position\s*:",
    "profile_summary": r"Zusammenfassung\s*:",
    "technical_profile": r"Technologie[\s-]*Stack\s*:",
    "expected_salary": r"Gehaltsvorstellung\s*:",
    "notice_period": r"Kündigungsfrist\s*:",
    "qualifications": r"Qualifikationen\s*:",
    "languages": r"Sprachkenntnisse[^:•]{0,40}:",
    "motivation": r"Wechselmotivation\s*:",
}
#: Labels that end the segment before them and are never read themselves.
_STOPS = (
    r"Rahmenbedingungen\s*:",
    r"Kontakt\s*:",
    r"Dieser\s+Lebenslauf\s+wurde",
)
#: Values one field per labelled row — plainly stated, pre-ticked.
_PLAIN = 0.95
#: Prose shredded into the skills inventory, which feeds the hard filters —
#: offered, but a person decides (below the review threshold).
_SHREDDED = 0.5
#: "70.000 – 80.000 €" is not one number; which end is the person's call.
_AMBIGUOUS = 0.4
_LIST_FIELDS = ("qualifications", "languages")
_AMOUNT = re.compile(r"\d{1,3}(?:[.\s']\d{3})+|\d+")
_EDGES = re.compile(r"^[\s•·–-]+|[\s•·–-]+$")


def _clean(text: str) -> str:
    """NFKC (the template's "ﬁ" ligature) and one space between words —
    pypdf hands this template back one word per line."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _strip(segment: str) -> str:
    """Bullets and dashes around a row are layout, not value."""
    return _EDGES.sub("", segment)


def _top_level_items(value: str) -> list[str]:
    """Split on commas outside parentheses: "IT-Infrastruktur (Windows
    Server, Active Directory)" is one item, not three."""
    items, depth, current = [], 0, []
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(ch)
    items.append("".join(current))
    return [i.strip(" .;") for i in items if i.strip(" .;")]


def parse_coversheet(text: str) -> list[ReferenceField]:
    flat = _clean(text)
    marks: list[tuple[int, int, str | None]] = []
    for field, pattern in _LABELS.items():
        m = re.search(pattern, flat, re.IGNORECASE)
        if m:
            marks.append((m.start(), m.end(), field))
    for pattern in _STOPS:
        m = re.search(pattern, flat, re.IGNORECASE)
        if m:
            marks.append((m.start(), m.end(), None))
    marks.sort()

    out: list[ReferenceField] = []
    for i, (start, end, field) in enumerate(marks):
        if field is None:
            continue
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(flat)
        raw = flat[end:stop]
        evidence = _strip(flat[start:stop])
        if field in _LIST_FIELDS:
            items = [_strip(p) for p in raw.split("•")]
            value = "; ".join(p for p in items if p)
        else:
            value = _strip(raw)
        if not value:
            continue
        confidence = _PLAIN
        if field == "expected_salary" and len(_AMOUNT.findall(value)) != 1:
            confidence = _AMBIGUOUS
        out.append(ReferenceField(field, value, evidence, confidence))
        if field == "technical_profile":
            skills = _top_level_items(value)
            if skills:
                out.append(
                    ReferenceField("skills", "; ".join(skills), evidence, _SHREDDED)
                )
    return out
