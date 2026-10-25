"""Wire contracts for activity tracking (ELI-15)."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class KpiRead(BaseModel):
    """One instrument: what was done, against what was asked."""

    key: str
    label: str
    source: str
    #: None when nothing measures this KPI — the UI shows the reason, not a 0.
    ist: int | None
    #: None when no target is set. Distinct from 0, which is a target of none.
    ziel: int | None
    available: bool
    unavailable_because: str = ""


class TrackingRead(BaseModel):
    period: str
    period_start: dt.datetime
    period_end: dt.datetime
    #: Whose numbers these are. None = the whole workspace.
    actor_user_id: str | None
    kpis: list[KpiRead]


class ConsultantRead(BaseModel):
    """Somebody with activity in the record, for the per-consultant switch."""

    actor_user_id: str | None
    name: str
    events: int


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    actor_user_id: str | None
    kpi: str
    period: str
    value: int


class TargetWrite(BaseModel):
    """Set (or clear) one target.

    `actor_user_id` absent means the workspace default that everyone without
    their own number inherits.
    """

    actor_user_id: str | None = None
    kpi: str
    period: str
    value: int = Field(ge=0, le=100_000)
