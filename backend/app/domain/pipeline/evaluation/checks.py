"""Deterministic checks on a model's Kandidatenauswertung (ELI-42).

The model proposes; these decide what of it may be offered to the recruiter
for acceptance. Pure functions over the answer and the material the prompt
was built from — never over a second model's opinion.

What is checked, and what happens on failure:

* **Score** — "Gesamtbewertung: X / 10" must be there and within 0–10.
  Otherwise the score is left empty and flagged; 10 is not what was said.
* **Section C is for the client** — a health term or a salary figure in it
  means the text is WITHHELD (not stored on accept) and flagged. A prompt
  instruction is a request; this is the guarantee.
* **Technologies (D) are grounded** — each must appear as a word in the
  CANDIDATE's material (documents, profile, notes; not the Suchprofil, which
  would ground anything the job asks for). Ungrounded ones are dropped from
  what accepting stores, and named.
* **Technisches Know-how (B)** — a must-have skill claimed there without
  "nicht angegeben"/"nicht erfragt" must also be grounded, else flagged.
* **Hard criteria** — decided by code (`matching.apply_hard_filters`). A
  failed one is repeated as a flag: the model's score cannot outvote it.

Flags travel with the proposal and are shown next to it. Nothing here
writes anything.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.domain.pipeline.auswertung import parse_auswertung
from app.domain.pipeline.bewertung import EvaluationMaterial

#: Health and other Art. 9 categories that must never reach a client text.
#: Narrow on purpose where a word is also an ordinary CV word: "Operations",
#: "Klinikum" (an employer), "Psychologie" (a degree) are not health data.
_HEALTH = re.compile(
    r"\b(krank\w*|erkrank\w*|gesundheitlich\w*|gesundheitsbedingt\w*|"
    r"burn-?out|therapie|therapeutisch\w*|reha|rehabilitation|diagnose|"
    r"diagnostiziert|psychisch\w*|depress\w*|schwanger\w*|behinderung\w*|"
    r"schwerbehindert\w*|operiert|kur)\b",
    re.IGNORECASE,
)
#: Money talk: a figure with a currency, a k-suffix, or the words for pay.
_SALARY = re.compile(
    r"(\d[\d.,\s]*\s?(?:€|eur\b|euro\b|k\b|t€|tsd))|"
    r"\b(gehalt\w*|vergütung\w*|jahresgehalt\w*|einkommen\w*|brutto\w*|"
    r"salär\w*|gehaltsvorstellung\w*)\b",
    re.IGNORECASE,
)
_NOT_GIVEN = re.compile(r"nicht\s+(angegeben|erfragt|belegt|genannt)", re.IGNORECASE)
_KNOW_HOW = re.compile(r"^Technisches Know-how:\s*(.+)$", re.MULTILINE)


def mentions(term: str, text: str) -> bool:
    """`term` appears in `text` as a word of its own — "Java" is not read out
    of "JavaScript", nor "C" out of every sentence. Same rule as the
    document reader's skill grounding."""
    tokens = unicodedata.normalize("NFKC", term).split()
    if not tokens:
        return False
    body = r"\s+".join(re.escape(t) for t in tokens)
    pattern = r"(?<![\w#+])" + body + r"(?![\w#+])"
    return re.search(pattern, unicodedata.normalize("NFKC", text), re.IGNORECASE) is not None


def candidate_text(m: EvaluationMaterial) -> str:
    """Everything the record says about the PERSON — the grounding corpus."""
    parts = [m.candidate_name]
    parts += [value for _, value in m.profile]
    parts += [n.text for n in m.candidate_notes + m.feedback]
    parts += [d.text for d in m.documents if d.text]
    return "\n".join(parts)


@dataclass
class Checked:
    """The answer after the checks: what accepting would store, and why not more."""

    #: AssessmentWrite-shaped: fit_score, verdict, strengths, risks,
    #: client_summary, technologies, basis, assessed_at.
    assessment: dict[str, Any]
    flags: list[str] = field(default_factory=list)
    #: Technologies the candidate's material does not name.
    ungrounded: list[str] = field(default_factory=list)
    client_text_withheld: bool = False


def check(answer: str, m: EvaluationMaterial) -> Checked:
    parsed = parse_auswertung(answer)
    assessment = dict(parsed["assessment"])
    flags: list[str] = []

    score = assessment.get("fit_score")
    if score is None or not 0 <= score <= 10:
        assessment["fit_score"] = None
        flags.append("Gesamtbewertung fehlt oder liegt nicht zwischen 0 und 10.")

    if not assessment.get("verdict"):
        flags.append("Kein Kurzfazit erkannt — Antwort weicht vom Schema ab.")

    withheld = False
    client = assessment.get("client_summary") or ""
    reasons = []
    if _HEALTH.search(client):
        reasons.append("Gesundheitsangaben")
    if _SALARY.search(client):
        reasons.append("Gehaltsangaben")
    if reasons:
        withheld = True
        assessment["client_summary"] = None
        flags.append(
            "Kundentext (C) zurückgehalten: enthält " + " und ".join(reasons)
            + " — wird beim Übernehmen nicht gespeichert."
        )

    source = candidate_text(m)
    grounded: list[str] = []
    ungrounded: list[str] = []
    for tech in assessment.get("technologies") or []:
        (grounded if mentions(tech, source) else ungrounded).append(tech)
    assessment["technologies"] = grounded
    if ungrounded:
        flags.append(
            "Nicht im Material des Kandidaten belegt (Technologien, nicht übernommen): "
            + ", ".join(ungrounded)
        )

    know_how = _KNOW_HOW.search(answer.replace("**", ""))
    if know_how:
        claimed = [
            skill
            for skill in m.must_have
            for segment in re.split(r"[;,\n]", know_how.group(1))
            if mentions(skill, segment) and not _NOT_GIVEN.search(segment)
        ]
        unbelegt = sorted({s for s in claimed if not mentions(s, source)})
        if unbelegt:
            flags.append(
                "Technisches Know-how nennt Muss-Kriterien ohne Beleg im Material: "
                + ", ".join(unbelegt)
            )

    for failure in m.hard_failures:
        flags.append(f"Harter Filter (per Code entschieden): {failure}")

    return Checked(
        assessment=assessment,
        flags=flags,
        ungrounded=ungrounded,
        client_text_withheld=withheld,
    )
