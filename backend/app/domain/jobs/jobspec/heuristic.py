"""The parser that needs no model, no key and no network.

It is the floor, not a compromise. `get_job_spec_extractor` falls back to it
whenever the LLM is unavailable, CI runs on it, and it handles the three
fields a German advert states in a machine-readable way often enough to be
worth reading deterministically: the headline, the band and the place.

What it deliberately does NOT do is guess **Muss-Kriterien**. Those feed
`apply_hard_filters`, which excludes people. A regex that decides "Python"
is non-negotiable because the word appears in a paragraph would quietly
narrow a search on evidence nobody checked. Skills come from the model, at
low confidence, and a human ticks them.
"""

from __future__ import annotations

import re

from app.domain.jobs.jobspec.base import JobSpec, ProposedField

# "60.000 – 70.000", "60.000 bis 70.000 €", "€60,000-70,000", "60 - 70 T€"
_RANGE = re.compile(
    r"(?<![\d.,])(\d{2,3}(?:[.,]\d{3})?)\s*(?:T€|k€|k)?\s*(?:–|-|—|bis|to)\s*"
    r"(\d{2,3}(?:[.,]\d{3})?)\s*(?:T€|k€|k|€|EUR)",
    re.IGNORECASE,
)
# "ca. 60.000 €", "Gehalt: 65.000 EUR"
_SINGLE = re.compile(
    r"(?:gehalt|vergütung|verguetung|salary)\D{0,20}?(\d{2,3}(?:[.,]\d{3})?)\s*(?:T€|k€|k|€|EUR)",
    re.IGNORECASE,
)
_PLZ_CITY = re.compile(r"\b(\d{5})\s+([A-ZÄÖÜ][\wäöüß.\-]+(?:\s[A-ZÄÖÜ][\wäöüß.\-]+)?)")
# The label, then the rest of the line — `_place_from` decides where the
# place stops. A regex cannot: it has to allow a dot for "St. Ingbert" and
# "Bad Soden a.Ts.", and the moment it does, "Standort: Dillenburg. Wir
# freuen uns" reads as a two-word place called "Dillenburg. Wir".
_IN_CITY = re.compile(
    r"\b(?:Standort|Einsatzort|Arbeitsort|Dienstsitz)\s*:?\s*([^\n]{2,80})"
)
_FORMS = [
    ("Vollzeit", re.compile(r"\bvollzeit\b|\bfull[- ]time\b", re.I)),
    ("Teilzeit", re.compile(r"\bteilzeit\b|\bpart[- ]time\b", re.I)),
]
#: Site chrome a <title> drags along: "Stelle – Firma | Jobportal".
_TITLE_TAIL = re.compile(r"\s*[|–—]\s*[^|–—]{0,40}$")
#: An advert headline nearly always carries one of these.
_HEADLINE = re.compile(
    r"^.{6,120}\((?:m/w/d|w/m/d|m/f/d|m/w/x|all genders)\).{0,40}$", re.I | re.M
)


#: Longest place name we will read off a label. "Frankfurt am Main" is
#: three; past that the line has stopped being an address.
_MAX_PLACE_WORDS = 3


def _place_from(line: str) -> str:
    """Where the place name stops.

    A full stop is ambiguous in German place names — it ends a sentence, and
    it also appears inside "St. Ingbert" and "Bad Soden a.Ts.". The rule that
    tells them apart is length: an abbreviation before the dot is short, a
    word is not. So "Dillenburg." ends the place and "St." does not.
    """
    words: list[str] = []
    for token in line.strip().split():
        if not (token[:1].isupper() or token[:1].isdigit()):
            break  # a lowercase word is prose, not an address
        words.append(token)
        ends_sentence = token.endswith(".") and len(token.rstrip(".")) > 3
        if ends_sentence or len(words) == _MAX_PLACE_WORDS:
            break
    return " ".join(words).strip().rstrip(".,;:·-–— ")


def _amount(raw: str) -> int | None:
    digits = raw.replace(".", "").replace(",", "")
    if not digits.isdigit():
        return None
    value = int(digits)
    # "60 – 70 T€" and "60k": a two-digit band is thousands.
    if value < 1000:
        value *= 1000
    return value if 10_000 <= value <= 500_000 else None


class HeuristicJobSpecExtractor:
    """Regexes over the advert's text. No network, no key, no model."""

    def extract(self, text: str, document_title: str = "") -> JobSpec:
        spec = JobSpec(excerpt=text[:1200])

        # ── title ──────────────────────────────────────────────────────
        # The (m/w/d) line beats the document title: it is the advert's own
        # headline, where <title> is usually the headline plus the site.
        headline = _HEADLINE.search(text)
        if headline:
            spec.title = ProposedField(headline.group(0).strip(), 0.8)
        elif document_title:
            spec.title = ProposedField(_TITLE_TAIL.sub("", document_title).strip(), 0.5)

        # ── band ───────────────────────────────────────────────────────
        found = _RANGE.search(text)
        if found:
            low, high = _amount(found.group(1)), _amount(found.group(2))
            if low and high and low <= high:
                spec.salary_min = ProposedField(str(low), 0.7)
                spec.salary_max = ProposedField(str(high), 0.7)
        else:
            one = _SINGLE.search(text)
            amount = _amount(one.group(1)) if one else None
            if amount:
                # One number is not a band. It is reported as the ceiling,
                # because a recruiter who sees it in the max field will widen
                # it, where one in the min field silently excludes people.
                spec.salary_max = ProposedField(str(amount), 0.45)

        # ── place ──────────────────────────────────────────────────────
        labelled = _IN_CITY.search(text)
        plz = _PLZ_CITY.search(text)
        place = _place_from(labelled.group(1)) if labelled else ""
        if place:
            spec.location = ProposedField(place, 0.75)
        elif plz:
            spec.location = ProposedField(_place_from(f"{plz.group(1)} {plz.group(2)}"), 0.6)

        # ── form ───────────────────────────────────────────────────────
        for label, pattern in _FORMS:
            if pattern.search(text):
                spec.employment_form = ProposedField(label, 0.7)
                break

        return spec
