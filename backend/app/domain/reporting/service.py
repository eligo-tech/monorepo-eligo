"""Reporting business logic — funnel, stage dwell, and KPI aggregation.

Everything here is derived from the live record (applications, candidates,
jobs); no analytics are stored, so figures can never drift from the source.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus, PipelineStage
from app.domain.jobs.models import Job
from app.domain.pipeline.models import Application
from app.domain.reporting.schemas import (
    DwellStage,
    FunnelStage,
    ReportingOverview,
    ReportingSummary,
)

# Linear funnel (rejected is an outcome, not a funnel step). Order defines rank.
FUNNEL_ORDER: list[ApplicationStatus] = [
    ApplicationStatus.SOURCED,
    ApplicationStatus.SCREENED,
    ApplicationStatus.PRESENTED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.PLACED,
]
FUNNEL_LABELS: dict[ApplicationStatus, str] = {
    ApplicationStatus.SOURCED: "Beworben",
    ApplicationStatus.SCREENED: "Gescreent",
    ApplicationStatus.PRESENTED: "Vorgestellt",
    ApplicationStatus.INTERVIEW: "Interview",
    ApplicationStatus.PLACED: "Vermittelt",
}
_RANK: dict[str, int] = {s.value: i for i, s in enumerate(FUNNEL_ORDER)}

# Board stages we report dwell for, in board order.
DWELL_STAGES: list[PipelineStage] = [
    PipelineStage.BEWERBUNG,
    PipelineStage.LONG_LIST,
    PipelineStage.SHORT_LIST,
    PipelineStage.PRESENTED,
    PipelineStage.INTERVIEW,
]
STAGE_LABELS: dict[PipelineStage, str] = {
    PipelineStage.BEWERBUNG: "Bewerbung",
    PipelineStage.LONG_LIST: "Long List",
    PipelineStage.SHORT_LIST: "Short List",
    PipelineStage.PRESENTED: "Presented",
    PipelineStage.INTERVIEW: "Interview",
}


def _as_str(value: object) -> str:
    """Enum column values come back as plain strings when re-read from the DB."""
    inner = getattr(value, "value", None)
    return inner if isinstance(inner, str) else str(value)


def _furthest_rank(app: Application) -> int:
    """Highest funnel step an application reached.

    Non-rejected: its current status. Rejected: the furthest step recorded in
    its transition history (fallback: it at least entered the funnel at rank 0).
    """
    status = _as_str(app.status)
    if status != ApplicationStatus.REJECTED.value:
        return _RANK.get(status, 0)
    best = 0
    for entry in app.history or []:
        to = entry.get("to") if isinstance(entry, dict) else None
        if to in _RANK:
            best = max(best, _RANK[to])
    return best


async def _applications(session: AsyncSession, tenant_id: uuid.UUID) -> list[Application]:
    result = await session.execute(
        select(Application).where(Application.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


async def funnel(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[FunnelStage]:
    """Applications that reached each funnel step (cumulative, top-of-funnel first)."""
    apps = await _applications(session, tenant_id)
    ranks = [_furthest_rank(a) for a in apps]
    stages: list[FunnelStage] = []
    for i, status in enumerate(FUNNEL_ORDER):
        stages.append(
            FunnelStage(
                key=status.value,
                label=FUNNEL_LABELS[status],
                count=sum(1 for r in ranks if r >= i),
            )
        )
    return stages


async def dwell(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[DwellStage]:
    """Average days applications currently in each stage have sat there
    (time since their last transition, approximated by ``updated_at``)."""
    apps = await _applications(session, tenant_id)
    now = dt.datetime.now(dt.timezone.utc)
    out: list[DwellStage] = []
    for stage in DWELL_STAGES:
        in_stage = [a for a in apps if _as_str(a.stage) == stage.value]
        if in_stage:
            days = [
                max((now - _aware(a.updated_at)).total_seconds() / 86400.0, 0.0)
                for a in in_stage
            ]
            avg = round(sum(days) / len(days), 1)
        else:
            avg = 0.0
        out.append(
            DwellStage(
                key=stage.value,
                label=STAGE_LABELS[stage],
                avg_days=avg,
                count=len(in_stage),
            )
        )
    return out


def _aware(value: dt.datetime) -> dt.datetime:
    """Normalise naive DB timestamps (SQLite) to UTC-aware."""
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


async def summary(session: AsyncSession, *, tenant_id: uuid.UUID) -> ReportingSummary:
    total_candidates = await _scalar(
        session, select(func.count()).select_from(Candidate).where(Candidate.tenant_id == tenant_id)
    )
    open_jobs = await _scalar(
        session,
        select(func.count()).select_from(Job).where(
            Job.tenant_id == tenant_id, Job.status == "open"
        ),
    )
    total_applications = await _scalar(
        session, select(func.count()).select_from(Application).where(Application.tenant_id == tenant_id)
    )
    placements = await _scalar(
        session,
        select(func.count()).select_from(Application).where(
            Application.tenant_id == tenant_id,
            Application.status == ApplicationStatus.PLACED.value,
        ),
    )
    avg_verification = await _scalar(
        session,
        select(func.coalesce(func.avg(Candidate.verification_score), 0.0)).where(
            Candidate.tenant_id == tenant_id
        ),
        as_float=True,
    )
    return ReportingSummary(
        total_candidates=int(total_candidates),
        open_jobs=int(open_jobs),
        total_applications=int(total_applications),
        placements=int(placements),
        avg_verification=round(float(avg_verification), 3),
    )


async def _scalar(session: AsyncSession, stmt, *, as_float: bool = False):
    result = await session.execute(stmt)
    value = result.scalar_one()
    return float(value or 0.0) if as_float else (value or 0)


async def overview(session: AsyncSession, *, tenant_id: uuid.UUID) -> ReportingOverview:
    return ReportingOverview(
        funnel=await funnel(session, tenant_id=tenant_id),
        dwell=await dwell(session, tenant_id=tenant_id),
        summary=await summary(session, tenant_id=tenant_id),
    )