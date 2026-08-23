"""Verification ORM models: the append-only Receipt ledger and the
EnrichmentRecord proposed-change log.

Receipts are append-only proof of every agent action (read / assert / verify /
write). Each receipt chains to the previous one for its tenant via a hash,
making the ledger tamper-evident — supports EU AI Act traceability and GDPR
Art. 22 (contestability of automated decisions) obligations.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.enums import ConfidenceSource, ReceiptAction
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONDict


class Receipt(Base, IDMixin, TenantMixin, TimestampMixin):
    """Append-only, hash-chained record of a single agent action.

    Each row stores the hash of its predecessor for the same tenant, so altering
    any historical row breaks the chain.

    **Position is explicit.** `chain_index` is a per-tenant sequence, and
    `UNIQUE (tenant_id, chain_index)` is what makes the chain a chain: two
    concurrent appends cannot both claim the same position, so the database
    rejects a fork instead of the ledger silently growing two heads that
    `verify_chain` would later report as tampering. Ordering by it is also
    honest — the previous ordering was by `created_at`, whose resolution is a
    property of the clock rather than of the data.

    **Immutability is enforced by the database**, not by convention: migration
    0014 revokes UPDATE/DELETE from the runtime role and installs triggers that
    refuse both. The service layer being careful is not a guarantee; a service
    bug or a stolen application credential was previously enough to rewrite the
    whole ledger and recompute every hash.

    Known residual: a hash chain detects modification and mid-chain insertion,
    and `chain_index` gaps now catch deletion — but TRUNCATION at the head is
    still invisible from inside. Detecting that needs an externally anchored
    head (see ARCHITECTURE.md §4).
    """

    __tablename__ = "receipts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "chain_index", name="uq_receipt_chain_position"),
    )

    # Position in this tenant's ledger, from 0. The uniqueness constraint above
    # is the actual anti-fork mechanism.
    chain_index: Mapped[int] = mapped_column(Integer, nullable=False)

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

# ---------------------------------------------------------------------------
# Append-only, enforced by the database
# ---------------------------------------------------------------------------
#
# Attached to the TABLE rather than declared only in a migration, because
# `receipts` is created by `create_all` as well as by Alembic. A guarantee that
# exists on one of those paths is a guarantee that CI never exercises — and an
# untested guarantee is a claim.
#
# The trigger refuses UPDATE and DELETE for everyone, including the table owner,
# so it catches a service bug or a stray admin statement and not merely a
# misconfigured grant. Migration 0014 additionally revokes both privileges from
# the runtime role, so a stolen application credential never held them.

_PG_APPEND_ONLY = """
CREATE OR REPLACE FUNCTION receipts_are_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'receipts are append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS receipts_no_update ON receipts;
DROP TRIGGER IF EXISTS receipts_no_delete ON receipts;

CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts
    FOR EACH ROW EXECUTE FUNCTION receipts_are_append_only();
CREATE TRIGGER receipts_no_delete BEFORE DELETE ON receipts
    FOR EACH ROW EXECUTE FUNCTION receipts_are_append_only();
"""

_SQLITE_APPEND_ONLY = (
    "CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts "
    "BEGIN SELECT RAISE(ABORT, 'receipts are append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts "
    "BEGIN SELECT RAISE(ABORT, 'receipts are append-only'); END",
)


@event.listens_for(Receipt.__table__, "after_create")
def _install_append_only_guard(target, connection, **kw) -> None:  # noqa: ARG001
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(_PG_APPEND_ONLY)
    elif connection.dialect.name == "sqlite":
        for statement in _SQLITE_APPEND_ONLY:
            connection.exec_driver_sql(statement)
