"""Job ORM model — a client hiring mandate."""

from __future__ import annotations

import uuid

from sqlalchemy import Index, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONList


class Job(Base, IDMixin, TenantMixin, TimestampMixin):
    """A role a client wants filled."""

    __tablename__ = "jobs"

    __table_args__ = (
        # Declared here as well as in migration 0020, so every database built
        # by `create_all` (the tests' included) refuses the same ad twice.
        Index("ix_jobs_external_identity", "tenant_id", "external_source", "external_id", unique=True),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    client_company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True, index=True
    )

    # Who owns this mandate. Nullable: a role can be logged before the contact
    # is known, and backfilling a person you have not met is not possible.
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("managers.id"), nullable=True, index=True
    )

    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Radius (km) around the location used by the deterministic location filter.
    location_radius_km: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Hard requirements evaluated deterministically before any LLM ranking.
    must_have_skills: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )
    required_certifications: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )
    requires_work_permit: Mapped[bool] = mapped_column(
        default=True, nullable=False
    )

    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    status: Mapped[str] = mapped_column(
        String(30), default="active", nullable=False
    )

    # ── Briefing points with no other home (ELI-47, migration 0079) ──────
    # What the client said in the briefing call, as the recruiter wrote it
    # down. Free text on purpose: "zum 1. März, notfalls später" and "6 Devs
    # + PO" are answers a date or an int column would refuse. None of these
    # is a matching input — the hard filters stay on the columns above.
    #: Aufgaben — what the person will actually do.
    tasks: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Kann-Kriterien. Never a hard filter: nice-to-have excludes nobody.
    nice_to_have_skills: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )
    #: Startdatum, as agreed ("sofort", "Q2", "zum 1. März").
    start_date: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Teamgröße ("6 Entwickler + PO").
    team_size: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Prozess beim Kunden — interview rounds, who decides.
    interview_process: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Grund der Vakanz (Nachfolge, Wachstum, neue Abteilung …).
    vacancy_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: The mandate this one was copied from (ELI-7). An inactive mandate is
    #: final, so working the role again means a new row — and without this the
    #: new row cannot say that it continues the old one, which is the whole of
    #: "wurde die Stelle nachbesetzt?". Nullable and never required: most
    #: mandates are not copies.
    copied_from_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True
    )
    #: Identity in the system this row was imported from. Unique per
    #: (tenant, external_source, external_id) so a re-import updates instead of
    #: duplicating.
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    external_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
