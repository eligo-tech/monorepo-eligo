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
FIELD_LABELS: dict[str, str] = CV_FIELDS

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
