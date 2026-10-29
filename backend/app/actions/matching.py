"""Matching reads. Hard criteria stay deterministic (backend/CLAUDE.md §2.2)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.actions.core import ActionContext, ActionNotFound, Effect, action
from app.actions.schemas import MatchList, MatchOut, MatchReasonOut, Source
from app.domain.candidates import service as candidates
from app.domain.jobs import service as jobs
from app.domain.matching import service as matching


class ForJobArgs(BaseModel):
    job_id: uuid.UUID
    limit: int = Field(20, ge=1, le=50)


@action(
    "matching.for_job",
    effect=Effect.READ,
    description="Candidates that pass the mandate's hard criteria, ranked, each with evidence-backed reasons. "
    "A recommendation for a human, never a decision.",
    input=ForJobArgs,
)
async def for_job(ctx: ActionContext, args: ForJobArgs) -> MatchList:
    tenant_id = ctx.actor.tenant_id
    job = await jobs.get_job(ctx.session, tenant_id=tenant_id, job_id=args.job_id)
    if job is None:
        raise ActionNotFound(f"job {args.job_id}")
    criteria = matching.active_criteria(job)
    # Only those that PASSED the hard filters — never include_rejected.
    results = (
        await matching.match_job(ctx.session, job_id=job.id, tenant_id=tenant_id, record=False)
    )[: args.limit]
    out: list[MatchOut] = []
    for r in results:
        person = await candidates.get_candidate(
            ctx.session, tenant_id=tenant_id, candidate_id=r.candidate_id
        )
        if person is None:
            continue
        out.append(
            MatchOut(
                candidate_id=r.candidate_id,
                candidate_name=person.full_name,
                score=r.score,
                strength=str(r.strength.value if hasattr(r.strength, "value") else r.strength),
                reasons=[
                    MatchReasonOut(
                        title=m.title,
                        strength=str(
                            m.strength.value if hasattr(m.strength, "value") else m.strength
                        ),
                        evidence=m.evidence,
                    )
                    for m in r.reasons
                ],
            )
        )
    return MatchList(
        job_id=job.id,
        hard_criteria=criteria,
        matches=out,
        sources=[Source(type="job", id=str(job.id))]
        + [Source(type="candidate", id=str(m.candidate_id)) for m in out],
    )
