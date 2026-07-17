"""Company ORM model.

A company is either a paying ``client`` or an ``external`` company surfaced by
the market-map agent from PUBLIC sources only.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONDict


class Company(Base, IDMixin, TenantMixin, TimestampMixin):
    """A client or external company."""

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    is_client: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # For external companies: which public source it came from (market map).
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Business-development signals gathered from public data.
    bd_signals: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)