"""Pydantic v2 contracts for the reporting domain."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FunnelStage(BaseModel):
    """One step of the hiring funnel with the count of applications that have
    reached (i.e. got at least to) that step."""

    key: str
    label: str
    count: int


class DwellStage(BaseModel):
    """Average time applications currently sitting in a pipeline stage have
    spent there, as a proxy for stage velocity."""

    key: str
    label: str
    avg_days: float
    count: int


class ReportingSummary(BaseModel):
    """Headline KPIs for the cockpit."""

    total_candidates: int
    open_jobs: int
    total_applications: int
    placements: int
    avg_verification: float = Field(
        description="Mean candidate verification score (0-1)."
    )


class ReportingOverview(BaseModel):
    """One-shot payload backing the Reporting tab."""

    funnel: list[FunnelStage]
    dwell: list[DwellStage]
    summary: ReportingSummary