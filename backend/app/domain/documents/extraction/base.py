"""The extractor seam: text → structured fields with confidence.

`CV_FIELDS` is the single source of truth for the field set (aiFind parity) and
their product-facing German labels. The OpenAI schema enum, the display labels,
and the display order all derive from it — add a field in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.agents.document_extraction import ExtractedField


@dataclass
class WorkRole:
    """One position on the CV — the unit the dossier timeline renders."""

    title: str = ""
    company: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    highlights: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "highlights": self.highlights,
        }


@dataclass
class EducationEntry:
    degree: str = ""
    institution: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""

    def as_dict(self) -> dict:
        return {
            "degree": self.degree,
            "institution": self.institution,
            "location": self.location,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


@dataclass
class CVSections:
    """Structured, per-entry history — richer than the flat aiFind fields.
    Empty lists mean the extractor could not (or does not) produce them."""

    work_history: list[WorkRole] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Everything one extraction pass yields: the flat aiFind fields (each
    confidence-scored) and the structured per-entry history. Produced in a
    single LLM call by providers that implement `extract_all`."""

    fields: list["ExtractedField"] = field(default_factory=list)
    sections: CVSections = field(default_factory=CVSections)

# Canonical field name → German label, in display order (mirrors aiFind's
# "New Candidate" form: personal info → contact → career → history).
CV_FIELDS: dict[str, str] = {
    # Personal
    "full_name": "Name",
    "first_name": "Vorname",
    "last_name": "Nachname",
    "sex": "Geschlecht",
    "name_prefix": "Namenszusatz",
    "date_of_birth": "Geburtsdatum",
    # Contact
    "email": "E-Mail",
    "phone": "Telefon",
    "location": "Standort",
    "street": "Straße",
    "postal_code": "PLZ",
    "city": "Stadt",
    "country": "Land",
    "linkedin_url": "LinkedIn URL",
    "xing_url": "Xing URL",
    # Career
    "current_title": "Job Title",
    "current_company": "Aktuelles Unternehmen",
    "industry": "Branche",
    "employment_type": "Anstellungsart",
    "willing_to_relocate": "Umzugsbereit",
    "notice_period": "Kündigungsfrist",
    "availability": "Verfügbarkeit",
    "total_years_experience": "Berufserfahrung (Jahre)",
    "current_salary": "Aktuelles Gehalt",
    "expected_salary": "Wunschgehalt",
    "salary_currency": "Währung",
    # Lists / free text
    "skills": "Skills",
    "languages": "Sprachen",
    "education": "Ausbildung",
    "working_experience": "Berufserfahrung",
    "motivation": "Motivation",
    "source": "Quelle",
}

FIELD_ORDER: list[str] = list(CV_FIELDS.keys())

# ── The Qualifikationsgespräch ──────────────────────────────────────────────
#
# `data/examples/metadata_quailfication.txt` splits the core data in two: what
# a CV can tell you, and what only the conversation can. These four are the
# second half — no CV states a minimum salary, the other processes someone is
# running, or when they can take an interview.
QUALIFICATION_ONLY_FIELDS: dict[str, str] = {
    "salary_minimum": "Mindestgehalt",
    "other_processes": "Andere aktive Prozesse",
    "interview_availability": "Verfügbarkeit für Interviews",
    "profile_summary": "Profil-Zusammenfassung",
}

#: What a transcript is read for: the post-Gespräch set. The overlap with
#: `CV_FIELDS` is deliberate — a candidate states their notice period in the
#: conversation whether or not the CV mentioned it, and the later source wins
#: by being more recent, not by being different.
_FROM_CV = (
    "notice_period",
    "availability",
    "current_salary",
    "expected_salary",
    "motivation",
    "skills",
)
TRANSCRIPT_FIELDS: dict[str, str] = {
    **{k: CV_FIELDS[k] for k in _FROM_CV},
    **QUALIFICATION_ONLY_FIELDS,
}
TRANSCRIPT_FIELD_ORDER: list[str] = list(TRANSCRIPT_FIELDS.keys())

