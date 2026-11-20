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
    APPOINTMENT_INTERACTION_KINDS,
    CallOutcome,
    ConfidenceSource,
    CONTACT_INTERACTION_KINDS,
    InteractionType,
    LIVE_JOB_STATUSES,
    interaction_spellings,
    normalise_interaction_type,
)
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction, ManagerPhone
from app.domain.managers.schemas import (
    ManagerCreate,
    ManagerInteractionCreate,
    ManagerPhoneIn,
    ManagerUpdate,
)


class CompanyNotInTenant(Exception):
    """The company does not belong to this tenant (or does not exist).

    Raised rather than returning None so the caller cannot mistake a rejected
    write for an empty result: a manager attached to another tenant's company
    would be a cross-tenant leak, not a 404.
    """


class NotALead(Exception):
    """ELI-66: only a lead (stage `bus_dev`) is removed from the Leads list."""


class NotInterested(Exception):
    """ELI-60: the person is already this workspace's lead, marked
    "Kein Interesse" — they are not created a second time."""

    def __init__(self, manager: Manager) -> None:
        super().__init__(str(manager.id))
        self.manager = manager


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
    stage: str | None = None,
) -> int:
    """How many contacts exist, independent of any page or search term."""
    stmt = select(func.count()).select_from(Manager).where(Manager.tenant_id == tenant_id)
    if company_id is not None:
        stmt = stmt.where(Manager.company_id == company_id)
    if stage is not None:
        stmt = stmt.where(Manager.stage == stage)
    return int(await session.scalar(stmt) or 0)


