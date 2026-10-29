"""Reporting reads — aggregate numbers, no person in them."""

from __future__ import annotations

from pydantic import BaseModel

from app.actions.core import ActionContext, Effect, action
from app.actions.schemas import Report, Source
from app.domain.reporting import service as reporting


class NoArgs(BaseModel):
    pass


@action(
    "reporting.overview",
    effect=Effect.READ,
    description="Workspace KPIs: funnel, time per stage and summary numbers.",
    input=NoArgs,
)
async def overview(ctx: ActionContext, args: NoArgs) -> Report:
    data = await reporting.overview(ctx.session, tenant_id=ctx.actor.tenant_id)
    return Report(
        report=data.model_dump(mode="json"),
        sources=[Source(type="report", id=f"overview:{ctx.actor.tenant_id}")],
    )


@action(
    "reporting.funnel",
    effect=Effect.READ,
    description="How many processes reached each step of the hiring funnel.",
    input=NoArgs,
)
async def funnel(ctx: ActionContext, args: NoArgs) -> Report:
    stages = await reporting.funnel(ctx.session, tenant_id=ctx.actor.tenant_id)
    return Report(
        report={"funnel": [s.model_dump(mode="json") for s in stages]},
        sources=[Source(type="report", id=f"funnel:{ctx.actor.tenant_id}")],
    )
