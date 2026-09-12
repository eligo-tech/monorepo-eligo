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
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.candidates.models import Candidate
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager

SOURCE = "aifind"


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
        row = existing_managers.get(record.external_id)
        if row is None:
            row = Manager(
                tenant_id=tenant_id,
                company_id=company.id,
                full_name=record.full_name,
                role_title=record.job_title,
                external_id=record.external_id,
                external_source=SOURCE,
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
            if row.full_name != record.full_name:
                row.full_name = record.full_name
                changed = True
            if record.job_title and row.role_title != record.job_title:
                row.role_title = record.job_title
                changed = True
            if row.company_id != company.id:
                # People move. That is the single most valuable signal in
                # recruiting BD, so following it matters more than stability.
                row.company_id = company.id
                changed = True
            summary.managers_updated += int(changed)
        manager_by_external[record.external_id] = row
    await session.flush()

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
        if row is None:
            session.add(
                Candidate(
                    tenant_id=tenant_id,
                    full_name=record.full_name,
                    current_title=record.job_title,
                    postal_code=record.postal_code,
                    employment_type=record.employment,
                    external_id=record.external_id,
                    external_source=SOURCE,
                )
            )
            summary.candidates_created += 1
        elif row.full_name != record.full_name:
            row.full_name = record.full_name
            summary.candidates_updated += 1

    await session.commit()
    return summary