#: Every field either source can yield — the one place labels come from.
FIELD_LABELS: dict[str, str] = {**CV_FIELDS, **QUALIFICATION_ONLY_FIELDS}

# ── Zeugnisse & Zertifikate ─────────────────────────────────────────────────
#
# A reference is read for what it attests, and every value comes with the
# sentence it was read from. The service drops a value whose sentence is not
# in the document — the quote is what makes the proposal checkable.


@dataclass(frozen=True)
class ReferenceField:
    """One value read from a Zeugnis or Zertifikat, with its verbatim quote."""

    field: str
    value: str
    evidence: str
    confidence: float


ZEUGNIS_FIELDS: dict[str, str] = {
    "employer": "Arbeitgeber",
    "role_title": "Position",
    "period": "Zeitraum",
    "tasks": "Aufgaben",
    "skills": "Skills",
    "leaving_reason": "Beendigung",
    "assessment_quote": "Leistungsbeurteilung",
    "assessment_grade": "Gesamtnote (Interpretation)",
}
ZERTIFIKAT_FIELDS: dict[str, str] = {
    "certificate_name": "Zertifikat",
    "issuer": "Aussteller",
    "issued_on": "Ausgestellt am",
    "skills": "Skills",
}
#: Which fields each readable kind may yield. A Zertifikat read with Zeugnis
#: vocabulary ("employer") must not get that value through.
REFERENCE_FIELDS_BY_KIND: dict[str, dict[str, str]] = {
    "zeugnis": ZEUGNIS_FIELDS,
    "zertifikat": ZERTIFIKAT_FIELDS,
}
REFERENCE_FIELDS: dict[str, str] = {**ZEUGNIS_FIELDS, **ZERTIFIKAT_FIELDS}
REFERENCE_FIELD_ORDER: list[str] = list(REFERENCE_FIELDS.keys())

#: Values that must themselves appear in the text — names, dates, titles. The
#: others (a task summary, a grade) only have to quote a real sentence.
REFERENCE_VERBATIM_FIELDS = frozenset(
    {"employer", "role_title", "period", "leaving_reason", "assessment_quote",
     "certificate_name", "issuer", "issued_on"}
)
#: A reading of coded Zeugnissprache, not a fact the document states.
REFERENCE_INTERPRETED_FIELDS = frozenset({"assessment_grade"})
#: The German grade scale — the only values an interpretation may take.
ZEUGNIS_GRADES = ("sehr gut", "gut", "befriedigend", "ausreichend", "mangelhaft")


# The subset the canonical Candidate row can store today; the rest are extracted
# and shown for review (persisting them is a schema follow-up).
PERSISTABLE_FIELDS = (
    "full_name", "email", "phone", "current_title", "current_company",
    "location", "skills",
)


@runtime_checkable
class CVExtractor(Protocol):
    """Turns raw CV text into extracted fields. Pure w.r.t. the DB — it reads no
    state and writes none; confidence-gating and verification happen downstream."""

    name: str

    def extract(self, text: str) -> list[ExtractedField]: ...

    # Optional: flat fields AND structured history in a SINGLE call. Providers
    # that implement it are driven through this (one LLM round-trip per CV);
    # those that don't (the heuristic fallback) use `extract` and yield no
    # structured sections.
    def extract_all(self, text: str) -> ExtractionResult: ...

    # Optional: read a Gesprächstranskript for the qualification fields
    # (`TRANSCRIPT_FIELDS`). A provider that cannot do it yields nothing and
    # the caller says so — guessing a salary floor out of a regex would be
    # worse than an empty form.
    def extract_qualification(self, text: str) -> list[ExtractedField]: ...

    # Optional: read a Zeugnis or Zertifikat (`kind`) for `REFERENCE_FIELDS`,
    # each value with the sentence it came from. Same rule: a provider that
    # cannot do it yields nothing.
    def extract_reference(self, text: str, kind: str) -> list[ReferenceField]: ...
