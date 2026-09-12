"""Manager ORM models — the hiring-side person, and the record of talking to them.

A manager is the link the rest of the model hangs on: companies do not hire,
people do. A mandate belongs to a person, a candidate is introduced to a person,
and the relationship that wins the next mandate is with a person — not with a
legal entity.

**These rows are personal data, and that decides where they live.**
ARCHITECTURE.md RULE 2 forbids natural persons in the shared `hub_*` corpus: a
person in a shared table means one erasure request reaches across every
customer, and it would make us controller of personal data we simultaneously
distribute to third parties. So managers are tenant-scoped like candidates, and
`company_id` points at the tenant's OWN `companies` row — never at a corpus
company. Adopting a corpus company into `companies` is the gated crossing that
already leaves a receipt; a manager is added after it, not instead of it.

Provenance is carried from the first migration rather than retrofitted, because
it cannot be recovered later: once a row exists without a source, where it came
from is unknowable, and Art. 14 turns on exactly that.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.common.enums import ConfidenceSource, owes_art14_notice
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONList


class Manager(Base, IDMixin, TenantMixin, TimestampMixin):
    """A hiring manager or client contact at one of this tenant's companies."""

    __tablename__ = "managers"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # What they do, which is what decides whether they can sign off a hire.
    role_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)

    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    xing_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    facebook_url: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # --- provenance: not optional, and not addable later ------------------
    #: Where this person's data came from. Drives the Art. 14 obligation.
    source: Mapped[str] = mapped_column(
        String(40), default=ConfidenceSource.SELF_REPORTED.value, nullable=False
    )
    #: The specific origin — a mailbox thread, a page URL, an import file.
    #: "third_party_source" without saying WHICH is not a defensible record.
    source_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Set when the subject has actually been informed. NULL while a notice is
    #: outstanding, which is why `art14_outstanding` reads it rather than a bool
    #: that could be flipped without anything having been sent.
    art14_notified_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: "MNGR197" — the reference a recruiter reads out on a call.
    external_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    street: Mapped[str | None] = mapped_column(String(200), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: What the person is open to — "Looks for: Contract".
    looks_for: Mapped[str | None] = mapped_column(String(200), nullable=True)
    skills: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    tags: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    #: Taken from the source rather than derived from `interactions`: the source
    #: knows about contact that predates anything we imported, and recomputing
    #: it from our own rows would quietly move the date backwards.
    last_contact_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Identity in the system this row was imported from. Unique per
    #: (tenant, external_source, external_id) so a re-import updates instead of
    #: duplicating.
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    external_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)

    interactions: Mapped[list["ManagerInteraction"]] = relationship(
        "ManagerInteraction",
        back_populates="manager",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def art14_outstanding(self) -> bool:
        """A notice is owed and has not been sent.

        Derived, never stored: a stored flag and the source column can disagree,
        and when they do the row silently stops owing a notice it still owes.
        """
        return owes_art14_notice(self.source) and self.art14_notified_at is None


class ManagerInteraction(Base, IDMixin, TenantMixin, TimestampMixin):
    """One touch on the relationship — a call, a mail, a meeting, a note.

    Append-only by convention rather than by trigger: this is a working record,
    not the receipt ledger, so it carries no integrity guarantee and must not be
    used as evidence for anything the verification layer is responsible for.

    `candidate_id` is nullable on purpose. Most interactions are about the
    account; the ones that name a candidate are the ones that become a
    placement, and being able to ask "who have I already sent them?" is the
    point of recording it at all.
    """

    __tablename__ = "manager_interactions"

    manager_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("managers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidates.id"), nullable=True, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True
    )

    interaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Identity in the system this note came from, so a re-import updates the
    #: same row instead of appending the conversation again.
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    external_source: Mapped[str | None] = mapped_column(String(80), nullable=True)

    manager: Mapped["Manager"] = relationship("Manager", back_populates="interactions")
