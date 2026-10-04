"""A workspace's own data sources — where ITS book of business comes from.

Onboarding a customer used to mean an operator running
`scripts/ats_import --tenant <uuid>` with that customer's ATS password in
their shell. That does not scale past one customer and it puts somebody else's
credential in somebody's terminal history.

This is the same import, made part of the product: the workspace stores its
own credential (encrypted), asks for an import, and a scheduled job performs
it. The asking and the doing are separate on purpose — see `service.py`.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONDict


class TenantSource(Base, IDMixin, TenantMixin, TimestampMixin):
    """One configured source for one workspace."""

    __tablename__ = "tenant_sources"
    __table_args__ = (
        # One configuration per source per workspace: two accounts on the
        # same system under one tenant would import two books into one record
        # with no way to tell them apart afterwards.
        UniqueConstraint("tenant_id", "kind", name="uq_tenant_source_kind"),
    )

    #: Which source — a key from the connector registry. Open by design: the next one
    #: (a different ATS, a CSV drop) changes nothing else here.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: The login. Stored in the clear — it is an e-mail address, and hiding it
    #: would stop a recruiter recognising which account is connected.
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    #: The password, Fernet-encrypted (`app/core/secrets.py`). Never returned
    #: by the API, not even masked back to the workspace that set it.
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: "active" | "disabled". A disabled source keeps its credential but is
    #: skipped by the runner — the way to pause an import without re-typing a
    #: password later.
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    #: Set when the workspace asks for an import; cleared when one runs. This
    #: single field is the whole request queue, and it is idempotent: asking
    #: twice before the job runs is one import, not two.
    import_requested_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: What the last run did: counts per entity, or nothing on a failure.
    last_result: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)
    #: Why the last run failed, in words a recruiter can act on ("Login
    #: abgelehnt" is actionable; a stack trace is not).
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
