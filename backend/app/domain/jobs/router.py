"""Jobs API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, get_current_tenant
from app.core.database import get_db
from app.domain.common.enums import InteractionType
from app.domain.managers import service as managers_service
from app.domain.pipeline import service as pipeline_service
from app.domain.managers.schemas import (
    ManagerInteractionCreate,
    ManagerInteractionRead,
)
from app.domain.jobs import service
from app.domain.jobs import jobspec
from app.domain.jobs.schemas import (
    CriteriaSuggestion,
    JobCopy,
    JobCreate,
    JobRead,
    JobSpecProposal,
    JobSpecRequest,
    JobUpdate,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobRead])
async def list_jobs(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(
        default=None,
        description="active | inactive. Legacy spellings are understood.",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[JobRead]:
    rows = await service.list_jobs(
        db, tenant_id=tenant_id, limit=limit, status=status
    )
    return [JobRead.model_validate(r) for r in rows]


@router.get("/{job_id}", response_model=JobRead)
async def get_job(
    job_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    row = await service.get_job(db, tenant_id=tenant_id, job_id=job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobRead.model_validate(row)


@router.get(
    "/{job_id}/criteria-suggestions", response_model=list[CriteriaSuggestion]
)
async def criteria_suggestions(
    job_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[CriteriaSuggestion]:
    """Muss-Kriterien this mandate's title already names.

    63 of 76 mandates in the live workspace have none, which makes the
    deterministic half of matching a no-op for most of the book. These are
    proposals drawn from the title and the workspace's own skill vocabulary —
    deterministic, explainable, and committed only by a human click.
    """
    job = await service.get_job(db, tenant_id=tenant_id, job_id=job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return [
        CriteriaSuggestion(
            skill=s.skill, evidence=s.evidence, candidates=s.candidates
        )
        for s in await service.criteria_suggestions(db, tenant_id=tenant_id, job=job)
    ]


@router.get(
    "/{job_id}/briefings", response_model=list[ManagerInteractionRead]
)
async def list_briefings(
    job_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerInteractionRead]:
    """What was said about this mandate, newest first.

    Phase 2 of the Prozess-Doku is a conversation, and until now the product
    had nowhere to put it: the Suchprofil fields held the OUTCOME of the
    briefing and nothing held the briefing.
    """
    rows = await managers_service.list_for_job(
        db,
        tenant_id=tenant_id,
        job_id=job_id,
        # Feedback about one candidate is a different question and has its
        # own list; mixing it in here would put "wirkte nervös" among the
        # Muss-Kriterien.
        exclude=[InteractionType.FEEDBACK],
    )
    return [ManagerInteractionRead.model_validate(r) for r in rows]


@router.post(
    "/{job_id}/briefings",
    response_model=ManagerInteractionRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_briefing(
    job_id: uuid.UUID,
    payload: ManagerInteractionCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerInteractionRead:
    """Write down a briefing call. The contact is optional — see 0034."""
    job = await service.get_job(db, tenant_id=tenant_id, job_id=job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    payload = payload.model_copy(update={"job_id": job_id})
    row = await managers_service.log_interaction(
        db, tenant_id=tenant_id, manager_id=payload.manager_id, payload=payload
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerInteractionRead.model_validate(row)


@router.get("/{job_id}/feedback", response_model=list[ManagerInteractionRead])
async def list_feedback(
    job_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerInteractionRead]:
    """What was said about the CANDIDATES on this mandate, newest first."""
    rows = await managers_service.list_for_job(
        db, tenant_id=tenant_id, job_id=job_id, kinds=[InteractionType.FEEDBACK]
    )
    return [ManagerInteractionRead.model_validate(r) for r in rows]


@router.post(
    "/{job_id}/feedback",
    response_model=ManagerInteractionRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_feedback(
    job_id: uuid.UUID,
    payload: ManagerInteractionCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerInteractionRead:
    """Record a remark about one candidate on this mandate.

    A row per remark. It used to be written into the process step's `note`,
    which is one field: the second piece of feedback on a step silently
    replaced the first, and the recruiter only found out by looking.

    The candidate is required and must actually be running on this mandate —
    feedback is always ABOUT somebody, and a remark filed against a person
    who was never put forward is a remark nobody will find again.
    """
    job = await service.get_job(db, tenant_id=tenant_id, job_id=job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if payload.candidate_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "candidate_id is required"
        )
    running = await pipeline_service.get_application_for(
        db, tenant_id=tenant_id, job_id=job_id, candidate_id=payload.candidate_id
    )
    if running is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "candidate is not on this mandate"
        )
    payload = payload.model_copy(
        update={"job_id": job_id, "interaction_type": InteractionType.FEEDBACK}
    )
    row = await managers_service.log_interaction(
        db, tenant_id=tenant_id, manager_id=payload.manager_id, payload=payload
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerInteractionRead.model_validate(row)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    payload.tenant_id = tenant_id  # force the authenticated tenant
    try:
        row = await service.create_job(db, data=payload)
    except service.ContactNotAtClient as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return JobRead.model_validate(row)


@router.patch("/{job_id}", response_model=JobRead)
async def update_job(
    job_id: uuid.UUID,
    payload: JobUpdate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    """Edit the Suchprofil. Each changed field leaves a receipt, naming who.

    The editor used to be a query parameter — identity the browser could set.
    It comes from the verified token now.
    """
    try:
        row = await service.update_job(
            db,
            tenant_id=actor.tenant_id,
            job_id=job_id,
            patch=payload,
            editor=actor.name,
        )
    except service.ReopeningRefused as exc:
        # 409, not 422: the payload is perfectly valid and would be accepted
        # on any other mandate. What refuses it is the state this one is in.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (service.InvalidBand, service.ContactNotAtClient) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobRead.model_validate(row)


@router.post(
    "/{job_id}/copy", response_model=JobRead, status_code=status.HTTP_201_CREATED
)
async def copy_job(
    job_id: uuid.UUID,
    payload: JobCopy | None = None,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    """Reuse an old mandate: "alte Jobs als Kopie wiederverwenden" (ELI-7).

    The Suchprofil comes across; the pipeline, the briefings and the feedback
    do not. The copy is ACTIVE and knows which mandate it came from.
    """
    row = await service.copy_job(
        db,
        tenant_id=tenant_id,
        job_id=job_id,
        title=payload.title if payload else None,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobRead.model_validate(row)


@router.post("/parse-spec", response_model=JobSpecProposal)
async def parse_spec(
    payload: JobSpecRequest,
    actor: Actor = Depends(get_current_actor),
) -> JobSpecProposal:
    """Read a job advert and PROPOSE a Suchprofil. Creates nothing (ELI-6).

    Why this is not ingestion, and why that distinction is enforced in
    `jobspec/fetch.py` rather than asserted here: it reads one document the
    recruiter is already holding, for their own mandate. It writes nothing,
    touches no `hub_*` table, follows no links and runs on no schedule. The
    comparison is uploading the advert as a PDF, which this product has
    always allowed — not crawling a board, which RULE 1 forbids and this
    cannot become.

    Why it returns a proposal instead of a `Job`: `must_have_skills` feed
    `apply_hard_filters`, which EXCLUDES candidates. A model may suggest
    them; a human decides (RULE 5, GDPR Art. 22). The form the recruiter was
    going to fill in arrives filled in, and they press save.
    """
    text = (payload.text or "").strip()
    document_title = ""
    source_url = (payload.url or "").strip() or None

    if not text and source_url:
        try:
            raw = await jobspec.fetch_posting(source_url)
        except jobspec.NotFetchable as exc:
            # 422, not 502: the URL is the payload, and the recruiter is the
            # one who can fix it — usually by pasting the text instead.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
            ) from exc
        text, document_title = jobspec.html_to_text(raw)
    elif text.lstrip().startswith("<"):
        # Pasted straight out of "view source".
        text, document_title = jobspec.html_to_text(text)

    if len(text) < 80:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Aus dieser Seite ließ sich kein Anzeigentext lesen — bitte den "
            "Text der Anzeige einfügen.",
        )

    extractor = jobspec.get_job_spec_extractor()
    spec = extractor.extract(text, document_title)
    return JobSpecProposal(**spec.as_dict(), source_url=source_url)

