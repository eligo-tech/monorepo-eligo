"""Importing a recruiter's own ATS into the system-of-record.

Destination first, because it is the decision that matters: this writes
tenant-scoped `companies`, `managers`, `jobs` and `candidates`, and never a
`hub_` table. The corpus is shared across workspaces by design; a customer's
clients, contacts and mandates are the opposite of shared. Putting them there
would publish one customer's book of business to all of them.

Idempotent by construction. Every row carries the id it has in aiFind, so a
second run updates what it created rather than duplicating it. That is not a
nicety: this is meant to run on a schedule, and an importer that cannot
recognise its own output doubles the book every night.

Order is load-bearing: companies, then managers (which need a company), then
jobs (which need both). A mandate whose company failed to import is attached to
nothing rather than to the wrong account.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.candidates.models import Candidate
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction

SOURCE = "aifind"


def _as_datetime(value: str | None) -> dt.datetime | None:
    """ISO-8601 with a Z suffix -> aware datetime.

    `fromisoformat` rejects the trailing Z on older Pythons and the source uses
    it everywhere, so it is normalised rather than trusted.
    """
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclasses.dataclass
class ImportSummary:
    companies_created: int = 0
    companies_updated: int = 0
    managers_created: int = 0
    managers_updated: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    candidates_created: int = 0
    candidates_updated: int = 0
    #: Mandates whose company or manager was absent from the source. Counted and
    #: named rather than dropped silently — a mandate that lost its client is a
    #: fact about the import, not an implementation detail.
    jobs_without_company: int = 0
    jobs_without_manager: int = 0
    notes_created: int = 0

    def as_dict(self) -> dict[str, int]:
        return dataclasses.asdict(self)


async def _by_external_id(
    session: AsyncSession, model, *, tenant_id: uuid.UUID, source_column: str
) -> dict[str, object]:
    """Everything this tenant has already imported from this source, by its id."""
    rows = await session.scalars(
        select(model).where(
            model.tenant_id == tenant_id,
            getattr(model, source_column) == SOURCE,
            model.external_id.is_not(None),
        )
    )
    return {row.external_id: row for row in rows}


async def import_aifind(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    companies: list,
    managers: list,
    jobs: list,
    candidates: list | None = None,
) -> ImportSummary:
    """Upsert one aiFind export into this workspace. Pure of network by design.

    Takes already-parsed records rather than a client, so the whole mapping is
    testable against a captured payload with no credentials and no network —
    the same split `hub/adapters` uses.
    """
    summary = ImportSummary()

    # --- companies ---------------------------------------------------------
    existing_companies = await _by_external_id(
        session, Company, tenant_id=tenant_id, source_column="source"
    )
    company_by_external: dict[str, Company] = dict(existing_companies)  # type: ignore[arg-type]
    for record in companies:
        row = existing_companies.get(record.external_id)
        if row is None:
            row = Company(
                tenant_id=tenant_id,
                name=record.name,
                source=SOURCE,
                external_id=record.external_id,
                # These are the workspace's own accounts, not market
                # observations — that is what importing an ATS means.
                is_client=True,
            )
            session.add(row)
            summary.companies_created += 1
        elif row.name != record.name:
            row.name = record.name
            summary.companies_updated += 1
        company_by_external[record.external_id] = row
    await session.flush()

    # --- managers ----------------------------------------------------------
    existing_managers = await _by_external_id(
        session, Manager, tenant_id=tenant_id, source_column="external_source"
    )
    manager_by_external: dict[str, Manager] = dict(existing_managers)  # type: ignore[arg-type]
    for record in managers:
        company = (
            company_by_external.get(record.company_external_id)
            if record.company_external_id
            else None
        )
        if company is None:
            # `managers.company_id` is NOT NULL: a contact belongs to an
            # account. A person whose company did not import has nowhere to
            # hang, and inventing a placeholder company to hold them would put
            # a fictional account in the record.
            continue
        # Written on create AND update, for the same reason candidates are: the
        # first import predated the detail pass, so its rows hold a name, a role
        # and nothing to call the person with.
        detail = {
            "full_name": record.full_name,
            "role_title": record.job_title,
            "first_name": record.first_name,
            "last_name": record.last_name,
            "department": record.department,
            "email": record.email,
            "phone": record.phone,
            "external_code": record.code,
            "looks_for": record.looks_for,
            "street": record.street,
            "postal_code": record.postal_code,
            "city": record.city,
            "country": record.country,
            "last_contact_at": _as_datetime(record.last_contact_at),
        }
        row = existing_managers.get(record.external_id)
        if row is None:
            row = Manager(
                tenant_id=tenant_id,
                company_id=company.id,
                full_name=record.full_name,
                role_title=record.job_title,
                external_id=record.external_id,
                external_source=SOURCE,
                skills=list(record.skills),
                tags=list(record.tags),
                # The recruiter's own CRM record, entered by them. Not collected
                # from a third party by US, so no Art. 14 notice falls due here
                # — the obligation, if any, arose when they first recorded the
                # person, and moving their own data between their own systems
                # is not a new collection. Recorded explicitly so the judgement
                # is visible and reversible rather than implied by a default.
                source=ConfidenceSource.HUMAN_VERIFIED.value,
                source_detail=f"{SOURCE}:{record.external_id}",
            )
            session.add(row)
            summary.managers_created += 1
        else:
            changed = False
            for attr, value in detail.items():
                # Absent in the source is not "delete what we have": a detail
                # call that failed would otherwise blank a good record.
                if value is not None and getattr(row, attr) != value:
                    setattr(row, attr, value)
                    changed = True
            if record.skills and list(row.skills or []) != list(record.skills):
                row.skills = list(record.skills)
                changed = True
            if record.tags and list(row.tags or []) != list(record.tags):
                row.tags = list(record.tags)
                changed = True
            if row.company_id != company.id:
                # People move. That is the single most valuable signal in
                # recruiting BD, so following it matters more than stability.
                row.company_id = company.id
                changed = True
            summary.managers_updated += int(changed)
        manager_by_external[record.external_id] = row
    await session.flush()

    # --- the conversation history ------------------------------------------
    # This is the part of a CRM that cannot be re-derived. A company can be
    # re-crawled and a mandate re-entered; "Budgets gerade low, nochmal im
    # November" exists only because someone wrote it down after a call.
    existing_notes = {
        row.external_id: row
        for row in await session.scalars(
            select(ManagerInteraction).where(
                ManagerInteraction.tenant_id == tenant_id,
                ManagerInteraction.external_source == SOURCE,
                ManagerInteraction.external_id.is_not(None),
            )
        )
    }
    for record in managers:
        manager_row = manager_by_external.get(record.external_id)
        if manager_row is None:
            continue
        for note in record.notes:
            if note.external_id in existing_notes:
                continue
            session.add(
                ManagerInteraction(
                    tenant_id=tenant_id,
                    manager_id=manager_row.id,
                    # The source's own category ("BD Call", "Meeting Notes") is
                    # kept verbatim rather than mapped onto InteractionType: a
                    # forced mapping would turn a category someone chose into a
                    # near-miss, and the recruiter's word is the useful one.
                    interaction_type=note.category or "note",
                    occurred_at=_as_datetime(note.created_at)
                    or dt.datetime.now(dt.UTC),
                    summary=note.text,
                    external_id=note.external_id,
                    external_source=SOURCE,
                )
            )
            summary.notes_created += 1

    # --- jobs --------------------------------------------------------------
    existing_jobs = await _by_external_id(
        session, Job, tenant_id=tenant_id, source_column="external_source"
    )
    for record in jobs:
        company = (
            company_by_external.get(record.company.external_id)
            if record.company
            else None
        )
        manager = (
            manager_by_external.get(record.manager.external_id)
            if record.manager
            else None
        )
        summary.jobs_without_company += int(company is None)
        summary.jobs_without_manager += int(manager is None)

        row = existing_jobs.get(record.external_id)
        status = "open" if record.is_open else "closed"
        if row is None:
            session.add(
                Job(
                    tenant_id=tenant_id,
                    title=record.title,
                    client_company_id=company.id if company else None,
                    manager_id=manager.id if manager else None,
                    status=status,
                    external_id=record.external_id,
                    external_source=SOURCE,
                )
            )
            summary.jobs_created += 1
        else:
            changed = False
            for attr, value in (
                ("title", record.title),
                ("status", status),
                ("client_company_id", company.id if company else None),
                ("manager_id", manager.id if manager else None),
            ):
                if value is not None and getattr(row, attr) != value:
                    setattr(row, attr, value)
                    changed = True
            summary.jobs_updated += int(changed)

    # --- candidates --------------------------------------------------------
    existing_candidates = await _by_external_id(
        session, Candidate, tenant_id=tenant_id, source_column="external_source"
    )
    for record in candidates or []:
        row = existing_candidates.get(record.external_id)
        # Written on create AND on update: the first import ran before the
        # detail pass existed, so the rows it made carry a name and a title and
        # nothing else. Re-running must fill them in rather than decide they
        # already exist and move on.
        fields = {
            "full_name": record.full_name,
            "current_title": record.job_title,
            "employment_type": record.employment,
            "first_name": record.first_name,
            "last_name": record.last_name,
            "sex": record.sex,
            "name_prefix": record.name_prefix,
            "date_of_birth": record.date_of_birth,
            "email": record.email,
            "xing_url": record.xing_url,
            "current_company": record.current_company,
            "industry": record.industry,
            "street": record.street,
            "postal_code": record.postal_code,
            "city": record.city,
            "country": record.country,
            # `location` is what the matcher's radius filter reads, and the
            # source has no single field for it — composed from the parts that
            # exist rather than left empty.
            "location": ", ".join(
                p for p in (record.city, record.country) if p
            )
            or None,
        }
        if row is None:
            session.add(
                Candidate(
                    tenant_id=tenant_id,
                    external_id=record.external_id,
                    external_source=SOURCE,
                    skills=list(record.skills),
                    **{k: v for k, v in fields.items() if v is not None},
                )
            )
            summary.candidates_created += 1
        else:
            changed = False
            for attr, value in fields.items():
                # Absent in the source is not "delete what we have": a detail
                # call that failed would otherwise blank a good record.
                if value is not None and getattr(row, attr) != value:
                    setattr(row, attr, value)
                    changed = True
            if record.skills and list(row.skills or []) != list(record.skills):
                row.skills = list(record.skills)
                changed = True
            summary.candidates_updated += int(changed)

    await session.commit()
    return summary
