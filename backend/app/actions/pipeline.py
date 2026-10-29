"""Pipeline reads: the running processes, grouped by mandate."""

from __future__ import annotations

from pydantic import BaseModel

from app.actions.core import ActionContext, Effect, action
from app.actions.schemas import ProcessCandidate, ProcessList, ProcessOut, Source, StepOut
from app.domain.pipeline import service as pipeline


class NoArgs(BaseModel):
    pass


@action(
    "pipeline.processes",
    effect=Effect.READ,
    description="The running processes grouped by mandate: each candidate's stage, steps, next appointment "
    "and assessment verdict.",
    input=NoArgs,
)
async def processes(ctx: ActionContext, args: NoArgs) -> ProcessList:
    groups = await pipeline.processes(ctx.session, tenant_id=ctx.actor.tenant_id)
    out: list[ProcessOut] = []
    sources: list[Source] = []
    for g in groups:
        people = []
        for c in g["candidates"]:
            assessment = c.get("assessment") or {}
            people.append(
                ProcessCandidate(
                    application_id=c["application_id"],
                    candidate_id=c["candidate_id"],
                    candidate_name=c["candidate_name"],
                    stage=str(getattr(c["stage"], "value", c["stage"])),
                    presented_at=c["presented_at"],
                    next_appointment=c["next_appointment"],
                    # Step notes are free text a recruiter wrote — left out on purpose.
                    steps=[
                        StepOut(
                            step_key=s["step_key"],
                            label=s["label"],
                            scheduled_at=s["scheduled_at"],
                            done_at=s["done_at"],
                            outcome=s["outcome"],
                        )
                        for s in c["steps"]
                    ],
                    fit_score=assessment.get("fit_score"),
                    verdict=assessment.get("verdict"),
                )
            )
            sources.append(Source(type="process", id=str(c["application_id"])))
        out.append(
            ProcessOut(
                job_id=g["job_id"],
                job_title=g["job_title"],
                company_name=g["company_name"],
                status=g["status"],
                candidates=people,
            )
        )
    return ProcessList(
        processes=out, sources=sources or [Source(type="workspace", id=str(ctx.actor.tenant_id))]
    )