async def list_managers(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 100,
    stage: str | None = None,
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
    if stage is not None:
        # ELI-23: the Manager screen asks for "manager" — vetted contacts only;
        # the bus-dev contacts from Markt have their own list.
        stmt = stmt.where(Manager.stage == stage)
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
    company = await _own_company(session, tenant_id=tenant_id, company_id=payload.company_id)
    from app.domain.erasure import service as erasure

    await erasure.guard_readd(
        session, tenant_id=tenant_id, email=payload.email, override=payload.override_suppression
    )
    if not payload.override_suppression:
        # ELI-22: ad contacts rarely carry an e-mail — the erased person is
        # also recognised by direct phone and by surname at this employer.
        # The recruiter's override (they came back of their own accord) wins.
        guard = await erasure.person_guard(session, tenant_id)
        names = await erasure.employer_names(session, tenant_id, company.id)
        on = guard.erased_on(
            company_name=names[0] if names else company.name, other_names=tuple(names[1:]),
            surname=payload.last_name or payload.full_name, phone=payload.phone,
        )
        if on is not None:
            raise erasure.Suppressed(on)

    if stage_for(payload.source.value) == "bus_dev":
        # ELI-60: a new lead from Markt who is already here with "Kein
        # Interesse" is recognised (the call list's own same-person rule),
        # not created again and not moved back into Leads.
        await _refuse_no_interest_again(session, tenant_id, payload)

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
        # ELI-23: a person taken from a public ad is a new bus-dev contact.
        stage=stage_for(payload.source.value),
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
    editor: str | None = None,
) -> Manager | None:
    """A recruiter's edit of a contact (ELI-45/46/66).

    Each field that really changes goes through `verify_and_commit` as a
    `human_verified` proposal — the recruiter is the field's provenance, the
    same rule as a candidate's manual edit — leaving an `EnrichmentRecord`
    and receipts naming the field. A move to another company is checked to
    be one of this workspace's own (`CompanyNotInTenant` otherwise).
    """
    manager = await session.scalar(
        select(Manager).where(
            Manager.id == manager_id, Manager.tenant_id == tenant_id
        )
    )
    if manager is None:
        return None
    changes = payload.model_dump(exclude_unset=True)
    override = bool(changes.pop("override_suppression", False))
    if changes.get("email") and changes["email"] != manager.email:
        from app.domain.erasure import service as erasure

        await erasure.guard_readd(
            session, tenant_id=tenant_id, email=changes["email"], override=override
        )
    phones = payload.phones if "phones" in changes else None
    changes.pop("phones", None)
    held = {p["number"] for p in manager.phones}
    added = [n for n in ([changes["phone"]] if changes.get("phone") else [p.number for p in phones or []])
             if n not in held]
    if added and not override:
        # ELI-45: the phone is editable on the Manager page. Create refuses an
        # erased person's direct number; setting it by an edit is the same act
        # — for every number added (ELI-46), not only the primary.
        from app.domain.erasure import service as erasure

        guard = await erasure.person_guard(session, tenant_id)
        for number in added:
            on = guard.erased_on(company_name=None, surname=None, phone=number)
            if on is not None:
                raise erasure.Suppressed(on)
    target = manager.company_id
    if changes.get("company_id") and changes["company_id"] != manager.company_id:
        target = (await _own_company(session, tenant_id=tenant_id, company_id=changes["company_id"])).id
    renamed = any(f in changes and changes[f] != getattr(manager, f) for f in ("full_name", "last_name"))
    if not override and (renamed or target != manager.company_id):
        # ELI-66: name and company are editable. Create refuses an erased
        # person by surname at their employer; a rename or a move onto that
        # surname there is the same act.
        from app.domain.erasure import service as erasure

        guard = await erasure.person_guard(session, tenant_id)
        names = await erasure.employer_names(session, tenant_id, target)
        surname = changes.get("last_name", manager.last_name) or changes.get("full_name", manager.full_name)
        if names:
            on = guard.erased_on(company_name=names[0], other_names=tuple(names[1:]), surname=surname, phone=None)
            if on is not None:
                raise erasure.Suppressed(on)
    effective = {f: v for f, v in changes.items() if getattr(manager, f, None) != v}
    if phones is not None:
        wanted = [{"number": p.number, "kind": p.kind} for p in phones]
        if wanted != [{"number": p["number"], "kind": p["kind"]} for p in manager.phones]:
            effective["phones"] = wanted
    detail = f"manual edit via recruiter UI ({editor})" if editor else "manual edit via recruiter UI"
    for field, value in effective.items():
        await _commit_edit(session, manager, field, value, detail=detail, editor=editor)
    if phones is not None and "phones" in effective:
        _set_phones(manager, phones)
    elif "phone" in effective and not manager.phone and manager.extra_phones:
        # The primary was removed by a writer that knows only `phone`: the
        # next number moves up rather than the contact showing no primary.
        _set_phones(manager, [ManagerPhoneIn(number=p.number, kind=p.kind) for p in manager.extra_phones])
    await session.commit()
    await session.refresh(manager)
    return manager


async def _commit_edit(session: AsyncSession, manager: Manager, field: str, value: object, *,
                       detail: str, editor: str | None) -> None:
    """One hand-edited field through the verification gate. `phones` is
    recorded here and written by `_set_phones` after."""
    import json

    from app.domain.verification import service as verification
    from app.domain.verification.schemas import ProposedChange

    text = value if value is None or isinstance(value, str) else (
        json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value))
    change = ProposedChange(
        tenant_id=manager.tenant_id, entity_type="manager", entity_id=manager.id, field=field,
        proposed_value=text, source=ConfidenceSource.HUMAN_VERIFIED, source_detail=detail, confidence=1.0,
    )

    async def _apply(_s: AsyncSession, _c: ProposedChange) -> None:
        if field != "phones":
            setattr(manager, field, value)

    await verification.verify_and_commit(
        session, change=change, agent="recruiter_manual_edit", apply_hook=_apply, actor=editor,
    )


