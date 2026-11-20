"""The goals a consultant is measured against (ELI-15).

**One table, and it holds something nothing else holds.** An earlier draft
of this feature also kept an `activity_events` table that copied every
countable action out of `manager_interactions` and `process_steps`. That
was a second copy of facts the record already had: the same call stored
twice, free to disagree the moment a note was edited or deleted through a
path that did not know to update the copy.

What those rows actually lacked was an author, so that is what they got —
`actor_user_id` on each source table — and the KPIs count the real rows.
The only thing with no home anywhere was the Ziel, which is this file.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONList


class ActivityTarget(Base, IDMixin, TenantMixin, TimestampMixin):
    """What one consultant is asked to do in one period.

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
    #: ELI-64: a goal SHARED by several consultants — "bei Jonas und mir gilt
    #: der Umsatz zusammen". Two or more Clerk ids; the goal is measured on
    #: the sum of their rows. Empty for an individual goal or the workspace
    #: default. `actor_user_id` stays NULL on a shared goal, so it never
    #: collides with anybody's own.
    members: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    #: What the shared goal is called on screen ("Jonas & Tobias").
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: ELI-64: the goal applies from this day on — "Xaver … startet ab
    #: 1. Januar". A period that ends before it has no goal (not a goal of 0).
    valid_from: Mapped[dt.date | None] = mapped_column(Date, nullable=True)


class TrackingPreference(Base, IDMixin, TenantMixin, TimestampMixin):
    """Which tracking tiles one person shows on their Cockpit (ELI-64).

    *"Welche im Cockpit auf der Startseite angezeigt werden, soll jeder
    selbst konfigurieren können."* Per person, server-side, so the choice
    follows them to another browser. No row = the default set.
    """

    __tablename__ = "tracking_preferences"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tracking_preference"),
    )

    #: Clerk `sub`; "" in the auth-disabled demo, which has no person.
    user_id: Mapped[str] = mapped_column(String(80), nullable=False)
    #: Tile keys in display order — KPI keys plus "process".
    tiles: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
