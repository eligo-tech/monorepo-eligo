"""What each consultant did, and what they were asked to do (ELI-15).

The ticket: *"Jeder Consultant muss seine Tätigkeiten tracken und managen
können. Dabei soll es möglich sein, dass für jeden Consultant
unterschiedliche Ziele vorgegeben werden."*

The process document states the rule this follows: **every figure comes from
an event the system records anyway — no manual counting.** So nothing here
asks anybody to tick a box at the end of the week. A note saved against a
manager is a business call; a process step reaching "Vorgestellt" is a
candidate presented. This table is where those two facts get an owner and a
timestamp.

Why a separate table rather than an `actor_user_id` column on each source
row: the sources are not comparable. A manager note and a process step live
in different domains with different lifecycles, and counting across them
would mean a UNION of two schemas that keep changing. An append-only event
is one shape, one index, one query — and it is the shape the process
document's §6 asks for (`ActivityEvent: type, recruiter_id, timestamp,
ref_type, ref_id`).
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin


class ActivityEvent(Base, IDMixin, TenantMixin, TimestampMixin):
    """One thing a consultant did, counted by exactly one KPI."""

    __tablename__ = "activity_events"
    __table_args__ = (
        # The whole table is read as "events of this kind, in this window".
        Index("ix_activity_events_kind_when", "tenant_id", "event_type", "occurred_at"),
        # Re-saving a note must not count it twice. The source row's id is the
        # identity, so a write is an upsert on (type, ref) rather than an
        # append — "append-only" here means we never delete, not that we
        # blindly insert.
        UniqueConstraint(
            "tenant_id", "event_type", "ref_id", name="uq_activity_event_ref"
        ),
    )

    #: A key from `kpis.EVENT_TYPES`. Stored rather than derived so a KPI
    #: definition can change without rewriting history.
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)

    #: The Clerk `sub` of whoever did it. NULL is a real and common answer:
    #: everything imported from aiFind, and everything recorded before this
    #: table existed, genuinely has no author. The UI shows that as "nicht
    #: zugeordnet" rather than quietly attributing it to somebody.
    actor_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    #: Denormalised on purpose: there is no users table, the name lives in
    #: Clerk, and a KPI list that has to call an identity provider per row to
    #: render a name is a KPI list nobody opens.
    actor_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: WHEN IT HAPPENED, not when it was typed. A call logged on Monday for
    #: last Friday belongs in last week's numbers, which is the difference
    #: between a KPI and a keystroke counter.
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    #: What it was about, for drill-down and for the uniqueness above.
    ref_type: Mapped[str] = mapped_column(String(30), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(nullable=False)


class ActivityTarget(Base, IDMixin, TenantMixin, TimestampMixin):
    """What one consultant is asked to do in one period — the Ziel.

    `actor_user_id` NULL is the workspace-wide default: *"wir als Admins
    [können] unsere Ziele selbst festlegen"*. A consultant with no row of
    their own inherits it, so a workspace can set one number for everybody
    and override the two people it does not fit.
    """

    __tablename__ = "activity_targets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "actor_user_id", "kpi", "period", name="uq_activity_target"
        ),
    )

    actor_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kpi: Mapped[str] = mapped_column(String(40), nullable=False)
    #: "woche" | "monat" | "quartal" — the periods the design offers.
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