async def remove_lead(session: AsyncSession, *, tenant_id: uuid.UUID, manager_id: uuid.UUID,
                      reason: str, note: str | None = None) -> Manager | None:
    """ELI-66 "Entfernen": the lead leaves the Leads list and the record
    stays — the same `no_interest_at` as "Kein Interesse" (restorable by
    `revive_lead`, not taken again from Markt), plus the reason code and the
    recruiter's words. A lead already hidden keeps its date. One receipt
    naming the code, never the words. Raises `NotALead` for a vetted
    manager: they are not on the Leads list to be removed from."""
    from app.domain.common.enums import ReceiptAction
    from app.domain.verification import service as verification

    manager = await session.scalar(
        select(Manager).where(Manager.id == manager_id, Manager.tenant_id == tenant_id)
    )
    if manager is None:
        return None
    if manager.stage != "bus_dev":
        raise NotALead(str(manager.id))
    manager.no_interest_at = manager.no_interest_at or dt.datetime.now(dt.UTC)
    manager.removed_reason = reason
    manager.removed_note = (note or "").strip() or None
    await verification.append_receipt(
        session, tenant_id=tenant_id, agent="recruiter", action=ReceiptAction.WRITE,
        subject_type="manager", subject_id=str(manager.id), verified=True,
        summary="Lead entfernt", payload={"status": "removed", "reason": reason},
    )
    await session.commit()
    await session.refresh(manager)
    return manager


async def _refuse_no_interest_again(session: AsyncSession, tenant_id: uuid.UUID, payload: ManagerCreate) -> None:
    from app.domain.hub.call_list import _existing_manager, _surname_key

    key = _surname_key(payload.last_name, payload.full_name)
    if not key:
        return
    first = payload.first_name
    if not first and not payload.last_name:
        parts = payload.full_name.split()
        first = parts[0] if len(parts) > 1 else None
    found = await _existing_manager(session, tenant_id, payload.company_id, key, first)
    if found is not None and found.no_interest_at is not None:
        raise NotInterested(found)


async def mark_no_interest(session: AsyncSession, *, tenant_id: uuid.UUID, manager: Manager,
                           interaction_id: uuid.UUID | None = None) -> None:
    """ELI-60: "Kein Interesse" — the lead leaves the Leads list, the record
    stays. Only a lead (stage `bus_dev`); a second mark keeps the first date.
    One receipt naming the call, never its words. The caller commits."""
    from app.domain.common.enums import ReceiptAction
    from app.domain.verification import service as verification

    if manager.stage != "bus_dev" or manager.no_interest_at is not None:
        return
    manager.no_interest_at = dt.datetime.now(dt.UTC)
    payload: dict[str, object] = {"status": "no_interest"}
    if interaction_id is not None:
        payload["interaction_id"] = str(interaction_id)
    await verification.append_receipt(
        session, tenant_id=tenant_id, agent="recruiter", action=ReceiptAction.WRITE,
        subject_type="manager", subject_id=str(manager.id), verified=True,
        summary="Kein Interesse vermerkt", payload=payload,
    )


async def revive_lead(session: AsyncSession, *, tenant_id: uuid.UUID, manager_id: uuid.UUID) -> Manager | None:
    """ELI-60: "Wieder als Lead aufnehmen" — back on the Leads list."""
    from app.domain.common.enums import ReceiptAction
    from app.domain.verification import service as verification

    manager = await session.scalar(
        select(Manager).where(Manager.id == manager_id, Manager.tenant_id == tenant_id)
    )
    if manager is None:
        return None
    if manager.no_interest_at is not None:
        manager.no_interest_at = None
        manager.removed_reason = None
        manager.removed_note = None
        await verification.append_receipt(
            session, tenant_id=tenant_id, agent="recruiter", action=ReceiptAction.WRITE,
            subject_type="manager", subject_id=str(manager.id), verified=True,
            summary="Wieder als Lead aufgenommen", payload={"status": "lead"},
        )
        await session.commit()
        await session.refresh(manager)
    return manager


