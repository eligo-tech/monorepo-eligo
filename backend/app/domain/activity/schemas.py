"""Wire contracts for activity tracking (ELI-15, ELI-64)."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class KpiRead(BaseModel):
    """One instrument: what was done, against what was asked."""

    key: str
    label: str
    source: str
    #: "business" · "bd" · "prozess" — the ticket's three headings.
    group: str = "bd"
    #: "count" or "eur".
    unit: str = "count"
    #: None when nothing measures this KPI — the UI shows the reason, not a 0.
    ist: int | None
    #: None when no target is set. Distinct from 0, which is a target of none.
    ziel: int | None
    #: Umsatz only: closed deals in the period with no Honorar entered.
    missing: int = 0
    available: bool
    unavailable_because: str = ""


class GoalRead(BaseModel):
    """A goal that belongs to people rather than to the workspace: one
    consultant's, or one shared by several ("Jonas & Tobias")."""

    id: uuid.UUID
    kpi: str
    label: str | None
    members: list[str]
    shared: bool
    #: None before `valid_from` — no goal yet, which is not a goal of 0.
    ziel: int | None
    valid_from: dt.date | None
    #: Counted over the members' rows together.
    ist: int


class FunnelStepRead(BaseModel):
    """One transition of the Prozess funnel, as n of m and median days."""

    from_key: str
    to_key: str
    from_label: str
    to_label: str
    #: Processes whose from-step is dated in the period.
    of: int
    #: Of those, how many reached the next step.
    reached: int
    #: None when `of` is 0 — no rate, not 0 %.
    ratio: float | None
    #: None when no pair of dates could be measured.
    median_days: float | None
    source: str


class TrackingRead(BaseModel):
    period: str
    period_start: dt.datetime
    period_end: dt.datetime
    #: Whose numbers these are. None = the whole workspace.
    actor_user_id: str | None
    kpis: list[KpiRead]
    goals: list[GoalRead] = []
    funnel: list[FunnelStepRead] = []


class ConsultantRead(BaseModel):
    """Somebody with activity in the record, for the per-consultant switch."""

    actor_user_id: str | None
    name: str
    events: int


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_user_id: str | None
    kpi: str
    period: str
    value: int
    members: list[str] = []
    label: str | None = None
    valid_from: dt.date | None = None


class TargetWrite(BaseModel):
    """Set (or update) one goal.

    `actor_user_id` absent and no `members` means the workspace default that
    everyone without their own number inherits. `members` (two or more) is a
    goal shared by a group. `valid_from` lets a goal start later.
    """

    actor_user_id: str | None = None
    kpi: str
    period: str
    #: Euros for Umsatz, so the ceiling is a revenue figure, not a call count.
    value: int = Field(ge=0, le=100_000_000)
    members: list[str] = Field(default_factory=list, max_length=20)
    label: str | None = Field(default=None, max_length=80)
    valid_from: dt.date | None = None


class TilesRead(BaseModel):
    """Which tracking tiles this person shows on the Cockpit."""

    tiles: list[str]
    #: False while they have never chosen — the default set is shown.
    saved: bool


class TilesWrite(BaseModel):
    tiles: list[str] = Field(max_length=20)
