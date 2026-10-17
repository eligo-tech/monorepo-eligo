"""A workspace's recorded consent to a gated feature.

One row per acceptance. Revoking stamps `revoked_at` on the active row; a
later acceptance is a new row, so the table reads as the history of who
switched the feature on and off, and under which terms. The receipts ledger
carries the same events tamper-evidently.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin


class TenantFeatureConsent(Base, IDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "tenant_feature_consents"

    #: Key from `features.service.FEATURES`, e.g. "interviewer".
    feature: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    #: The terms text the admin accepted. A new version of the terms needs a
    #: new acceptance — consent to old terms does not carry over.
    terms_version: Mapped[str] = mapped_column(String(20), nullable=False)
    accepted_by: Mapped[str] = mapped_column(String(200), nullable=False)
    accepted_by_user_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
