"""Wiedervorlagen business logic (ELI-44). No FastAPI imports; tenant_id is
always explicit, and every person or note a follow-up points at must be this
workspace's own."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.candidates.models import Candidate
from app.domain.companies.models import Company
from app.domain.followups.dates import DateSuggestion, suggest_dates
from app.domain.followups.models import DONE, OPEN, FollowUp
from app.domain.followups.schemas import FollowUpCreate, FollowUpUpdate
from app.domain.managers.models import Manager, ManagerInteraction

#: Rows read at most per list — the to-do list of one workspace.
LIST_LIMIT = 500


class NotFound(LookupError):
    """No such follow-up, person or note in this workspace."""


def suggest(text: str, reference: dt.date) -> list[DateSuggestion]:
    """The dates a note names (`dates.suggest_dates`). Reads only."""
    return suggest_dates(text, reference)


def _query(tenant_id: uuid.UUID):
    return (
        select(FollowUp, Manager.full_name, Manager.stage, Manager.company_id, Company.name, Candidate.full_name)
        .outerjoin(Manager, (Manager.id == FollowUp.manager_id) & (Manager.tenant_id == tenant_id))
        .outerjoin(Company, (Company.id == Manager.company_id) & (Company.tenant_id == tenant_id))
        .outerjoin(Candidate, (Candidate.id == FollowUp.candidate_id) & (Candidate.tenant_id == tenant_id))
        .where(FollowUp.tenant_id == tenant_id)
    )


def _read(row) -> dict:  # noqa: ANN001 — a result row of `_query`
    follow_up, manager_name, stage, company_id, company_name, candidate_name = row
    if follow_up.manager_id is not None:
        kind = "lead" if stage == "bus_dev" else "manager"
        name = manager_name or ""
    else:
        kind, name, company_id, company_name = "candidate", candidate_name or "", None, None
    done_at = follow_up.done_at
    if done_at is not None and done_at.tzinfo is None:
        done_at = done_at.replace(tzinfo=dt.UTC)  # SQLite hands back naive
    created_at = follow_up.created_at
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=dt.UTC)
    return {
        "id": follow_up.id,
        "manager_id": follow_up.manager_id,
        "candidate_id": follow_up.candidate_id,
        "source_interaction_id": follow_up.source_interaction_id,
        "due_date": follow_up.due_date,
        "due_time": follow_up.due_time,
        "text": follow_up.text,
        "status": follow_up.status,
        "origin": follow_up.origin,
        "created_at": created_at,
        "created_by_name": follow_up.created_by_name,
        "done_at": done_at,
        "done_by_name": follow_up.done_by_name,
        "subject_kind": kind,
        "person_name": name,
        "company_id": company_id,
        "company_name": company_name,
    }


async def _one(session: AsyncSession, tenant_id: uuid.UUID, follow_up_id: uuid.UUID) -> dict:
    row = (await session.execute(_query(tenant_id).where(FollowUp.id == follow_up_id))).first()
    if row is None:
        raise NotFound("follow-up")
    return _read(row)


async def list_follow_ups(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    status: Literal["open", "done", "all"] = "open",
    manager_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    limit: int = LIST_LIMIT,
) -> list[dict]:
    """Open ones soonest first (overdue on top); done ones newest first."""
    stmt = _query(tenant_id)
    if status != "all":
        stmt = stmt.where(FollowUp.status == status)
    if manager_id is not None:
        stmt = stmt.where(FollowUp.manager_id == manager_id)
    if candidate_id is not None:
        stmt = stmt.where(FollowUp.candidate_id == candidate_id)
    if status == "done":
        stmt = stmt.order_by(FollowUp.done_at.desc().nulls_last(), FollowUp.id)
    else:
        stmt = stmt.order_by(
            FollowUp.due_date, FollowUp.due_time.asc().nulls_first(), FollowUp.created_at, FollowUp.id
        )
    return [_read(r) for r in (await session.execute(stmt.limit(limit))).all()]


async def create(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    payload: FollowUpCreate,
    actor_user_id: str | None,
    actor_name: str | None,
) -> dict:
    """Raises `NotFound` when the person or the note is not this workspace's."""
    if payload.manager_id is not None:
        owner = await session.scalar(
            select(Manager.id).where(Manager.id == payload.manager_id, Manager.tenant_id == tenant_id)
        )
    else:
        owner = await session.scalar(
            select(Candidate.id).where(Candidate.id == payload.candidate_id, Candidate.tenant_id == tenant_id)
        )
    if owner is None:
        raise NotFound("person")
    if payload.source_interaction_id is not None:
        note = await session.scalar(
            select(ManagerInteraction.id).where(
                ManagerInteraction.id == payload.source_interaction_id,
                ManagerInteraction.tenant_id == tenant_id,
            )
        )
        if note is None:
            raise NotFound("note")
    row = FollowUp(
        tenant_id=tenant_id,
        manager_id=payload.manager_id,
        candidate_id=payload.candidate_id,
        source_interaction_id=payload.source_interaction_id,
        due_date=payload.due_date,
        due_time=payload.due_time,
        text=payload.text,
        origin=payload.origin,
        status=OPEN,
        created_by_user_id=actor_user_id,
        created_by_name=actor_name,
    )
    session.add(row)
    await session.commit()
    return await _one(session, tenant_id, row.id)


async def update(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    follow_up_id: uuid.UUID,
    payload: FollowUpUpdate,
    actor_user_id: str | None,
    actor_name: str | None,
) -> dict:
    row = await session.scalar(
        select(FollowUp).where(FollowUp.id == follow_up_id, FollowUp.tenant_id == tenant_id)
    )
    if row is None:
        raise NotFound("follow-up")
    sent = payload.model_fields_set
    if payload.due_date is not None:
        row.due_date = payload.due_date
    if "due_time" in sent:
        row.due_time = payload.due_time
    if payload.text is not None:
        row.text = payload.text
    if payload.status == DONE and row.status != DONE:
        row.status = DONE
        row.done_at = dt.datetime.now(dt.UTC)
        row.done_by_user_id = actor_user_id
        row.done_by_name = actor_name
    elif payload.status == OPEN and row.status != OPEN:
        row.status = OPEN
        row.done_at = None
        row.done_by_user_id = None
        row.done_by_name = None
    await session.commit()
    return await _one(session, tenant_id, follow_up_id)


async def delete(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    follow_up_id: uuid.UUID,
) -> None:
    """Removes it for everyone; the router lets only an admin call this
    (ELI-27). Anyone in the workspace may move it or mark it done."""
    row = await session.scalar(
        select(FollowUp).where(FollowUp.id == follow_up_id, FollowUp.tenant_id == tenant_id)
    )
    if row is None:
        raise NotFound("follow-up")
    await session.delete(row)
    await session.commit()
