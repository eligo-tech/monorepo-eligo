"""Verification ORM models: the append-only Receipt ledger and the
EnrichmentRecord proposed-change log.

Receipts are append-only proof of every agent action (read / assert / verify /
write). Each receipt chains to the previous one for its tenant via a hash,
making the ledger tamper-evident — supports EU AI Act traceability and GDPR
Art. 22 (contestability of automated decisions) obligations.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.enums import ConfidenceSource, ReceiptAction
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONDict


class Receipt(Base, IDMixin, TenantMixin, TimestampMixin):
    """Append-only, hash-chained record of a single agent action.

    Never updated or deleted (enforced by convention + service layer). Each row
    stores the hash of the previous receipt for the same tenant, so tampering
    with any historical row breaks the chain.
    """

    __tablename__ = "receipts"

    agent: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[ReceiptAction] = mapped_column(String(20), nullable=False)

    # What the action targeted (e.g. "candidate", "<uuid>", "email").
    subject_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(80), nullable=False)

    # Outcome + free-form structured detail (postcondition results, payloads).
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)

    # Tamper-evidence: hash of this receipt + hash of the previous one.
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class EnrichmentRecord(Base, IDMixin, TenantMixin, TimestampMixin):
    """A single proposed field change with provenance and confidence.

    Produced by enrichment / extraction agents. Persisted whether or not it was
    committed, so the provenance of every value in a candidate profile is
    auditable (GDPR Art. 14 — origin of personal data not obtained from the
    data subject).
    """

    __tablename__ = "enrichment_records"

    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(), index=True, nullable=False)

    field: Mapped[str] = mapped_column(String(120), nullable=False)
    proposed_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[ConfidenceSource] = mapped_column(String(40), nullable=False)
    source_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    committed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    needs_human_review: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Link to the receipt that recorded the verify/write decision.
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("receipts.id"), nullable=True
    )