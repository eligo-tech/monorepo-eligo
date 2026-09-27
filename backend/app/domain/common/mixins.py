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
    """Created/updated audit timestamps (UTC).

    Both a DB-side default AND a client-side one, deliberately. The DB default
    only exists on tables whose migration remembered to write it: migration
    0025 did not, so inserting a project on Postgres failed with "null value in
    column created_at" while every test passed — tests build their schema from
    these models, where `create_all` carries the default. The client-side
    `default` makes the insert correct whatever the table was built by.
    """

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )