"""Managers business logic. No FastAPI imports; tenant_id is always explicit."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Collection

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.candidates.models import Candidate
from app.domain.common.enums import (
    CONTACT_INTERACTION_KINDS,
    InteractionType,
    LIVE_JOB_STATUSES,
    normalise_interaction_type,
)
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.managers.schemas import (
    ManagerCreate,
    ManagerInteractionCreate,
    ManagerUpdate,
)


class CompanyNotInTenant(Exception):
    """The company does not belong to this tenant (or does not exist).

    Raised rather than returning None so the caller cannot mistake a rejected
    write for an empty result: a manager attached to another tenant's company
    would be a cross-tenant leak, not a 404.
    """


async def _own_company(
    session: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> Company:
    company = await session.scalar(
        select(Company).where(
            Company.id == company_id, Company.tenant_id == tenant_id
        )
    )
    if company is None:
        raise CompanyNotInTenant(str(company_id))
    return company


async def count_managers(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
) -> int:
    """How many contacts exist, independent of any page or search term."""
    stmt = select(func.count()).select_from(Manager).where(Manager.tenant_id == tenant_id)
    if company_id is not None:
        stmt = stmt.where(Manager.company_id == company_id)
    return int(await session.scalar(stmt) or 0)


async def list_managers(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 100,
) -> list[Manager]:
    """This workspace's contacts, optionally narrowed.

    `q` searches the person AND their employer, because a recruiter looking for
    a contact remembers one or the other — "the CTO at Bergfreunde" is as common
    a way in as the name. Searching only the name would send them scrolling
    through an alphabetical list of 650.
    """
    stmt = select(Manager).where(Manager.tenant_id == tenant_id)
    if company_id is not None:
        stmt = stmt.where(Manager.company_id == company_id)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.join(Company, Company.id == Manager.company_id).where(
            or_(
                func.lower(Manager.full_name).like(needle),
                func.lower(Manager.role_title).like(needle),
                func.lower(Company.name).like(needle),
            )
        )
    result = await session.execute(
        stmt.order_by(Manager.full_name).limit(limit)
    )
    rows = list(result.scalars().all())
    await _annotate_duplicates(session, tenant_id=tenant_id, rows=rows)
    return rows


async def _annotate_duplicates(
    session: AsyncSession, *, tenant_id: uuid.UUID, rows: list[Manager]
) -> None:
    """Mark contacts that share an e-mail address with another row.

    The source genuinely holds the same person twice — "Mick Drahtschmid" exists
    as MNGR571 and MNGR572, created seconds apart, same address. The import
    copies both faithfully, which is correct: they ARE two records, and merging
    them here would silently pick a winner and would be undone by the next run,
    since idempotency is keyed on the source id.

    So they are flagged, not merged. The reader decides; the importer does not
    guess.

    The test is e-mail AND name together, because e-mail alone is not identity:
    `info@occhio.com` is a shared company mailbox listed by three different
    people, and `huehn.a@eplan.de` sits on Anna Vogel's record as well as Anna
    Huehn's — a typo in the source. Matching on the address alone would call
    all of those duplicates of each other, which is a worse error than missing
    one: it accuses two real colleagues of being the same person.

    Set as a transient attribute: it is a fact about the SET being displayed,
    not a property of the row.
    """
    emails = {
        (r.email or "").strip().lower() for r in rows if (r.email or "").strip()
    }
    counts: dict[tuple[str, str], int] = {}
    if emails:
        result = await session.execute(
            select(
                func.lower(Manager.email),
                func.lower(Manager.full_name),
                func.count(Manager.id),
            )
            .where(
                Manager.tenant_id == tenant_id,
                func.lower(Manager.email).in_(emails),
            )
            .group_by(func.lower(Manager.email), func.lower(Manager.full_name))
        )
        counts = {(email, name): n for email, name, n in result.all() if n > 1}
    for row in rows:
        email = (row.email or "").strip().lower()
        name = (row.full_name or "").strip().lower()
        row.duplicate_count = counts.get((email, name), 1) if email else 1


async def get_manager(
    session: AsyncSession, *, tenant_id: uuid.UUID, manager_id: uuid.UUID
) -> Manager | None:
    manager = await session.scalar(
        select(Manager)
        .options(selectinload(Manager.interactions))
        .where(Manager.id == manager_id, Manager.tenant_id == tenant_id)
    )
    if manager is None:
        return None
    # Counted here rather than in the router so the profile is one request. Set
    # as transient attributes: they are facts ABOUT the row, not columns on it,
    # and storing them would mean keeping two numbers in step with the tables
    # that produce them.
    manager.job_count = (
        await session.scalar(
            select(func.count(Job.id)).where(
                Job.tenant_id == tenant_id, Job.manager_id == manager_id
            )
        )
    ) or 0
    manager.open_job_count = (
        await session.scalar(
            select(func.count(Job.id)).where(
                Job.tenant_id == tenant_id,
                Job.manager_id == manager_id,
                Job.status.in_(LIVE_JOB_STATUSES),
            )
        )
    ) or 0
    manager.note_count = len(manager.interactions)
    await _annotate_duplicates(session, tenant_id=tenant_id, rows=[manager])
    return manager


async def create_manager(
    session: AsyncSession, *, tenant_id: uuid.UUID, payload: ManagerCreate
) -> Manager:
    """Add a contact at one of this tenant's own companies.

    The company is verified to belong to the tenant first. `company_id` is a
    client-supplied UUID, and without that check a caller could attach a person
    to another tenant's company — RLS would not catch it, because the write
    itself is perfectly valid for the writer's own tenant.
    """
    await _own_company(session, tenant_id=tenant_id, company_id=payload.company_id)

    manager = Manager(
        tenant_id=tenant_id,
        company_id=payload.company_id,
        full_name=payload.full_name.strip(),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role_title=payload.role_title,
        department=payload.department,
        email=payload.email,
        phone=payload.phone,
        linkedin_url=payload.linkedin_url,
        source=payload.source.value,
        source_detail=payload.source_detail,
        notes=payload.notes,
    )
    session.add(manager)
    await session.commit()
    await session.refresh(manager)
    return manager


async def update_manager(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID,
    payload: ManagerUpdate,
) -> Manager | None:
    manager = await session.scalar(
        select(Manager).where(
            Manager.id == manager_id, Manager.tenant_id == tenant_id
        )
    )
    if manager is None:
        return None
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(manager, field, value)
    await session.commit()
    await session.refresh(manager)
    return manager


async def mark_art14_notified(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID,
    at: dt.datetime | None = None,
) -> Manager | None:
    """Record that the data subject has been informed (GDPR Art. 14).

    Separate from `update_manager` on purpose: this asserts something happened
    in the world, and it should not be settable as a side effect of editing a
    phone number.
    """
    manager = await session.scalar(
        select(Manager).where(
            Manager.id == manager_id, Manager.tenant_id == tenant_id
        )
    )
    if manager is None:
        return None
    manager.art14_notified_at = at or dt.datetime.now(dt.UTC)
    await session.commit()
    await session.refresh(manager)
    return manager


async def managers_owing_art14(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[Manager]:
    """The work queue: people we hold data on who have not been told.

    Filtered in Python over the tenant's rows rather than in SQL, because the
    obligation is derived from `source` by one shared predicate
    (`owes_art14_notice`) and duplicating that set into a WHERE clause is how
    the two definitions drift apart.
    """
    rows = await list_managers(session, tenant_id=tenant_id, limit=10_000)
    return [m for m in rows if m.art14_outstanding]


#: Which kinds move "letzter Kontakt". Defined once in `common/enums.py`
#: alongside the vocabulary itself — this used to be a second list here, and
#: a second list is how `NOT_REACHED` would have been forgotten.
CONTACT_KINDS = CONTACT_INTERACTION_KINDS


def _advance_last_contact(manager: Manager, occurred_at: dt.datetime) -> None:
    """Move the contact date forward, never back.

    Notes get filed late and out of order — somebody writes up Tuesday's call
    on Friday, after Thursday's mail is already in. Taking the newest WRITE
    rather than the newest EVENT would then rewind the date and make a fresh
    relationship look stale.
    """
    current = manager.last_contact_at
    if current is not None and current.tzinfo is None:
        # SQLite hands back a naive datetime even for a tz-aware column.
        current = current.replace(tzinfo=dt.UTC)
    if current is None or occurred_at > current:
        manager.last_contact_at = occurred_at


async def log_interaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID | None,
    payload: ManagerInteractionCreate,
) -> ManagerInteraction | None:
    """Record one touch. `manager_id` may be None for a mandate-level note.

    A briefing belongs to the mandate: the conversation that defines it often
    happens before the contact is in the record, and refusing the note until
    somebody creates a `managers` row means the note is never written.
    """
    manager = None
    if manager_id is not None:
        manager = await session.scalar(
            select(Manager).where(
                Manager.id == manager_id, Manager.tenant_id == tenant_id
            )
        )
        if manager is None:
            return None
    occurred_at = payload.occurred_at or dt.datetime.now(dt.UTC)
    # Normalised on the way in as well as on the way out: the schema accepts
    # an `InteractionType`, but a re-import or an older client can still
    # present "BD Call", and two spellings of one kind in the column is the
    # state ELI-9 exists to end.
    kind = normalise_interaction_type(payload.interaction_type)
    interaction = ManagerInteraction(
        tenant_id=tenant_id,
        manager_id=manager_id,
        candidate_id=payload.candidate_id,
        job_id=payload.job_id,
        interaction_type=kind,
        occurred_at=occurred_at,
        summary=payload.summary,
    )
    if manager is not None and kind in CONTACT_KINDS:
        _advance_last_contact(manager, occurred_at)
    session.add(interaction)
    await session.commit()
    await session.refresh(interaction)
    return interaction


async def list_interactions(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID,
    limit: int = 200,
) -> list[ManagerInteraction]:
    result = await session.execute(
        select(ManagerInteraction)
        .where(
            ManagerInteraction.tenant_id == tenant_id,
            ManagerInteraction.manager_id == manager_id,
        )
        .order_by(ManagerInteraction.occurred_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_candidate_interactions(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    limit: int = 200,
) -> list[ManagerInteraction]:
    """Every note filed against one candidate, newest first.

    Lives in this domain because the row does: `manager_interactions` has
    carried a nullable `candidate_id` since it was created and not one of the
    366 imported rows ever filled it. ELI-9 is what finally fills it, and a
    second table for the same shape of note would mean a candidate's history
    and a manager's history could not be read together.
    """
    result = await session.execute(
        select(ManagerInteraction)
        .where(
            ManagerInteraction.tenant_id == tenant_id,
            ManagerInteraction.candidate_id == candidate_id,
        )
        .order_by(ManagerInteraction.occurred_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def log_candidate_interaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    payload: ManagerInteractionCreate,
) -> ManagerInteraction | None:
    """Record one touch on a candidate. None when the candidate is not ours.

    `manager_id` stays empty: this is a conversation with the candidate, not
    with a client contact. A note that is about both — what a manager said
    regarding one candidate — is a FEEDBACK row on the mandate, which has its
    own panel.
    """
    candidate = await session.scalar(
        select(Candidate).where(
            Candidate.id == candidate_id, Candidate.tenant_id == tenant_id
        )
    )
    if candidate is None:
        return None

    interaction = ManagerInteraction(
        tenant_id=tenant_id,
        manager_id=None,
        candidate_id=candidate_id,
        job_id=payload.job_id,
        interaction_type=normalise_interaction_type(payload.interaction_type),
        occurred_at=payload.occurred_at or dt.datetime.now(dt.UTC),
        summary=payload.summary,
    )
    session.add(interaction)
    await session.commit()
    await session.refresh(interaction)
    return interaction


async def list_for_job(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    limit: int = 200,
    kinds: Collection[InteractionType] | None = None,
    exclude: Collection[InteractionType] | None = None,
) -> list[ManagerInteraction]:
    """Everything said ABOUT one mandate, newest first.

    Reads the same table as a contact's history, from the other side: the
    briefing, the sharpened Muss-Profil, the "they want someone who can also
    do X" — all of it is a conversation with a person about a job, and both
    questions ("what did we discuss with her?" and "what do we know about
    this mandate?") are worth being able to ask.

    `kinds` / `exclude` split the two readings of that: what the client wants
    from the mandate, and what anybody thought of one candidate on it. Both
    are rows here; showing them in one list would mix a Muss-Kriterium with a
    remark about one person.
    """
    query = select(ManagerInteraction).where(
        ManagerInteraction.tenant_id == tenant_id,
        ManagerInteraction.job_id == job_id,
    )
    if kinds is not None:
        query = query.where(
            ManagerInteraction.interaction_type.in_([k.value for k in kinds])
        )
    if exclude:
        query = query.where(
            ManagerInteraction.interaction_type.notin_([k.value for k in exclude])
        )
    rows = await session.scalars(
        query.order_by(ManagerInteraction.occurred_at.desc()).limit(limit)
    )
    return list(rows)
