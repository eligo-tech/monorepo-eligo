"""Manager ORM models — the hiring-side person, and the record of talking to them.

A manager is the link the rest of the model hangs on: companies do not hire,
people do. A mandate belongs to a person, a candidate is introduced to a person,
and the relationship that wins the next mandate is with a person — not with a
legal entity.

**These rows are personal data, and that decides where they live.**
ARCHITECTURE.md RULE 2 lets the shared `hub_*` corpus hold a person only as a
public source published them (the contact named in a job ad). A manager is more
than that: it is this tenant's relationship — imported contacts, enriched
emails/phones, LinkedIn/XING, notes — none of which may leave the tenant. So
managers are tenant-scoped like candidates, and
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

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.common.enums import ConfidenceSource, owes_art14_notice
from app.domain.common.mixins import CreatedByMixin, IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONBList


class Manager(Base, IDMixin, TenantMixin, TimestampMixin, CreatedByMixin):
    """A hiring manager or client contact at one of this tenant's companies."""

    __tablename__ = "managers"
    #: ELI-23: the Bus-Dev list and the Manager screen each read one stage.
    __table_args__ = (Index("ix_managers_tenant_stage", "tenant_id", "stage"),)

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
    #: The PRIMARY number (ELI-46) — what the Leads list, "Anruf erfassen"
    #: and every older reader show. Further numbers are `extra_phones`. Kept
    #: on this row rather than moved, so the importers and the ad-contact
    #: adoption, which write `phone`, keep working untouched: a re-import
    #: replaces the primary and leaves the numbers a recruiter added alone.
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: Kind of the primary (`PHONE_KINDS`). NULL reads as "other" (Sonstige):
    #: every number written before ELI-46, and every importer's, is one whose
    #: kind nobody stated.
    phone_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    skills: Mapped[list] = mapped_column(JSONBList, default=list, nullable=False)
    tags: Mapped[list] = mapped_column(JSONBList, default=list, nullable=False)
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
    #: ELI-23: "bus_dev" — a new contact taken from Markt (a public ad), not
    #: yet vetted; listed under Bus-Dev-Kontakte. "manager" — a vetted contact
    #: (imported, entered by hand, or moved over after the first contact).
    #: Same record either way: provenance and the Art. 14 duty travel with it.
    stage: Mapped[str] = mapped_column(String(20), default="manager", server_default="manager", nullable=False)
    #: When a bus-dev contact was moved to Managers.
    promoted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ELI-32: the person asked not to be contacted again. The record stays
    #: (a Leads row with a red mark); the call list, the Wiedervorlage and
    #: Markt stop offering them until a person undoes it. The reason is a
    #: code (`requested`), never free text — the note carries the words.
    do_not_contact_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    do_not_contact_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: ELI-60: a lead called with the outcome "Kein Interesse". A SALES
    #: status, not the ELI-32 mark: the Leads list hides them by default
    #: (filter "Kein Interesse"), Markt shows them as such and does not take
    #: them again; the record, the call and its note stay. Cleared by
    #: "Wieder als Lead aufnehmen". Set only on leads (stage `bus_dev`).
    no_interest_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ELI-66: "Entfernen" — a lead hidden by hand, on the same
    #: `no_interest_at` (off Leads, restorable, not taken again from Markt),
    #: with WHY: a code (`REMOVE_REASONS`) and, optionally, the recruiter's
    #: words. Both cleared with `no_interest_at`. NULL reason with a date =
    #: ELI-60's "Kein Interesse" from a call.
    removed_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    removed_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: ELI-65: the vacancy a lead entered by hand is about ("Job" on the
    #: "+ Lead" form) — a job Markt does not hold, so there is no ad row to
    #: link it to. Shown on the Leads row and the lead page like a Markt
    #: lead's ad. NULL for every other contact.
    lead_job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    @property
    def manual_lead(self) -> bool:
        """ELI-65: a lead entered by hand rather than taken from Markt —
        the "manuell" mark on the Leads list. Derived: a Markt lead is the
        public ad's (`public_web`); `create_manual_lead` is the only path
        that writes a `bus_dev` row from any other source. A new such path
        must decide whether it is "manuell" too."""
        return self.stage == "bus_dev" and self.source != ConfidenceSource.PUBLIC_WEB.value

    interactions: Mapped[list["ManagerInteraction"]] = relationship(
        "ManagerInteraction",
        back_populates="manager",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    #: ELI-46: the numbers besides the primary. Loaded with the row
    #: ("selectin", one IN query per batch) because `phones` is part of
    #: every read of a manager, and an async lazy load would fail.
    extra_phones: Mapped[list["ManagerPhone"]] = relationship(
        "ManagerPhone",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="ManagerPhone.position",
    )

    @property
    def phones(self) -> list[dict]:
        """Every number, the primary first (ELI-46)."""
        out = []
        if self.phone:
            out.append({"number": self.phone, "kind": self.phone_kind or "other", "is_primary": True})
        out += [{"number": p.number, "kind": p.kind, "is_primary": False} for p in self.extra_phones]
        return out

    @property
    def art14_outstanding(self) -> bool:
        """A notice is owed and has not been sent.

        Derived, never stored: a stored flag and the source column can disagree,
        and when they do the row silently stops owing a notice it still owes.
        """
        return owes_art14_notice(self.source) and self.art14_notified_at is None


#: Mobil · Durchwahl · Zentrale · Sonstige (ELI-46).
PHONE_KINDS = ("mobile", "direct", "switchboard", "other")


class ManagerPhone(Base, IDMixin, TenantMixin, TimestampMixin):
    """A further number of one manager (ELI-46) — the primary is `managers.phone`.

    Personal data like the row it belongs to: tenant-scoped, fail-closed RLS
    (migration 0077), deleted with the manager and by an erasure, whose
    suppression fingerprints every direct number here too.
    """

    __tablename__ = "manager_phones"

    manager_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("managers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="other", server_default="other")
    #: Order on the card, as the recruiter entered them.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


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
    __table_args__ = (
        # The call list's follow-up queue: calls with a next date, per
        # workspace. Partial — most interactions have no next call.
        Index(
            "ix_manager_interactions_next_action",
            "tenant_id",
            "next_action_at",
            postgresql_where=text("next_action_at IS NOT NULL"),
            sqlite_where=text("next_action_at IS NOT NULL"),
        ),
    )

    #: Nullable since migration 0034: a BRIEFING belongs to the mandate, and
    #: a mandate whose contact is not recorded yet is an ordinary state — the
    #: GE example literally reads "Kein Ansprechpartner hinterlegt". Requiring
    #: a contact first would mean the note does not get written at all, and an
    #: unwritten briefing is worse than one without a name on it.
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("managers.id", ondelete="CASCADE"), nullable=True, index=True
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
    #: Who recorded it (the Clerk `sub`), for the per-consultant KPIs in
    #: ELI-15. NULL is a real and common answer: everything the aiFind
    #: importer wrote, and everything saved before this column existed,
    #: genuinely has no author. The tracking screen shows that as "Nicht
    #: zugeordnet" rather than attributing it to somebody.
    #:
    #: A column here rather than a separate events table: the row IS the
    #: event, and a second copy of it could only drift from this one.
    actor_user_id: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    #: Denormalised deliberately — there is no users table, the name lives
    #: in Clerk, and a KPI list that calls an identity provider per row is a
    #: list nobody opens.
    actor_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: Identity in the system this note came from, so a re-import updates the
    #: same row instead of appending the conversation again.
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    external_source: Mapped[str | None] = mapped_column(String(80), nullable=True)

    #: How the call ended (`CallOutcome`) and when to call again — ELI-22's
    #: call list. NULL for interactions that are not calls with an outcome.
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    next_action_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    manager: Mapped["Manager"] = relationship("Manager", back_populates="interactions")
