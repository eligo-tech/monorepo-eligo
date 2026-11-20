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

from sqlalchemy import DateTime, String, Uuid, func
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


def _actor_user_id() -> str | None:
    from app.core.context import current_actor_var

    actor = current_actor_var.get()
    return actor.user_id if actor else None


def _actor_name() -> str | None:
    from app.core.context import current_actor_var

    actor = current_actor_var.get()
    return (actor.name or None) if actor and actor.user_id else None


class CreatedByMixin:
    """Who created the row (ELI-64), for the per-consultant tracking KPIs.

    Filled from the request's actor at INSERT, not by each create path: a
    lead is created by Markt adoption, by hand on the Leads screen and by
    "Manager hinzufügen", and a column every path had to remember is the
    column the next path forgets. Outside a request (cron, an import script)
    there is no person, and NULL says so — the tracking screen shows that
    as "Nicht zugeordnet".
    """

    created_by_user_id: Mapped[str | None] = mapped_column(
        String(80), default=_actor_user_id, nullable=True
    )
    #: Denormalised like `actor_name` on the KPI source rows: there is no
    #: users table, the name lives in Clerk.
    created_by_name: Mapped[str | None] = mapped_column(
        String(160), default=_actor_name, nullable=True
    )