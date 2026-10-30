"""Propose actions: an AI client asks for a change; a human confirms it in Eligo.

Each handler READS — to check the record is in this workspace and to snapshot
what the client saw — and returns a `ProposalDraft`. The registry stores it.
`REGISTRY.check()` refuses a propose handler that names any write, so "the
handler only proposes" is checked at startup, not trusted.

Never a tool: rejecting a candidate (outcome "out"), deleting, sending. Those
stay with a human in Eligo (GDPR Art. 22, EU AI Act).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.actions.core import ActionContext, ActionNotFound, Effect, action
from app.actions.schemas import ProposalList, ProposalOut
from app.domain.candidates.models import Candidate
from app.domain.jobs.models import Job
from app.domain.pipeline import service as pipeline
from app.domain.pipeline import steps as steps_mod
from app.domain.proposals import service as proposals

StepKey = Literal[steps_mod.PROCESS_STEP_KEYS]  # type: ignore[valid-type]


class ProposeStep(BaseModel):
    application_id: uuid.UUID = Field(description="The process (application) id from pipeline_processes.")
    step_key: StepKey = Field(description="Which of the nine process steps.")
    #: Aware only: "10:00" from a German recruiter means Berlin, and a bare
    #: time stored as UTC would show an hour off. Refused, not guessed.
    scheduled_at: AwareDatetime | None = Field(
        None, description="New appointment, ISO 8601 WITH offset, e.g. 2026-11-03T10:00:00+01:00."
    )
    done_at: AwareDatetime | None = Field(
        None, description="When it happened, ISO 8601 WITH offset, e.g. 2026-10-29T15:00:00+01:00."
    )
    #: Only "pass". "out" would reject a candidate and "open" could undo a
    #: rejection — both stay with a person in Eligo (GDPR Art. 22).
    outcome: Literal["pass"] | None = Field(None, description="'pass' = it went well. Rejecting is not available.")
    reason: str | None = Field(None, max_length=1000, description="Why — shown to the person who confirms.")

    @model_validator(mode="after")
    def _changes_something(self) -> ProposeStep:
        if self.scheduled_at is None and self.done_at is None and self.outcome is None:
            raise ValueError("propose at least one of scheduled_at, done_at, outcome")
        return self


class ProposeCandidateNote(BaseModel):
    candidate_id: uuid.UUID = Field(description="The candidate id.")
    text: str = Field(min_length=1, max_length=5000, description="The note, as it should appear in Eligo.")
    job_id: uuid.UUID | None = Field(None, description="The mandate it is about, if any.")
    interaction_type: Literal["note", "candidate_call", "message"] = Field(
        "note", description="note · candidate_call · message"
    )
    reason: str | None = Field(None, max_length=1000, description="Why — shown to the person who confirms.")


class ListArgs(BaseModel):
    pending_only: bool = Field(False, description="Only proposals still waiting.")


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=dt.UTC)).isoformat()


@action(
    "pipeline.propose_step",
    effect=Effect.PROPOSE,
    description="Propose a change to one process step: schedule it, mark it done, or mark it passed. "
    "The stage follows the steps. Nothing changes until a person confirms it in Eligo.",
    input=ProposeStep,
)
async def propose_step(ctx: ActionContext, args: ProposeStep) -> proposals.ProposalDraft:
    tenant = ctx.actor.tenant_id
    app = await pipeline.get_application(ctx.session, tenant_id=tenant, application_id=args.application_id)
    if app is None:
        raise ActionNotFound(f"process {args.application_id}")
    cand = await ctx.session.get(Candidate, app.candidate_id)
    job = await ctx.session.get(Job, app.job_id)
    payload = {
        "application_id": str(app.id),
        "step_key": args.step_key,
        "scheduled_at": _iso(args.scheduled_at),
        "done_at": _iso(args.done_at),
        "outcome": args.outcome,
    }
    seen = await proposals.snapshot(ctx.session, tenant_id=tenant, kind="step", args=payload)
    label = steps_mod.STEP_BY_KEY[args.step_key].label
    return proposals.ProposalDraft(
        kind="step",
        title=f"{cand.full_name if cand else '?'} · {job.title if job else '?'} — {label}",
        args=payload,
        snapshot=seen or {"step": None},
        reason=args.reason,
        refs=(("process", str(app.id)), ("candidate", str(app.candidate_id))),
    )


@action(
    "notes.propose_candidate_note",
    effect=Effect.PROPOSE,
    description="Propose a note on a candidate. Nothing is written until a person confirms it in Eligo.",
    input=ProposeCandidateNote,
)
async def propose_candidate_note(ctx: ActionContext, args: ProposeCandidateNote) -> proposals.ProposalDraft:
    tenant = ctx.actor.tenant_id
    cand = await ctx.session.get(Candidate, args.candidate_id)
    if cand is None or cand.tenant_id != tenant:
        raise ActionNotFound(f"candidate {args.candidate_id}")
    if args.job_id is not None:
        job = await ctx.session.get(Job, args.job_id)
        if job is None or job.tenant_id != tenant:
            raise ActionNotFound(f"job {args.job_id}")
    payload = {
        "candidate_id": str(cand.id),
        "text": args.text,
        "job_id": str(args.job_id) if args.job_id else None,
        "interaction_type": args.interaction_type,
    }
    return proposals.ProposalDraft(
        kind="candidate_note",
        title=f"{cand.full_name} — Notiz",
        args=payload,
        snapshot={},
        reason=args.reason,
        refs=(("candidate", str(cand.id)),),
    )


@action(
    "proposals.list",
    effect=Effect.READ,
    description="The changes you proposed and whether a person confirmed, declined them, or they expired.",
    input=ListArgs,
)
async def list_mine(ctx: ActionContext, args: ListArgs) -> ProposalList:
    if not ctx.actor.user_id:
        # Without a user, "mine" would silently become "everyone's".
        return ProposalList(proposals=[], sources=[_none()])
    rows = await proposals.list_proposals(
        ctx.session,
        tenant_id=ctx.actor.tenant_id,
        asked_by_user_id=ctx.actor.user_id,
        pending_only=args.pending_only,
        limit=50,
    )
    items = [ProposalOut.from_row(r) for r in rows]
    sources = [s for p in items for s in p.sources] or [_none()]
    return ProposalList(proposals=items, sources=sources)


def _none():
    from app.actions.schemas import Source

    return Source(type="report", id="proposals")
