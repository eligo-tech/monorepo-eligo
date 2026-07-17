"""Reusable ORM column mixins.

Every core table composes these so the platform is uniformly:
  * UUID-keyed (``IDMixin``),
  * multi-tenant (``TenantMixin`` — a ``tenant_id`` on every row), and
  * auditable (``TimestampMixin``).

The ``sqlalchemy.Uuid`` type is dialect-portable: native ``UUID`` on Postgres,
``CHAR(32)`` on SQLite — so the same models run on both.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class IDMixin:
    """UUID primary key."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        primary_key=True,
        default=uuid.uuid4,
    )


class TenantMixin:
    """Multi-tenancy discriminator. Indexed — every tenant-scoped query filters
    on it. Row-level isolation is enforced in the service layer."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        index=True,
        nullable=False,
    )


class TimestampMixin:
    """Created/updated audit timestamps (UTC, DB-side defaults)."""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )