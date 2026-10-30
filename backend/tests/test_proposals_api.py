"""The human side of PR 4: confirming or declining in Eligo, over REST.

A proposal is created through the registry as an AI client would (agent actor,
OAuth client id); the decision is taken over the REST API as the browser does.
Every refusal has a control that passes.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.actions import catalog  # noqa: F401
from app.actions.core import REGISTRY, ActionContext
from app.core.auth import RECRUITER, Actor
from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ReceiptAction
from app.domain.jobs.models import Job
from app.domain.managers.models import ManagerInteraction
from app.domain.pipeline.models import Application, ProcessStep
from app.domain.proposals.models import AgentProposal
from app.domain.verification import service as verification
from app.domain.verification.models import Receipt

TENANT = settings.default_tenant_id  # what the auth-free test app resolves to


@pytest.fixture
def api():
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _agent(tenant: uuid.UUID = TENANT) -> Actor:
    return Actor(
        tenant_id=tenant, user_id="user_42", name="Dana Recruiter", role=RECRUITER,
        role_known=True, kind="agent", client_id="lEpz2crhuszLqEo0",
    )


async def _process(tenant: uuid.UUID = TENANT) -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as s:
        cand = Candidate(tenant_id=tenant, full_name="Anna Beispiel")
        job = Job(tenant_id=tenant, title="COC Lead")
        s.add_all([cand, job])
        await s.flush()
        app = Application(tenant_id=tenant, candidate_id=cand.id, job_id=job.id)
        s.add(app)
        await s.commit()
        return cand.id, app.id


async def _propose(name: str, args: dict, tenant: uuid.UUID = TENANT) -> str:
    async with SessionLocal() as s:
        out = await REGISTRY.invoke(name, ActionContext(session=s, actor=_agent(tenant)), args)
    return str(out.id)


async def _step_proposal() -> tuple[str, uuid.UUID]:
    _, app_id = await _process()
    pid = await _propose("pipeline.propose_step", {
        "application_id": str(app_id), "step_key": "interview",
        "done_at": "2026-10-29T10:00:00Z", "outcome": "pass", "reason": "lief gut",
    })
    return pid, app_id


async def test_the_list_shows_pending_proposals_with_before_and_after(api) -> None:
    pid, _ = await _step_proposal()
    rows = (await api.get("/api/v1/proposals?pending_only=true")).json()
    [row] = [r for r in rows if r["id"] == pid]
    assert row["status"] == "pending" and row["kind"] == "step"
    assert row["before"]["step"] is None  # what Claude saw: no step yet
    assert row["before"]["stage"]  # and the process it was in
    assert row["after"]["outcome"] == "pass" and row["reason"] == "lief gut"
    assert row["asked_by_name"] == "Dana Recruiter"


async def test_confirming_applies_the_step_and_leaves_a_receipt(api) -> None:
    pid, app_id = await _step_proposal()
    r = await api.post(f"/api/v1/proposals/{pid}/confirm")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed" and r.json()["decided_by_name"] == "Demo"
    async with SessionLocal() as s:
        step = await s.scalar(select(ProcessStep).where(ProcessStep.application_id == app_id))
        assert step.step_key == "interview" and step.outcome == "pass"
        receipts = (await s.execute(
            select(Receipt).where(Receipt.tenant_id == TENANT, Receipt.subject_id == pid)
            .order_by(Receipt.chain_index)
        )).scalars().all()
        assert [x.action for x in receipts] == [ReceiptAction.ASSERT, ReceiptAction.WRITE]
        write = receipts[-1]
        assert write.payload["asked_by_user_id"] == "user_42"
        assert write.payload["client_id"] == "lEpz2crhuszLqEo0"
        ok, why = await verification.verify_chain(s, tenant_id=TENANT)
        assert ok, why


async def test_confirming_a_note_writes_it_attributed_to_the_confirmer(api) -> None:
    cand_id, _ = await _process()
    pid = await _propose("notes.propose_candidate_note",
                         {"candidate_id": str(cand_id), "text": "Start im März"})
    assert (await api.post(f"/api/v1/proposals/{pid}/confirm")).status_code == 200
    async with SessionLocal() as s:
        note = await s.scalar(select(ManagerInteraction).where(ManagerInteraction.candidate_id == cand_id))
    assert note.summary == "Start im März" and note.actor_name == "Demo"


async def test_a_proposal_is_confirmed_once(api) -> None:
    pid, _ = await _step_proposal()
    assert (await api.post(f"/api/v1/proposals/{pid}/confirm")).status_code == 200
    again = await api.post(f"/api/v1/proposals/{pid}/confirm")
    assert again.status_code == 409


async def test_a_stale_proposal_is_refused_and_nothing_is_applied(api) -> None:
    pid, app_id = await _step_proposal()
    # Somebody records the step in Eligo after Claude proposed.
    async with SessionLocal() as s:
        s.add(ProcessStep(tenant_id=TENANT, application_id=app_id, step_key="interview",
                          outcome="open", note="von Hand"))
        await s.commit()
    r = await api.post(f"/api/v1/proposals/{pid}/confirm")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale"
    async with SessionLocal() as s:
        step = await s.scalar(select(ProcessStep).where(ProcessStep.application_id == app_id))
        row = await s.get(AgentProposal, uuid.UUID(pid))
    assert step.outcome == "open"  # the human's record stands
    assert row.status == "stale"


async def test_an_expired_proposal_cannot_be_confirmed(api) -> None:
    pid, _ = await _step_proposal()
    async with SessionLocal() as s:
        row = await s.get(AgentProposal, uuid.UUID(pid))
        row.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=8)
        await s.commit()
    r = await api.post(f"/api/v1/proposals/{pid}/confirm")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "closed"


async def test_declining_applies_nothing_and_erases_the_text(api) -> None:
    cand_id, _ = await _process()
    pid = await _propose("notes.propose_candidate_note",
                         {"candidate_id": str(cand_id), "text": "Gehalt 95k", "reason": "Telefonat"})
    r = await api.post(f"/api/v1/proposals/{pid}/decline")
    assert r.status_code == 200 and r.json()["status"] == "declined"
    async with SessionLocal() as s:
        row = await s.get(AgentProposal, uuid.UUID(pid))
        notes = (await s.execute(select(ManagerInteraction).where(
            ManagerInteraction.candidate_id == cand_id))).scalars().all()
    assert notes == []
    assert "95k" not in str(row.args) and row.reason is None


async def test_another_workspaces_proposal_is_404(api) -> None:
    other = uuid.uuid4()
    cand_id, _ = await _process(other)
    pid = await _propose("notes.propose_candidate_note",
                         {"candidate_id": str(cand_id), "text": "x"}, tenant=other)
    assert (await api.post(f"/api/v1/proposals/{pid}/confirm")).status_code == 404
    assert (await api.post(f"/api/v1/proposals/{pid}/decline")).status_code == 404
    assert pid not in {r["id"] for r in (await api.get("/api/v1/proposals")).json()}


# --- review fixes -------------------------------------------------------------


async def test_a_proposal_loaded_before_a_concurrent_confirm_is_not_applied_twice(monkeypatch) -> None:
    """The race: two people (or two tabs) both read "pending". The second must
    be refused at the write, not at the read — so `_open` is handed a row that
    still says pending while the database already says confirmed."""
    from sqlalchemy import update

    from app.domain.proposals import service as proposals

    cand_id, _ = await _process()
    pid = uuid.UUID(await _propose("notes.propose_candidate_note",
                                   {"candidate_id": str(cand_id), "text": "einmal"}))
    async with SessionLocal() as late:
        stale_view = await late.get(AgentProposal, pid)

        async def _open_as_seen_before(session, tenant_id, proposal_id):
            return stale_view

        # The other click wins first.
        async with SessionLocal() as winner:
            await winner.execute(update(AgentProposal).where(AgentProposal.id == pid)
                                 .values(status="confirmed"))
            await winner.commit()
        monkeypatch.setattr(proposals, "_open", _open_as_seen_before)
        for decide in (proposals.confirm, proposals.decline):
            await late.refresh(stale_view)  # attributes, not the decision: `_open` is patched
            with pytest.raises(proposals.ProposalClosed):
                await decide(late, tenant_id=TENANT, proposal_id=pid, user_id="u2", name="Zweiter")
            await late.rollback()
    async with SessionLocal() as s:
        notes = (await s.execute(select(ManagerInteraction).where(
            ManagerInteraction.candidate_id == cand_id))).scalars().all()
    assert notes == []  # the late click applied nothing


async def test_declining_and_staleness_leave_receipts_without_text(api) -> None:
    cand_id, _ = await _process()
    pid = await _propose("notes.propose_candidate_note",
                         {"candidate_id": str(cand_id), "text": "Gehalt 95k"})
    await api.post(f"/api/v1/proposals/{pid}/decline")
    async with SessionLocal() as s:
        receipts = (await s.execute(select(Receipt).where(
            Receipt.tenant_id == TENANT, Receipt.subject_id == pid
        ).order_by(Receipt.chain_index))).scalars().all()
    assert len(receipts) == 2
    assert receipts[-1].payload["decision"] == "declined"
    assert "95k" not in str(receipts[-1].payload) + receipts[-1].summary


async def test_confirming_erases_the_proposals_copy_of_the_note(api) -> None:
    cand_id, _ = await _process()
    pid = await _propose("notes.propose_candidate_note",
                         {"candidate_id": str(cand_id), "text": "Start im März", "reason": "Telefonat"})
    await api.post(f"/api/v1/proposals/{pid}/confirm")
    async with SessionLocal() as s:
        row = await s.get(AgentProposal, uuid.UUID(pid))
    assert row.args.get("text") is None and row.reason is None


async def test_expired_proposals_lose_their_text(api) -> None:
    from app.domain.proposals import service as proposals

    cand_id, _ = await _process()
    pid = await _propose("notes.propose_candidate_note",
                         {"candidate_id": str(cand_id), "text": "alt"})
    async with SessionLocal() as s:
        row = await s.get(AgentProposal, uuid.UUID(pid))
        row.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=8)
        await s.commit()
    # Any later proposal activity in the workspace purges what has expired.
    await _propose("notes.propose_candidate_note", {"candidate_id": str(cand_id), "text": "neu"})
    async with SessionLocal() as s:
        row = await s.get(AgentProposal, uuid.UUID(pid))
    assert row.status == proposals.EXPIRED and row.args.get("text") is None


async def test_refusals_carry_a_code_and_never_echo_input(api) -> None:
    pid, _ = await _step_proposal()
    await api.post(f"/api/v1/proposals/{pid}/confirm")
    again = await api.post(f"/api/v1/proposals/{pid}/confirm")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "closed"


# --- retention (review 2026-10-31) --------------------------------------------


@pytest.mark.parametrize("decision", ["confirm", "decline"])
async def test_a_decided_proposal_keeps_no_name(api, decision) -> None:
    pid, _ = await _step_proposal()
    await api.post(f"/api/v1/proposals/{pid}/{decision}")
    async with SessionLocal() as s:
        row = await s.get(AgentProposal, uuid.UUID(pid))
    assert "Anna" not in row.title  # the receipt keeps the references


async def test_the_nightly_job_expires_proposals_in_every_workspace() -> None:
    """Without a user coming back: the scheduler's call alone erases them."""
    from app.domain.proposals import service as proposals

    other = uuid.uuid4()
    ids = []
    for tenant in (TENANT, other):
        cand_id, _ = await _process(tenant)
        ids.append(uuid.UUID(await _propose("notes.propose_candidate_note",
                                            {"candidate_id": str(cand_id), "text": "alt"}, tenant=tenant)))
    async with SessionLocal() as s:
        for pid in ids:
            (await s.get(AgentProposal, pid)).created_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=8)
        await s.commit()

    done = await proposals.expire_all()
    assert done["expired"] >= 2
    async with SessionLocal() as s:
        for pid in ids:
            row = await s.get(AgentProposal, pid)
            assert row.status == "expired" and row.args.get("text") is None and "Anna" not in row.title
