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

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin


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
