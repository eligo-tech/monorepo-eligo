"""The pre-screen script and the deterministic reading of its answers.

The questions are the Qualifikationsgespräch topics a recruiter already asks
(`candidates` model: the Gesprächszusammenfassung set). Each question maps to
exactly ONE candidate field, so an answer can only ever propose a value for
the field it was asked about.

Deliberately NOT asked: work permit, date of birth, sex, nationality, health.
Work permit is a legally hard matching criterion and must be established by a
person against a document (ARCHITECTURE.md RULE 5); the others are protected
attributes an interview must not collect (AGG §1).

`read_answer` is the extraction seam. Today it is plain parsing — no model —
so every proposed value can be re-derived from its quote by the same code,
which is what the agent's postconditions do. An LLM reader can replace it
later; the postconditions stay, and a model's value that cannot be re-derived
from the candidate's own words goes to review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Literal

SCRIPT_VERSION = "2026-10-17"

#: Shown to the candidate BEFORE the first question; the interview cannot
#: start until consent to exactly this version is recorded.
CANDIDATE_NOTICE_VERSION = "2026-10-17"
CANDIDATE_NOTICE = """\
Sie sprechen mit einem KI-gestützten Interview-Assistenten.

• Ihre Antworten werden gespeichert und helfen Ihrem Recruiter, Ihr Profil
  vorzubereiten. Jede übernommene Angabe ist mit Ihrer Antwort belegt.
• Es gibt keine automatische Entscheidung über Ihre Bewerbung — ein Mensch
  prüft alle Ergebnisse.
• Sie können Fragen mit „keine Angabe" beantworten, das Interview jederzeit
  abbrechen und Ihre Zustimmung widerrufen. Das Transkript wird dann gelöscht.
