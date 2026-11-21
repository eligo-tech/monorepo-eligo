"""Company ORM model.

A company is either a paying ``client`` or an ``external`` company surfaced by
the market-map agent from PUBLIC sources only.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import CreatedByMixin, IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONDict


class Company(Base, IDMixin, TenantMixin, TimestampMixin, CreatedByMixin):
    """A client or external company.

    ELI-69: `created_by_*` (from `CreatedByMixin`) is the account that added
    it — "+ Unternehmen", a lead by hand, adoption from Markt. NULL for an
    import, a system job, or a row older than the column that no receipt
    attributes (`scripts/backfill_created_by.py`).
    """

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: ELI-64: "Rahmenvertrag abgeschlossen" — the day a framework agreement
    #: with this company was signed, as a person entered it on the company
    #: page. The cheapest honest source for the tracking KPI: there is no
    #: contract entity, and a date plus who set it is what the KPI counts.
    #: NULL = none recorded (not "none exists").
    framework_contract_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    framework_contract_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    framework_contract_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Identity in the system this row was imported from. Unique per
    #: (tenant, source, external_id) so a re-import updates instead of
    #: duplicating. `source` above names the system.
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    is_client: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # For external companies: which public source it came from (market map).
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Business-development signals gathered from public data.
    bd_signals: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)

    #: ELI-39: the company's own Impressum, read by the daily job
    #: (`companies/impressum.py`) — status and when it was checked; when
    #: "verified" also the website, VAT id, register and the page's URL, fetch
    #: time and content hash. Written only through the verification gate.
    #: Null: never checked.
    impressum: Mapped[dict | None] = mapped_column(JSONDict, nullable=True)