"""Candidate reads."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.actions.core import ActionContext, ActionNotFound, Effect, action
from app.actions.schemas import (
    CandidateDetail,
    CandidateList,
    CandidateSummary,
    ProvenanceEntry,
    Source,
)
from app.domain.candidates import service as candidates
from app.domain.verification import service as verification


class ListArgs(BaseModel):
    skill: str | None = Field(
        None, description="Only candidates with this skill (case-insensitive)."
    )
    city: str | None = Field(None, description="Only candidates in this city.")
    available_within_weeks: int | None = Field(
        None, ge=0, description="Only candidates available within this many weeks."
    )
    limit: int = Field(25, ge=1, le=100)


class GetArgs(BaseModel):
    candidate_id: uuid.UUID


@action(
    "candidates.list",
    effect=Effect.READ,
    description="List candidates in the workspace, optionally filtered by skill, city and availability. "
    "No contact data is returned.",
    input=ListArgs,
)
async def list_candidates(ctx: ActionContext, args: ListArgs) -> CandidateList:
    rows, total = await candidates.filter_candidates(
        ctx.session,
        tenant_id=ctx.actor.tenant_id,
        skill=args.skill,
        city=args.city,
        available_within_weeks=args.available_within_weeks,
        limit=args.limit,
    )
    return CandidateList(
        candidates=[CandidateSummary.model_validate(c) for c in rows],
        total=total,
        truncated=total > len(rows),
        sources=[Source(type="candidate", id=str(c.id)) for c in rows]
        or [Source(type="workspace", id=str(ctx.actor.tenant_id))],
    )


@action(
    "candidates.get",
    effect=Effect.READ,
    description="One candidate's profile, with the change history (who changed which field, from which source).",
    input=GetArgs,
)
async def get_candidate(ctx: ActionContext, args: GetArgs) -> CandidateDetail:
    tenant_id = ctx.actor.tenant_id
    row = await candidates.get_candidate(
        ctx.session, tenant_id=tenant_id, candidate_id=args.candidate_id
    )
    if row is None:
        raise ActionNotFound(f"candidate {args.candidate_id}")
    history = await verification.history_for(
        ctx.session, tenant_id=tenant_id, entity_type="candidate", entity_id=row.id
    )
    return CandidateDetail(
        candidate=CandidateSummary.model_validate(row),
        profile_summary=row.profile_summary,
        focus_areas=list(row.focus_areas or []),
        industries=list(row.industries or []),
        total_years_experience=row.total_years_experience,
        provenance=[ProvenanceEntry.model_validate(h) for h in history],
        sources=[Source(type="candidate", id=str(row.id))],
    )