"""

Kind = Literal["text", "money", "choice"]


@dataclass(frozen=True)
class Question:
    key: str
    field: str
    kind: Kind
    prompt: str
    #: For `choice`: candidate keyword (lower-case) → stored value.
    choices: dict[str, str] = dc_field(default_factory=dict)


QUESTIONS: tuple[Question, ...] = (
    Question(
        "motivation", "motivation", "text",
        "Was motiviert Sie, sich beruflich zu verändern?",
    ),
    Question(
        "technical_profile", "technical_profile", "text",
        "Beschreiben Sie bitte Ihre fachlichen Schwerpunkte und Technologien — "
        "gern mit Einschätzung, wie tief Sie sich jeweils auskennen.",
    ),
    Question(
        "salary_minimum", "salary_minimum", "money",
        "Was ist Ihr Mindestgehalt (brutto pro Jahr), unter dem ein Wechsel "
        "für Sie nicht in Frage kommt?",
    ),
    Question(
        "salary_expectation", "salary_expectation", "money",
        "Und was ist Ihr Wunschgehalt (brutto pro Jahr)?",
    ),
    Question(
        "notice_period", "notice_period", "text",
        "Wie lang ist Ihre aktuelle Kündigungsfrist?",
    ),
    Question(
        "employment_form", "employment_form", "choice",
        "Suchen Sie eine Festanstellung, Freelance-Projekte oder beides?",
        choices={
            "beides": "beides",
            "both": "beides",
            "festanstellung": "festanstellung",
            "festangestellt": "festanstellung",
            "fest": "festanstellung",
            "permanent": "festanstellung",
            "freelance": "freelance",
            "freiberuflich": "freelance",
            "projekte": "freelance",
        },
    ),
    Question(
        "willing_to_relocate", "willing_to_relocate", "choice",
        "Wären Sie für die richtige Stelle bereit umzuziehen?",
        choices={"ja": "ja", "yes": "ja", "nein": "nein", "no": "nein"},
    ),
    Question(
        "interview_availability", "interview_availability", "text",
        "Wann sind Sie für Interviews in der Regel erreichbar?",
    ),
    Question(
        "other_processes", "other_processes", "text",
        "Laufen bei Ihnen aktuell andere Bewerbungsprozesse? Wenn ja, wie weit "
        "sind diese?",
    ),
)

QUESTIONS_BY_KEY = {q.key: q for q in QUESTIONS}
INTERVIEW_FIELDS = frozenset(q.field for q in QUESTIONS)

_NO_ANSWER = {
    "", "-", "k.a.", "k. a.", "keine angabe", "weiß nicht", "weiss nicht",
    "keine ahnung", "n/a", "pass", "möchte ich nicht sagen",
}
_TEXT_LIMIT = 2000

# 92.000 · 92 000 · 92000 · 92k · 92 k€ · 92 Tsd. · 92 Tausend · 92,5k
_MONEY = re.compile(
    r"(?P<num>\d{1,3}(?:[.\s]\d{3})+|\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>k€|k|tsd\.?|tausend|t€)?",
    re.IGNORECASE,
)
_MONEY_MIN, _MONEY_MAX = 10_000, 1_000_000


@dataclass(frozen=True)
class Reading:
    """What an answer says for its one field, and the words that say it."""

    value: str
    #: Verbatim substring of the candidate's answer that carries the value.
    quote: str
    confidence: float
    note: str = ""


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def parse_money(fragment: str) -> int | None:
    """One amount from one matched fragment, or None if implausible."""
    m = _MONEY.fullmatch(fragment.strip())
    if m is None:
        return None
    raw, unit = m.group("num"), (m.group("unit") or "").lower()
    if re.fullmatch(r"\d{1,3}(?:[.\s]\d{3})+", raw):
        amount = float(re.sub(r"[.\s]", "", raw))
    else:
        amount = float(raw.replace(",", "."))
    if unit or amount < 1000:
        # "92k", "92 Tausend" — and a bare "92" in a salary answer means 92k.
        amount *= 1000
    value = int(round(amount))
    return value if _MONEY_MIN <= value <= _MONEY_MAX else None


def _read_money(answer: str) -> Reading | None:
    hits = [(m.group(0).strip(), parse_money(m.group(0))) for m in _MONEY.finditer(answer)]
    hits = [(quote, value) for quote, value in hits if value is not None]
    if not hits:
        return None
    quote, value = hits[0]
    whole = _MONEY.fullmatch(quote)
    bare = whole is not None and not whole.group("unit")
    if len(hits) > 1:
        # "92–95k": a range is a fact about the candidate, not one number —
        # the lower bound is proposed, a recruiter confirms.
        return Reading(str(value), quote, 0.6, "mehrere Beträge genannt")
    if bare and float(re.sub(r"[.\s]", "", quote).replace(",", ".")) < 1000:
        return Reading(str(value), quote, 0.6, "Betrag ohne Einheit")
    return Reading(str(value), quote, 0.85)


def _read_choice(answer: str, q: Question) -> Reading | None:
    words = re.findall(r"[\wäöüß]+", answer.casefold())
    found = [(w, q.choices[w]) for w in words if w in q.choices]
    values = {v for _, v in found}
    if not found:
        return None
    if len(values) > 1:
        # "fest oder freelance" → beides is what they said, if they said it;
        # otherwise two different answers is a question for a person.
        if "beides" in values:
            word = next(w for w, v in found if v == "beides")
            return Reading("beides", _original(answer, word), 0.8)
        return Reading(found[0][1], _original(answer, found[0][0]), 0.5, "widersprüchlich")
    word, value = found[0]
    return Reading(value, _original(answer, word), 0.8)


def _original(answer: str, word: str) -> str:
    """The word as the candidate typed it (case preserved)."""
    m = re.search(re.escape(word), answer, re.IGNORECASE)
    return m.group(0) if m else word


def read_answer(q: Question, answer: str) -> Reading | None:
    """The value an answer gives for its question's field, or None."""
    text = answer.strip()
    if normalize(text) in _NO_ANSWER:
        return None
    if q.kind == "money":
        return _read_money(text)
    if q.kind == "choice":
        return _read_choice(text, q)
    clipped = text[:_TEXT_LIMIT]
    return Reading(clipped, clipped, 0.9)


def rederive(q: Question, quote: str) -> str | None:
    """Re-read a value from its quote alone — the postcondition's check."""
    if q.kind == "money":
        value = parse_money(quote)
        return None if value is None else str(value)
    if q.kind == "choice":
        return q.choices.get(quote.casefold())
    return quote
