"""Pipeline business logic — application creation, the status state machine,
Kanban stage moves, and the board view.

Status transitions are validated against ``ApplicationStatus.transitions()``:
illegal jumps (e.g. sourced -> placed) are rejected.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.common.enums import ApplicationStatus, PipelineStage
from app.domain.pipeline.models import Application
from app.domain.pipeline.schemas import ApplicationCreate

# Display labels for the board columns (German labels are product-facing).
STAGE_LABELS: dict[PipelineStage, str] = {
    PipelineStage.BEWERBUNG: "Bewerbung",
    PipelineStage.LONG_LIST: "Long List",
    PipelineStage.SHORT_LIST: "Short List",
    PipelineStage.PRESENTED: "Presented",
    PipelineStage.INTERVIEW: "Interview",
    PipelineStage.PLACED: "Placed",
    PipelineStage.REJECTED: "Rejected",
}


class InvalidTransition(ValueError):
    """Raised when a status transition violates the state machine."""


async def list_applications(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[Application]:
    result = await session.execute(
        select(Application)
        .where(Application.tenant_id == tenant_id)
        .order_by(Application.created_at)
    )
    return list(result.scalars().all())


async def get_application(
    session: AsyncSession, *, tenant_id: uuid.UUID, application_id: uuid.UUID
) -> Application | None:
    result = await session.execute(
        select(Application).where(
            Application.tenant_id == tenant_id,
            Application.id == application_id,
        )
    )
    return result.scalar_one_or_none()


async def create_application(
    session: AsyncSession, *, data: ApplicationCreate
) -> Application:
    app = Application(
        tenant_id=data.tenant_id or settings.default_tenant_id,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        status=data.status,
        stage=data.stage,
        notes=data.notes,
        history=[
            {
                "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "event": "created",
                "status": data.status.value,
                "stage": data.stage.value,
            }
        ],
    )
    session.add(app)
    await session.commit()
    await session.refresh(app)
    return app


def _append_history(app: Application, entry: dict) -> None:
    # Reassign (not mutate in place) so SQLAlchemy detects the JSON change.
    app.history = [*app.history, entry]


async def transition_status(
    session: AsyncSession,
    *,
    app: Application,
    to_status: ApplicationStatus,
    actor: str,
) -> Application:
    """Move the application to ``to_status`` if the transition is allowed."""
    allowed = ApplicationStatus.transitions()[app.status]
    if to_status not in allowed:
        raise InvalidTransition(
            f"cannot move from {app.status.value} to {to_status.value}"
        )
    _append_history(
        app,
        {
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "event": "status",
            "from": app.status.value,
            "to": to_status.value,
            "actor": actor,
        },
    )
    app.status = to_status
    await session.commit()
    await session.refresh(app)
    return app


async def move_stage(
    session: AsyncSession,
    *,
    app: Application,
    to_stage: PipelineStage,
    actor: str,
) -> Application:
    """Move the application to a new Kanban stage."""
    _append_history(
        app,
        {
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "event": "stage",
            "from": app.stage.value,
            "to": to_stage.value,
            "actor": actor,
        },
    )
    app.stage = to_stage
    await session.commit()
    await session.refresh(app)
    return app


async def board(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> dict[PipelineStage, list[Application]]:
    """Group applications by Kanban stage for the board view."""
    apps = await list_applications(session, tenant_id=tenant_id)
    grouped: dict[PipelineStage, list[Application]] = {
        stage: [] for stage in PipelineStage
    }
    for app in apps:
        grouped[app.stage].append(app)
    return grouped