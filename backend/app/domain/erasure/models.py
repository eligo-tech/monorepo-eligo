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

from sqlalchemy import Date, DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONBDict


def app_role_privileges(role: str) -> list[str]:
    """What the runtime role may do to these two tables — narrower than the
    blanket DML grant every other table gets.

    * `erasure_requests` is insert-only: rewriting or deleting a row would hide
      that an erasure happened, and `verify_chain` trusts it as the backing of
      every blackout.
    * `tenant_suppressions` may be inserted and LIFTED, nothing else: deleting
      a row, or changing its fingerprint, would silently let the person back.

    Applied by migration 0049 on existing databases and by
    `scripts/apply_rls.py` after its blanket grant (which would otherwise
    undo it). Proved in tests/test_erasure_postgres.py.
    """
    return [
        f'REVOKE UPDATE, DELETE, TRUNCATE ON erasure_requests FROM "{role}"',
        f'REVOKE UPDATE, DELETE, TRUNCATE ON tenant_suppressions FROM "{role}"',
        f'GRANT SELECT, INSERT ON erasure_requests, tenant_suppressions TO "{role}"',
        f'GRANT UPDATE (lifted_at, lifted_by_user_id, lifted_by_name, updated_at) '
        f'ON tenant_suppressions TO "{role}"',
    ]


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

    #: The request that wrote it. Not a foreign key on purpose: a FK check
    #: needs UPDATE rights on the parent, and the app role holds none on
    #: `erasure_requests` (insert-only, migration 0049).
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    #: "import_id" (source:external_id) | "email".
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    #: HMAC-SHA256 hex of tenant:kind:normalised value (see service.digest).
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    lifted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifted_by_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lifted_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
