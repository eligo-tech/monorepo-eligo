"""PR 4 — an AI client may PROPOSE a change; only a human in Eligo confirms it.

The rule, in three parts, each shown failing on purpose first:

1. A PROPOSE handler returns a draft. It cannot write: the catalog refuses at
   load any propose handler that names a write (session.add/commit, a domain
   write service, a receipt).
2. Calling a propose tool creates one pending proposal and one receipt — and
   the step / the note is exactly as it was.
3. Confirming happens over REST with a browser session (see
   test_proposals_api.py); no tool can do it.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from app.actions import catalog  # noqa: F401 — registers the actions
from app.actions import core
from app.actions.core import REGISTRY, ActionContext, ActionInputInvalid, Effect
from app.core.auth import RECRUITER, Actor
from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ReceiptAction
from app.domain.jobs.models import Job
from app.domain.managers.models import ManagerInteraction
from app.domain.pipeline.models import Application, ProcessStep
from app.domain.proposals.models import AgentProposal
from app.domain.verification.models import Receipt


class _Args(BaseModel):
    pass


def _agent(tenant_id: uuid.UUID, user: str = "user_42") -> Actor:
    return Actor(
        tenant_id=tenant_id,
        user_id=user,
        name="Dana Recruiter",
        role=RECRUITER,
        role_known=True,
        kind="agent",
        client_id="lEpz2crhuszLqEo0",
    )


async def _world() -> tuple[uuid.UUID, Candidate, Job, Application]:
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        cand = Candidate(tenant_id=tenant, full_name="Anna Beispiel")
        job = Job(tenant_id=tenant, title="COC Lead")
        s.add_all([cand, job])
        await s.flush()
        app = Application(tenant_id=tenant, candidate_id=cand.id, job_id=job.id)
        s.add(app)
        await s.commit()
        for row in (cand, job, app):
            await s.refresh(row)
        return tenant, cand, job, app


async def _count(model, tenant: uuid.UUID) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count()).select_from(model).where(model.tenant_id == tenant)
        )


async def _call(name: str, actor: Actor, args: dict):
    async with SessionLocal() as s:
        return await REGISTRY.invoke(name, ActionContext(session=s, actor=actor), args)


# --- 1. the catalog rule -----------------------------------------------------


def test_propose_is_an_agent_effect_and_commit_never_is() -> None:
    assert Effect.PROPOSE in core.AGENT_EFFECTS
    assert not core.AGENT_EFFECTS & {Effect.COMMIT, Effect.EXTERNAL}


async def _writes_a_step(ctx, args):
    from app.domain.pipeline import service as pipeline

    return await pipeline.set_step(ctx.session, tenant_id=ctx.actor.tenant_id,
                                   application_id=uuid.uuid4(), step_key="interview")


async def _adds_a_row(ctx, args):
    ctx.session.add(object())


async def _commits(ctx, args):
    await ctx.session.commit()


async def _logs_a_note(ctx, args):
    from app.domain.managers import service as managers

    return await managers.log_candidate_interaction(ctx.session)


async def _hides_it_in_a_closure(ctx, args):
    async def inner():
        await ctx.session.flush()

    await inner()


@pytest.mark.parametrize(
    "handler", [_writes_a_step, _adds_a_row, _commits, _logs_a_note, _hides_it_in_a_closure]
)
def test_a_propose_handler_that_writes_is_refused_at_load(handler) -> None:
    reg = core.Registry()
    reg.action("bad.propose", effect=Effect.PROPOSE, description="x", input=_Args)(handler)
    with pytest.raises(core.CatalogViolation):
        reg.check()


def test_control_the_same_code_as_a_human_commit_action_loads() -> None:
    # The rule is about PROPOSE, not about writing in general: a COMMIT action
    # (never agent-visible) may write.
    reg = core.Registry()
    reg.action("ok.commit", effect=Effect.COMMIT, description="x", input=_Args)(_commits)
    reg.check()


def test_the_real_catalog_has_the_propose_tools() -> None:
    proposes = {s.name for s in REGISTRY.all() if s.effect is Effect.PROPOSE}
    assert proposes == {"pipeline.propose_step", "notes.propose_candidate_note"}
    assert "proposals.list" in {s.name for s in REGISTRY.agent_exposed()}
    # Nothing an agent sees can confirm, decline or reject.
    for spec in REGISTRY.agent_exposed():
        assert not any(w in spec.name for w in ("confirm", "decline", "reject", "delete"))


# --- 2. proposing changes nothing -------------------------------------------


async def test_proposing_a_step_creates_a_pending_proposal_and_writes_no_step() -> None:
    tenant, _, _, app = await _world()
    out = await _call(
        "pipeline.propose_step",
        _agent(tenant),
        {
            "application_id": str(app.id),
            "step_key": "interview",
            "done_at": "2026-10-29T10:00:00Z",
            "reason": "Interview fand gestern statt.",
        },
    )
    assert out.status == "pending"
    assert out.sources[0].type == "proposal"
    assert await _count(ProcessStep, tenant) == 0  # nothing applied
    async with SessionLocal() as s:
        [row] = (await s.execute(select(AgentProposal).where(AgentProposal.tenant_id == tenant))).scalars()
    assert row.kind == "step" and row.status == "pending"
    assert row.asked_by_user_id == "user_42" and row.client_id == "lEpz2crhuszLqEo0"
    assert row.snapshot["step"] is None  # what Claude saw: no step yet
    assert "Anna Beispiel" in row.title and "COC Lead" in row.title


async def test_proposing_a_note_writes_no_note() -> None:
    tenant, cand, _, _ = await _world()
    out = await _call(
        "notes.propose_candidate_note",
        _agent(tenant),
        {"candidate_id": str(cand.id), "text": "Möchte ab März starten."},
    )
    assert out.status == "pending"
    assert await _count(ManagerInteraction, tenant) == 0


async def test_a_proposal_leaves_one_receipt_without_the_free_text() -> None:
    tenant, cand, _, _ = await _world()
    await _call(
        "notes.propose_candidate_note",
        _agent(tenant),
        {"candidate_id": str(cand.id), "text": "Gehalt 95k, Scheidung läuft",
         "reason": "aus dem Telefonat"},
    )
    async with SessionLocal() as s:
        [r] = (await s.execute(select(Receipt).where(Receipt.tenant_id == tenant))).scalars()
    assert r.action == ReceiptAction.ASSERT and r.subject_type == "proposal"
    assert r.payload["client_id"] == "lEpz2crhuszLqEo0"
    text = str(r.payload) + r.summary
    assert "Scheidung" not in text and "95k" not in text and "Telefonat" not in text


async def test_rejecting_a_candidate_cannot_be_proposed() -> None:
    tenant, _, _, app = await _world()
    with pytest.raises(ActionInputInvalid):
        await _call(
            "pipeline.propose_step",
            _agent(tenant),
            {"application_id": str(app.id), "step_key": "interview", "outcome": "out"},
        )


async def test_a_step_proposal_must_change_something() -> None:
    tenant, _, _, app = await _world()
    with pytest.raises(ActionInputInvalid):
        await _call(
            "pipeline.propose_step",
            _agent(tenant),
            {"application_id": str(app.id), "step_key": "interview"},
        )


async def test_another_workspaces_record_cannot_be_proposed_on() -> None:
    _, cand, _, app = await _world()
    other = uuid.uuid4()
    with pytest.raises(core.ActionNotFound):
        await _call("notes.propose_candidate_note", _agent(other),
                    {"candidate_id": str(cand.id), "text": "x"})
    with pytest.raises(core.ActionNotFound):
        await _call("pipeline.propose_step", _agent(other),
                    {"application_id": str(app.id), "step_key": "interview",
                     "outcome": "pass"})


async def test_open_proposals_per_person_are_capped(monkeypatch) -> None:
    from app.domain.proposals import service as proposals

    monkeypatch.setattr(proposals, "MAX_PENDING_PER_USER", 2)
    tenant, cand, _, _ = await _world()
    for _ in range(2):
        await _call("notes.propose_candidate_note", _agent(tenant),
                    {"candidate_id": str(cand.id), "text": "x"})
    with pytest.raises(proposals.TooManyPending):
        await _call("notes.propose_candidate_note", _agent(tenant),
                    {"candidate_id": str(cand.id), "text": "x"})
    # Control: somebody else in the workspace is not blocked by it.
    await _call("notes.propose_candidate_note", _agent(tenant, user="user_7"),
                {"candidate_id": str(cand.id), "text": "x"})


async def test_proposals_list_shows_my_proposals_and_their_status() -> None:
    tenant, cand, _, _ = await _world()
    await _call("notes.propose_candidate_note", _agent(tenant),
                {"candidate_id": str(cand.id), "text": "x"})
    await _call("notes.propose_candidate_note", _agent(tenant, user="user_7"),
                {"candidate_id": str(cand.id), "text": "y"})
    out = await _call("proposals.list", _agent(tenant), {})
    assert [p.status for p in out.proposals] == ["pending"]  # only mine


async def test_an_old_proposal_counts_as_expired() -> None:
    tenant, cand, _, _ = await _world()
    await _call("notes.propose_candidate_note", _agent(tenant),
                {"candidate_id": str(cand.id), "text": "x"})
    async with SessionLocal() as s:
        row = await s.scalar(select(AgentProposal).where(AgentProposal.tenant_id == tenant))
        row.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=8)
        await s.commit()
    out = await _call("proposals.list", _agent(tenant), {})
    assert [p.status for p in out.proposals] == ["expired"]


# --- review fixes -------------------------------------------------------------


def _draft(candidate_id):
    from app.domain.proposals.service import ProposalDraft

    return ProposalDraft(kind="candidate_note", title="t",
                         args={"candidate_id": str(candidate_id), "text": "x"}, snapshot={})


async def test_a_propose_handler_that_edits_a_loaded_record_is_refused_at_runtime() -> None:
    # The static guard cannot see `cand.full_name = ...`; the registry's own
    # commit would save it. The runtime guard refuses and nothing lands.
    tenant, cand, _, _ = await _world()
    reg = core.Registry()

    @reg.action("bad.edit", effect=Effect.PROPOSE, description="x", input=_Args)
    async def _edits(ctx, args):
        row = await ctx.session.get(Candidate, cand.id)
        row.full_name = "Überschrieben"
        return _draft(cand.id)

    with pytest.raises(core.CatalogViolation):
        async with SessionLocal() as s:
            await reg.invoke("bad.edit", ActionContext(session=s, actor=_agent(tenant)), {})
    async with SessionLocal() as s:
        assert (await s.get(Candidate, cand.id)).full_name == "Anna Beispiel"


async def test_a_propose_handler_running_raw_sql_writes_is_refused() -> None:
    from sqlalchemy import text

    tenant, cand, _, _ = await _world()
    reg = core.Registry()

    @reg.action("bad.sql", effect=Effect.PROPOSE, description="x", input=_Args)
    async def _sql(ctx, args):
        await ctx.session.execute(
            text("UPDATE candidates SET full_name = 'X' WHERE id = :i"), {"i": cand.id.hex}
        )
        return _draft(cand.id)

    with pytest.raises(core.CatalogViolation):
        async with SessionLocal() as s:
            await reg.invoke("bad.sql", ActionContext(session=s, actor=_agent(tenant)), {})
    async with SessionLocal() as s:
        assert (await s.get(Candidate, cand.id)).full_name == "Anna Beispiel"


async def test_a_time_without_an_offset_is_refused() -> None:
    # "10:00" from Claude means Berlin; stored as UTC it would show 11:00.
    tenant, _, _, app = await _world()
    with pytest.raises(ActionInputInvalid):
        await _call("pipeline.propose_step", _agent(tenant),
                    {"application_id": str(app.id), "step_key": "interview",
                     "scheduled_at": "2026-11-03T10:00:00"})


async def test_reopening_a_step_cannot_be_proposed() -> None:
    # "open" on a step marked "out" would undo a rejection; only "pass" is offered.
    tenant, _, _, app = await _world()
    with pytest.raises(ActionInputInvalid):
        await _call("pipeline.propose_step", _agent(tenant),
                    {"application_id": str(app.id), "step_key": "interview", "outcome": "open"})


async def test_the_snapshot_includes_the_process_stage() -> None:
    tenant, _, _, app = await _world()
    await _call("pipeline.propose_step", _agent(tenant),
                {"application_id": str(app.id), "step_key": "interview", "outcome": "pass"})
    async with SessionLocal() as s:
        row = await s.scalar(select(AgentProposal).where(AgentProposal.tenant_id == tenant))
    assert "stage" in row.snapshot and "status" in row.snapshot


async def test_my_proposals_without_a_user_is_empty_not_everything() -> None:
    tenant, cand, _, _ = await _world()
    await _call("notes.propose_candidate_note", _agent(tenant),
                {"candidate_id": str(cand.id), "text": "x"})
    anonymous = _agent(tenant, user=None)  # type: ignore[arg-type]
    out = await _call("proposals.list", anonymous, {})
    assert out.proposals == []
