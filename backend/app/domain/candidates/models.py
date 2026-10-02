"""Candidate ORM model — the canonical, de-duplicated person record.

``verification_score`` reflects how much of the profile has been human- or
postcondition-verified (vs. raw agent proposals) — surfaced to recruiters and
required for EU AI Act transparency about automated data.
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.enums import WorkPermitStatus
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONList


class Candidate(Base, IDMixin, TenantMixin, TimestampMixin):
    """A canonical candidate profile."""

    __tablename__ = "candidates"

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Identity in the system this row was imported from. Unique per
    #: (tenant, external_source, external_id) so a re-import updates instead of
    #: duplicating.
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    external_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    current_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # --- Extended profile (aiFind field set) -----------------------------
    # All nullable so they can be added to an existing table without a backfill.
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name_prefix: Mapped[str | None] = mapped_column(String(40), nullable=True)
    date_of_birth: Mapped[str | None] = mapped_column(String(40), nullable=True)

    street: Mapped[str | None] = mapped_column(String(200), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)

    linkedin_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    xing_url: Mapped[str | None] = mapped_column(String(300), nullable=True)

    #: What the source called the candidate's industry — ONE label, often a
    #: compound one ("Pharma, MedTech und Gesundheitsbranche"). Kept as the
    #: imported value; `industries` is the field of record. Dropped once
    #: nothing reads it (expand/contract, see migration 0030).
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Every industry the candidate has worked in. The document asks for
    #: "Branchen", plural — a career in Luftfahrt AND Behörden AND Bundeswehr
    #: cannot be said in one slot, and that breadth is exactly what makes
    #: someone placeable in a second market.
    industries: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    #: The source's own words ("Permanent", "Contract, Permanent", "Founder").
    employment_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: The decidable form: festanstellung | freelance | beides, or NULL when
    #: nobody has established it. This is what a filter reads.
    employment_form: Mapped[str | None] = mapped_column(String(20), nullable=True)
    willing_to_relocate: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notice_period: Mapped[str | None] = mapped_column(String(80), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(80), nullable=True)
    total_years_experience: Mapped[str | None] = mapped_column(String(40), nullable=True)
    current_salary: Mapped[int | None] = mapped_column(Integer, nullable=True)

    languages: Mapped[list | None] = mapped_column(JSONList, nullable=True)
    education: Mapped[list | None] = mapped_column(JSONList, nullable=True)
    working_experience: Mapped[list | None] = mapped_column(JSONList, nullable=True)

    motivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # De-duplication: source identity keys that were merged into this record.
    merged_identities: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )
    skills: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    work_history: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )

    salary_expectation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The floor, as asked in the Qualifikationsgespräch. A candidate names
    #: two numbers ("Minimum 92–95k, Wunsch ~100k") and only the pair says
    #: whether a mandate's band can work — `salary_expectation` is the Wunsch.
    salary_minimum: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    #: The recruiter's own summary of the Gesprächszusammenfassung (section B
    #: of the Kandidatenauswertung) — holds across mandates, so it lives here
    #: and not on the application.
    profile_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: "Mittwoch/Donnerstag ab 11–12 Uhr" — scheduling needs the window, and a
    #: window buried in a note cannot be read when booking a round.
    interview_availability: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Other processes the candidate is running, in their own words. Timing
    #: pressure, and the note behind the names below.
    other_processes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: WHERE those processes are running, as company names.
    #:
    #: The document is explicit about why: "im Idealfall sagt er uns wo -> so
    #: wissen wir wer ähnliche Profile sucht und ist für uns ein potentieller
    #: Neukunde". A sentence cannot be counted across a pool; names can, and
    #: three candidates naming the same company is a sales lead.
    other_process_companies: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )
    availability_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    work_permit: Mapped[WorkPermitStatus] = mapped_column(
        String(30), default=WorkPermitStatus.UNKNOWN, nullable=False
    )

    # 0.0-1.0 — share of the profile that is verified rather than proposed.
    verification_score: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )

    # Optional embedding (JSON list on SQLite; pgvector column on Postgres).
    embedding: Mapped[list | None] = mapped_column(JSONList, nullable=True)