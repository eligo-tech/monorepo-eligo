"""Proposals API — where a human confirms or declines what an AI client proposed.

Browser sessions only: the REST API refuses OAuth access tokens (#189), so the
client that proposed cannot confirm. Any member of the workspace may decide
(decided 2026-10-30); the receipt names who asked and who confirmed.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor
from app.core.database import get_db
from app.domain.proposals import service
from app.domain.proposals.models import AgentProposal
from app.domain.proposals.schemas import ProposalRead

router = APIRouter(prefix="/proposals", tags=["proposals"])


def _read(row: AgentProposal) -> ProposalRead:
    return ProposalRead(
        id=row.id,
        kind=row.kind,
        status=service.effective_status(row),
        title=row.title,
        tool=row.tool,
        before=row.snapshot or {},
        after=row.args or {},
        reason=row.reason,
        asked_by_name=row.asked_by_name,
        client_id=row.client_id,
        created_at=row.created_at,
        expires_at=service.expires_at(row),
        decided_by_name=row.decided_by_name,
        decided_at=row.decided_at,
    )


@router.get("", response_model=list[ProposalRead])
async def list_proposals(
    pending_only: bool = False,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[ProposalRead]:
    rows = await service.list_proposals(db, tenant_id=actor.tenant_id, pending_only=pending_only)
    return [_read(r) for r in rows]


def _refuse(code: int, reason: str, message: str) -> HTTPException:
    """A refusal the UI can branch on. Never echoes an exception's text: a
    validation error carries the input, and the input is a note about a person."""
    return HTTPException(code, {"code": reason, "message": message})


async def _decide(action, proposal_id: uuid.UUID, actor: Actor, db: AsyncSession) -> ProposalRead:  # noqa: ANN001
    try:
        row = await action(
            db, tenant_id=actor.tenant_id, proposal_id=proposal_id,
            user_id=actor.user_id, name=actor.name,
        )
    except service.ProposalNotFound as exc:
        raise _refuse(status.HTTP_404_NOT_FOUND, "not_found", "proposal not found") from exc
    except service.ProposalClosed as exc:
        raise _refuse(status.HTTP_409_CONFLICT, "closed", "already decided or expired") from exc
    except service.ProposalStale as exc:
        raise _refuse(status.HTTP_409_CONFLICT, "stale", "the record changed since this was proposed") from exc
    except ValueError as exc:
        # The domain refused the write (e.g. the process is gone): nothing applied.
        await db.rollback()
        raise _refuse(status.HTTP_409_CONFLICT, "unapplicable", "could not be applied") from exc
    return _read(row)


@router.post("/{proposal_id}/confirm", response_model=ProposalRead)
async def confirm(
    proposal_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ProposalRead:
    return await _decide(service.confirm, proposal_id, actor, db)


@router.post("/{proposal_id}/decline", response_model=ProposalRead)
async def decline(
    proposal_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ProposalRead:
    return await _decide(service.decline, proposal_id, actor, db)
