"""Proposals: an AI client asks, a human in Eligo decides (ADR 0003 §3.7).

Two doors, deliberately on different sides of the system:

* `create` is called by the action registry for a PROPOSE action — the only
  thing a propose tool can cause. It writes the proposal and its receipt,
  never the record.
* `confirm` / `decline` are called by the REST router with a browser session.
  The MCP endpoint has no tool that reaches them, and the REST API refuses an
  OAuth token (#189), so an AI client cannot confirm its own proposal.

Confirming runs the SAME domain function a recruiter's click runs
(`pipeline.set_step`, `managers.log_candidate_interaction`): a confirmed
proposal is a human edit, attributed to the human who confirmed it, with a
receipt naming who asked and through which client.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.enums import ReceiptAction
from app.domain.proposals.models import AgentProposal

#: Open proposals one person may have at once — a runaway loop in a client
#: fills a page, not a database.
MAX_PENDING_PER_USER = 20
#: After this a proposal is about a world that has moved on.
LIFETIME = dt.timedelta(days=7)

PENDING, CONFIRMED, DECLINED, STALE, EXPIRED = (
    "pending", "confirmed", "declined", "stale", "expired",
)


class TooManyPending(RuntimeError):
    """This person already has the maximum number of open proposals."""


class ProposalNotFound(LookupError):
    """No such proposal in this workspace."""


class ProposalClosed(RuntimeError):
    """Already confirmed, declined, stale or expired."""

    def __init__(self, status: str) -> None:
        super().__init__(f"proposal is {status}")
        self.status = status


class ProposalStale(RuntimeError):
    """The record changed since the proposal was made; it is not applied."""


@dataclass(frozen=True)
class ProposalDraft:
    """What a PROPOSE handler returns. The registry stores it; nothing else happens."""

    kind: str
    title: str
    args: dict[str, Any]
    snapshot: dict[str, Any]
    reason: str | None = None
    #: Record references for the receipt and the client: [("candidate", id), ...].
    refs: tuple[tuple[str, str], ...] = ()


# --- appliers: kind → (read the current state, apply) ------------------------

Snapshot = Callable[[AsyncSession, uuid.UUID, dict], Awaitable[dict | None]]
Apply = Callable[[AsyncSession, uuid.UUID, dict, str | None, str | None], Awaitable[None]]


def _iso(value: dt.datetime | None) -> str | None:
    # Normalised to UTC so the same instant always prints the same string,
    # whatever offset a driver hands back — the snapshot comparison is textual.
    return value.astimezone(dt.UTC).isoformat() if value else None


async def _step_snapshot(session: AsyncSession, tenant_id: uuid.UUID, args: dict) -> dict | None:
    """The step as it is now, or None when the process itself is gone."""
    from app.domain.pipeline import service as pipeline
    from app.domain.pipeline.models import ProcessStep

    app = await pipeline.get_application(
        session, tenant_id=tenant_id, application_id=uuid.UUID(args["application_id"])
    )
    if app is None:
        return None
    # The whole process, not only the step: a process rejected elsewhere since
    # the proposal was made must make it stale.
    process = {
        "stage": str(getattr(app.stage, "value", app.stage)),
        "status": str(getattr(app.status, "value", app.status)),
    }
    row = await session.scalar(
        select(ProcessStep).where(
            ProcessStep.tenant_id == tenant_id,
            ProcessStep.application_id == app.id,
            ProcessStep.step_key == args["step_key"],
        )
    )
    if row is None or not row.active:
        return {**process, "step": None}
    return {
        **process,
        "step": {
            "scheduled_at": _iso(pipeline.as_utc(row.scheduled_at)),
            "done_at": _iso(pipeline.as_utc(row.done_at)),
            "outcome": row.outcome,
        }
    }


async def _step_apply(
    session: AsyncSession, tenant_id: uuid.UUID, args: dict, user_id: str | None, name: str | None
) -> None:
    from app.domain.pipeline import service as pipeline

    parse = lambda v: dt.datetime.fromisoformat(v) if v else None  # noqa: E731
    await pipeline.set_step(
        session,
        tenant_id=tenant_id,
        application_id=uuid.UUID(args["application_id"]),
        step_key=args["step_key"],
        scheduled_at=parse(args.get("scheduled_at")),
        done_at=parse(args.get("done_at")),
        outcome=args.get("outcome"),
        actor=name or "recruiter",
        actor_user_id=user_id,
    )


async def _note_snapshot(session: AsyncSession, tenant_id: uuid.UUID, args: dict) -> dict | None:
    from app.domain.candidates.models import Candidate

    found = await session.scalar(
        select(Candidate.id).where(
            Candidate.tenant_id == tenant_id, Candidate.id == uuid.UUID(args["candidate_id"])
        )
    )
    return {} if found else None


async def _note_apply(
    session: AsyncSession, tenant_id: uuid.UUID, args: dict, user_id: str | None, name: str | None
) -> None:
    from app.domain.common.enums import InteractionType
    from app.domain.managers import service as managers
    from app.domain.managers.schemas import ManagerInteractionCreate

    row = await managers.log_candidate_interaction(
        session,
        tenant_id=tenant_id,
        candidate_id=uuid.UUID(args["candidate_id"]),
        payload=ManagerInteractionCreate(
            interaction_type=InteractionType(args.get("interaction_type") or "note"),
            summary=args["text"],
            job_id=uuid.UUID(args["job_id"]) if args.get("job_id") else None,
        ),
        actor_user_id=user_id,
        actor_name=name,
    )
    if row is None:
        raise ProposalStale("the candidate is no longer in this workspace")


APPLIERS: dict[str, tuple[Snapshot, Apply]] = {
    "step": (_step_snapshot, _step_apply),
    "candidate_note": (_note_snapshot, _note_apply),
}


async def snapshot(session: AsyncSession, *, tenant_id: uuid.UUID, kind: str, args: dict) -> dict | None:
    """The current state a proposal of `kind` is about; None if its record is gone."""
    read, _ = APPLIERS[kind]
    return await read(session, tenant_id, args)


# --- lifecycle ----------------------------------------------------------------


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def effective_status(row: AgentProposal, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    if row.status == PENDING and _aware(row.created_at) + LIFETIME < now:
        return EXPIRED
    return row.status


def expires_at(row: AgentProposal) -> dt.datetime:
    return _aware(row.created_at) + LIFETIME


async def create(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    draft: ProposalDraft,
    tool: str,
    asked_by_user_id: str | None,
    asked_by_name: str | None,
    client_id: str | None,
) -> AgentProposal:
    """Store one pending proposal and its receipt. Changes nothing else."""
    from app.domain.verification import service as verification

    await _purge_expired(session, tenant_id)
    cutoff = dt.datetime.now(dt.UTC) - LIFETIME
    open_count = await session.scalar(
        select(func.count())
        .select_from(AgentProposal)
        .where(
            AgentProposal.tenant_id == tenant_id,
            AgentProposal.asked_by_user_id == asked_by_user_id,
            AgentProposal.status == PENDING,
            AgentProposal.created_at > cutoff,
        )
    )
    if (open_count or 0) >= MAX_PENDING_PER_USER:
        raise TooManyPending(
            f"{MAX_PENDING_PER_USER} proposals are already waiting in Eligo — "
            "confirm or decline some first"
        )

    row = AgentProposal(
        tenant_id=tenant_id,
        kind=draft.kind,
        status=PENDING,
        tool=tool,
        title=draft.title[:300],
        args=draft.args,
        snapshot=draft.snapshot,
        reason=draft.reason,
        asked_by_user_id=asked_by_user_id,
        asked_by_name=asked_by_name,
        client_id=client_id,
    )
    session.add(row)
    await session.flush()
    # References only: the note text and the reason are free text about a
    # person, and a receipt cannot be erased (GDPR Art. 17).
    await verification.append_receipt(
        session,
        tenant_id=tenant_id,
        agent=f"ai-client:{client_id or 'unknown'}"[:100],
        action=ReceiptAction.ASSERT,
        subject_type="proposal",
        subject_id=str(row.id),
        verified=False,
        summary=f"{tool} proposed a {draft.kind} change — waiting for a human in Eligo",
        payload={
            "tool": tool,
            "kind": draft.kind,
            "client_id": client_id,
            "refs": [{"type": t, "id": i} for t, i in draft.refs],
        },
        actor_user_id=asked_by_user_id,
        actor_name=asked_by_name,
    )
    await session.commit()
    await session.refresh(row)
    return row


async def list_proposals(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    asked_by_user_id: str | None = None,
    pending_only: bool = False,
    limit: int = 100,
) -> list[AgentProposal]:
    query = select(AgentProposal).where(AgentProposal.tenant_id == tenant_id)
    if asked_by_user_id is not None:
        query = query.where(AgentProposal.asked_by_user_id == asked_by_user_id)
    if pending_only:
        cutoff = dt.datetime.now(dt.UTC) - LIFETIME
        query = query.where(AgentProposal.status == PENDING, AgentProposal.created_at > cutoff)
    query = query.order_by(AgentProposal.created_at.desc()).limit(limit)
    return list((await session.execute(query)).scalars())


async def _purge_expired(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Close what has expired and erase its free text (GDPR Art. 5(1)(e)).

    Runs on every proposal write in the workspace — no scheduler needed for a
    table this small. A workspace that never proposes again keeps its expired
    text until then; ARCHITECTURE.md lists that gap.
    """
    cutoff = dt.datetime.now(dt.UTC) - LIFETIME
    rows = (
        await session.execute(
            select(AgentProposal).where(
                AgentProposal.tenant_id == tenant_id,
                AgentProposal.status == PENDING,
                AgentProposal.created_at <= cutoff,
            )
        )
    ).scalars().all()
    for row in rows:
        row.status = EXPIRED
        row.args = _erased(row.args)
        row.reason = None