def _set_phones(manager: Manager, phones: list[ManagerPhoneIn]) -> None:
    """Store the list (ELI-46): the primary — first, see `schemas._phone_list`
    — on the row as `phone`/`phone_kind`, the rest as `extra_phones`."""
    primary, *rest = phones or [None]
    manager.phone = primary.number if primary else None
    manager.phone_kind = primary.kind if primary else None
    manager.extra_phones = [
        ManagerPhone(tenant_id=manager.tenant_id, number=p.number, kind=p.kind, position=i)
        for i, p in enumerate(rest, start=1)
    ]


def stage_for(source: str | None) -> str:
    """Where a new contact starts (ELI-23): from Markt (a public ad) as a
    bus-dev contact, otherwise as a manager."""
    return "bus_dev" if source == ConfidenceSource.PUBLIC_WEB.value else "manager"


async def promote_manager(
    session: AsyncSession, *, tenant_id: uuid.UUID, manager_id: uuid.UUID
) -> Manager | None:
    """Move a bus-dev contact to Managers once the first contact is done.
    Idempotent; nothing about the person is copied or lost."""
    manager = await session.scalar(
        select(Manager).where(Manager.id == manager_id, Manager.tenant_id == tenant_id)
    )
    if manager is None:
        return None
    if manager.stage != "manager":
        manager.stage = "manager"
        manager.promoted_at = dt.datetime.now(dt.UTC)
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
    # A meeting booked for next week is not contact made next week (ELI-40):
    # "Letzter Kontakt" never shows a date that has not happened yet.
    if occurred_at > dt.datetime.now(dt.UTC):
        return
    if current is None or occurred_at > current:
        manager.last_contact_at = occurred_at


async def log_interaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID | None,
    payload: ManagerInteractionCreate,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
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
        outcome=payload.outcome.value if payload.outcome else None,
        next_action_at=payload.next_action_at,
        # ELI-15: who wrote it, so the KPI can be counted per consultant off
        # this row rather than off a copy of it.
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )
    if manager is not None and kind in CONTACT_KINDS:
        _advance_last_contact(manager, occurred_at)
    session.add(interaction)
    if payload.do_not_contact and manager is not None:
        await _mark_do_not_contact(session, tenant_id, "manager", manager, interaction)
    if payload.outcome == CallOutcome.NOT_INTERESTED and manager is not None:
        await session.flush()
        await mark_no_interest(session, tenant_id=tenant_id, manager=manager, interaction_id=interaction.id)
    await session.commit()
    await session.refresh(interaction)
    return interaction


async def _mark_do_not_contact(session: AsyncSession, tenant_id: uuid.UUID, subject: str, person, interaction) -> None:  # noqa: ANN001
    """ELI-32: the note says "nicht mehr kontaktieren" — mark the person in
    the note's own transaction, the receipt naming the note."""
    from app.domain.erasure import do_not_contact

    await session.flush()
    await do_not_contact.mark(
        session, tenant_id=tenant_id, subject=subject, person=person, interaction_id=interaction.id,
    )


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


async def list_appointments(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID,
    limit: int = 200,
) -> list[ManagerInteraction] | None:
    """The manager's Termine (ELI-40): the interactions of an appointment kind.

    None when the manager is not in this workspace, so the router can say 404
    rather than an empty calendar that suggests the person exists.
    """
    exists = await session.scalar(
        select(Manager.id).where(Manager.id == manager_id, Manager.tenant_id == tenant_id)
    )
    if exists is None:
        return None
    spellings = interaction_spellings(APPOINTMENT_INTERACTION_KINDS)
    result = await session.execute(
        select(ManagerInteraction)
        .where(
            ManagerInteraction.tenant_id == tenant_id,
            ManagerInteraction.manager_id == manager_id,
            func.lower(func.trim(ManagerInteraction.interaction_type)).in_(spellings),
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
    actor_user_id: str | None = None,
    actor_name: str | None = None,
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
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )
    session.add(interaction)
    if payload.do_not_contact:
        await _mark_do_not_contact(session, tenant_id, "candidate", candidate, interaction)
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
