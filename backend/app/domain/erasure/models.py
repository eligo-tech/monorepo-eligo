"""Erasure inside a workspace: the request log and the suppression list (Art. 17/21).

The workspace (the recruiting agency) is the controller and decides; Eligo
carries it out. Two tables, both tenant-scoped and RLS-policed:

* ``erasure_requests`` — that a request was handled: when the person asked,
  when it was carried out, by whom, what kind of record, how much went. It
  names nobody: no name, no e-mail, not the erased row's id. Classification:
  tenant record (accountability, Art. 5(2)), not personal data of the subject.
* ``tenant_suppressions`` — what stops the next import bringing the person
  back. Keyed HMAC fingerprints of their import ids and e-mails, never the
  values. A fingerprint is still personal data while the key exists; it is
  kept because honouring the request requires it (Art. 17(3)(b)). Lifted,
  not deleted, when the person comes back of their own accord.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONBDict


class ErasureRequest(Base, IDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "erasure_requests"

    #: "candidate" | "manager".
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    #: "erasure" (Art. 17) | "objection" (Art. 21).
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    #: The day the person asked — the clock the controller answers to.
    requested_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    executed_by_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    executed_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    #: Rows removed per table, and receipts blacked out. Numbers only.
    counts: Mapped[dict] = mapped_column(JSONBDict, default=dict, nullable=False)
    erase_receipt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)


class TenantSuppression(Base, IDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "tenant_suppressions"
    __table_args__ = (Index("ix_tenant_suppressions_digest", "tenant_id", "digest"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("erasure_requests.id"), nullable=False, index=True
    )
    #: "import_id" (source:external_id) | "email".
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    #: HMAC-SHA256 hex of tenant:kind:normalised value (see service.digest).
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    lifted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifted_by_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lifted_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
