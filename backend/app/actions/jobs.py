"""Mandate reads."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.actions.core import ActionContext, ActionNotFound, Effect, action
from app.actions.schemas import JobDetail, JobList, JobSummary, Source
from app.domain.jobs import service as jobs


class ListArgs(BaseModel):
    status: str | None = Field(
        None,
        description="Only jobs with this status: 'active', 'inactive', or 'lead' (an ad taken from the "
        "market — business development, not a mandate; leads are listed only when asked for).",
    )
    limit: int = Field(50, ge=1, le=100)


class GetArgs(BaseModel):
    job_id: uuid.UUID


@action(
    "jobs.list",
    effect=Effect.READ,
    description="List the workspace's mandates (jobs), optionally one status only.",
    input=ListArgs,
)
async def list_jobs(ctx: ActionContext, args: ListArgs) -> JobList:
    # Leads (ELI-22) are ads taken from Markt, not mandates: listed only when
    # asked for by status, so Claude never presents one as a client's mandate.
    rows = await jobs.list_jobs(
        ctx.session, tenant_id=ctx.actor.tenant_id, limit=args.limit, status=args.status,
        exclude_status=None if args.status else "lead",
    )
    return JobList(
        jobs=[JobSummary.model_validate(j) for j in rows],
        sources=[Source(type="job", id=str(j.id)) for j in rows]
        or [Source(type="workspace", id=str(ctx.actor.tenant_id))],
    )


@action(
    "jobs.get",
    effect=Effect.READ,
    description="One mandate with its hard criteria (location, skills, certifications, work permit).",
    input=GetArgs,
)
async def get_job(ctx: ActionContext, args: GetArgs) -> JobDetail:
    row = await jobs.get_job(ctx.session, tenant_id=ctx.actor.tenant_id, job_id=args.job_id)
    if row is None:
        raise ActionNotFound(f"job {args.job_id}")
    return JobDetail(
        job=JobSummary.model_validate(row), sources=[Source(type="job", id=str(row.id))]
    )