def _erased(args: dict) -> dict:
    return {**args, "text": None} if "text" in (args or {}) else dict(args or {})


async def _open(session: AsyncSession, tenant_id: uuid.UUID, proposal_id: uuid.UUID) -> AgentProposal:
    row = await session.scalar(
        select(AgentProposal).where(
            AgentProposal.tenant_id == tenant_id, AgentProposal.id == proposal_id
        )
    )
    if row is None:
        raise ProposalNotFound(str(proposal_id))
    status = effective_status(row)
    if status != PENDING:
        raise ProposalClosed(status)
    return row


async def _claim(
    session: AsyncSession, row: AgentProposal, status: str, user_id: str | None, name: str | None
) -> None:
    """Move a proposal out of "pending" — once. The WHERE on status is the lock.

    Two clicks that both read "pending" both reach here; the database lets
    exactly one UPDATE match. On Postgres the loser blocks on the winner's row
    lock and then matches nothing.
    """
    result = await session.execute(
        update(AgentProposal)
        .where(
            AgentProposal.id == row.id,
            AgentProposal.tenant_id == row.tenant_id,
            AgentProposal.status == PENDING,
        )
        .values(
            status=status,
            decided_by_user_id=user_id,
            decided_by_name=name,
            decided_at=dt.datetime.now(dt.UTC),
            # Free text is erased whatever the decision: a confirmed note now
            # lives in the record, a declined or stale one should not live on.
            args=_erased(row.args),
            reason=None,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise ProposalClosed("already decided")


async def _receipt(
    session: AsyncSession, row: AgentProposal, decision: str, user_id: str | None, name: str | None
) -> None:
    from app.domain.verification import service as verification

    await verification.append_receipt(
        session,
        tenant_id=row.tenant_id,
        agent=f"ai-client:{row.client_id or 'unknown'}"[:100],
        action=ReceiptAction.WRITE if decision == CONFIRMED else ReceiptAction.VERIFY,
        subject_type="proposal",
        subject_id=str(row.id),
        verified=decision == CONFIRMED,
        summary=f"{row.tool} {decision} by a human in Eligo",
        # References only — never the note text or the reason.
        payload={
            "decision": decision,
            "kind": row.kind,
            "tool": row.tool,
            "client_id": row.client_id,
            "asked_by_user_id": row.asked_by_user_id,
            "decided_by_user_id": user_id,
        },
        actor_user_id=user_id,
        actor_name=name,
    )


async def confirm(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    proposal_id: uuid.UUID,
    user_id: str | None,
    name: str | None,
) -> AgentProposal:
    """Apply a pending proposal as the human `name`, if the record is still as proposed."""
    await _purge_expired(session, tenant_id)
    row = await _open(session, tenant_id, proposal_id)
    args = dict(row.args)  # kept before the claim erases the text
    read, apply = APPLIERS[row.kind]
    current = await read(session, tenant_id, args)
    if current is None or current != row.snapshot:
        await _claim(session, row, STALE, user_id, name)
        await _receipt(session, row, STALE, user_id, name)
        await session.commit()
        raise ProposalStale("the record changed since this was proposed — nothing was applied")

    # Claim, receipt and the domain write commit together (the applier
    # commits): either all three land or none does.
    await _claim(session, row, CONFIRMED, user_id, name)
    await _receipt(session, row, CONFIRMED, user_id, name)
    await apply(session, tenant_id, args, user_id, name)  # commits
    await session.refresh(row)
    return row


async def decline(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    proposal_id: uuid.UUID,
    user_id: str | None,
    name: str | None,
) -> AgentProposal:
    """Close a proposal without applying it. Its free text is erased."""
    await _purge_expired(session, tenant_id)
    row = await _open(session, tenant_id, proposal_id)
    await _claim(session, row, DECLINED, user_id, name)
    await _receipt(session, row, DECLINED, user_id, name)
    await session.commit()
    await session.refresh(row)
    return row
