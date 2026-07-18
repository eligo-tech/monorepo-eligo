"""Tenant ORM model — one row per organization (Clerk org)."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TimestampMixin


class Tenant(Base, IDMixin, TimestampMixin):
    """An organization. `id` is the `tenant_id` every other table references."""

    __tablename__ = "tenants"

    # The Clerk organization id (e.g. "org_2ab…"). Unique — one tenant per org.
    clerk_org_id: Mapped[str] = mapped_column(
        String(120), unique=True, index=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
