"""Importing a recruiter's own ATS.

Two things are being protected. The first is idempotency: this is meant to run
on a schedule, and an importer that cannot recognise its own output doubles the
book every night. The second is the boundary — a customer's clients, contacts
and mandates must land in tenant tables and never in the shared corpus.

The payloads below are the real shape, captured from the running client: padded
names ("Stefan " / "Graf"), a null priority, ids as opaque strings.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.atsimport import service as importer
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager
from app.integrations import aifind

TENANT = uuid.uuid4()

COMPANIES_PAYLOAD = {
    "data": {
        "companies": {
            "total": 2,
            "hits": [
                {"id": "c1", "name": "Conrad Electronic SE"},
                {"id": "c2", "name": "SSI Schaefer IT Solutions GmbH"},
            ],
        }
    }
}

MANAGERS_PAYLOAD = {
    "data": {
        "managers": {
            "total": 3,
            "hits": [
                {
                    "id": "m1",
                    "first_name": "Stefan ",
                    "last_name": "Graf",
                    "job_title": "Head of IT",
                    "company": {"id": "c1", "name": "Conrad Electronic SE"},
                },
                {
                    "id": "m2",
                    "first_name": "Anna",
                    "last_name": "Bennech",
                    "job_title": None,
                    "company": {"id": "c2", "name": "SSI Schaefer IT Solutions GmbH"},
                },
                # No company: nowhere to hang, must be skipped not invented.
                {
                    "id": "m3",
                    "first_name": "Orphan",
                    "last_name": "Contact",
                    "company": None,
                },
            ],
        }
    }
}

JOBS_PAYLOAD = {
    "data": {
        "jobs": {
            "total": 2,
            "hits": [
                {
                    "id": "j1",
                    "title": "Head of SAP",
                    "priority": None,
                    "isOpen": True,
                    "employment": "Permanent",
                    "added_by": "connect@example.test",
                    "owner": "connect@example.test",
                    "manager": {
                        "id": "m1",
                        "first_name": "Stefan ",
                        "last_name": "Graf",
                    },
                    "company": {"id": "c1", "name": "Conrad Electronic SE"},
                },
                {
                    "id": "j2",
                    "title": "Contract- & Claim Manager (w/m/d)",
                    "priority": "A",
                    "isOpen": False,
                    "employment": "Permanent",
                    "added_by": "connect@example.test",
                    "owner": None,
                    "manager": {
                        "id": "m2",
                        "first_name": "Anna",
                        "last_name": "Bennech",
                    },
                    "company": {"id": "c2", "name": "SSI Schaefer IT Solutions GmbH"},
                },
            ],
        }
    }
}


def _parsed():
    return (
        aifind.parse_companies(COMPANIES_PAYLOAD),
        aifind.parse_managers(MANAGERS_PAYLOAD),
        aifind.parse_jobs(JOBS_PAYLOAD),
    )


# --- the pure parser: no network, no credentials ---------------------------


def test_padded_names_are_squeezed_not_concatenated() -> None:
    """'Stefan ' + 'Graf' must not become 'Stefan  Graf'.

    Naively joined, the same person arrives as a second manager on the next
    import whose only difference is a double space — a duplicate nobody can see.
    """
    managers = aifind.parse_managers(MANAGERS_PAYLOAD)
    assert managers[0].full_name == "Stefan Graf"


def test_a_person_without_a_name_is_not_imported() -> None:
    empty = {
        "data": {
            "managers": {"hits": [{"id": "x", "first_name": " ", "last_name": ""}]}
        }
    }
    assert aifind.parse_managers(empty) == []


def test_an_untitled_mandate_is_skipped() -> None:
    empty = {"data": {"jobs": {"hits": [{"id": "x", "title": "  "}]}}}
    assert aifind.parse_jobs(empty) == []


def test_jobs_carry_their_company_and_manager() -> None:
    jobs = aifind.parse_jobs(JOBS_PAYLOAD)
    assert [j.title for j in jobs] == [
        "Head of SAP",
        "Contract- & Claim Manager (w/m/d)",
    ]
    assert jobs[0].company.name == "Conrad Electronic SE"
    assert jobs[0].manager.full_name == "Stefan Graf"
    assert jobs[0].is_open is True
    assert jobs[1].is_open is False


# --- the import ------------------------------------------------------------


async def test_import_builds_the_company_manager_job_graph() -> None:
    companies, managers, jobs = _parsed()
    async with SessionLocal() as s:
        summary = await importer.import_aifind(
            s, tenant_id=TENANT, companies=companies, managers=managers, jobs=jobs
        )

    assert summary.companies_created == 2
    # m3 has no company and `managers.company_id` is NOT NULL — skipped, never
    # attached to an invented account.
    assert summary.managers_created == 2
    assert summary.jobs_created == 2

    async with SessionLocal() as s:
        job = await s.scalar(
            select(Job).where(Job.tenant_id == TENANT, Job.external_id == "j1")
        )
        manager = await s.get(Manager, job.manager_id)
        company = await s.get(Company, job.client_company_id)
    assert manager.full_name == "Stefan Graf"
    assert company.name == "Conrad Electronic SE"
    assert job.status == "open"


async def test_running_twice_updates_instead_of_duplicating() -> None:
    """THE property. Scheduled and non-idempotent means the book doubles nightly."""
    companies, managers, jobs = _parsed()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=managers, jobs=jobs
        )
    async with SessionLocal() as s:
        second = await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=managers, jobs=jobs
        )

    assert second.companies_created == 0
    assert second.managers_created == 0
    assert second.jobs_created == 0

    async with SessionLocal() as s:
        counts = {
            "companies": await s.scalar(
                select(func.count(Company.id)).where(Company.tenant_id == tenant)
            ),
            "managers": await s.scalar(
                select(func.count(Manager.id)).where(Manager.tenant_id == tenant)
            ),
            "jobs": await s.scalar(
                select(func.count(Job.id)).where(Job.tenant_id == tenant)
            ),
        }
    assert counts == {"companies": 2, "managers": 2, "jobs": 2}


async def test_a_manager_who_moved_company_follows_the_move() -> None:
    """The most valuable signal in recruiting BD, so it must not be ignored."""
    companies, managers, jobs = _parsed()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=managers, jobs=jobs
        )

    moved = aifind.parse_managers(
        {
            "data": {
                "managers": {
                    "hits": [
                        {
                            "id": "m1",
                            "first_name": "Stefan",
                            "last_name": "Graf",
                            "job_title": "CTO",
                            "company": {
                                "id": "c2",
                                "name": "SSI Schaefer IT Solutions GmbH",
                            },
                        }
                    ]
                }
            }
        }
    )
    async with SessionLocal() as s:
        summary = await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=moved, jobs=[]
        )
        row = await s.scalar(
            select(Manager).where(
                Manager.tenant_id == tenant, Manager.external_id == "m1"
            )
        )
        new_company = await s.get(Company, row.company_id)

    assert summary.managers_updated == 1
    assert new_company.name == "SSI Schaefer IT Solutions GmbH"
    assert row.role_title == "CTO"


async def test_imported_contacts_owe_no_art14_notice() -> None:
    """Moving the controller's own records between their own systems is not a
    new collection from a third party.

    Marking these as third-party-sourced would queue a notification for every
    person the recruiter already has a working relationship with. Recorded
    explicitly so the judgement is visible and can be reversed.
    """
    companies, managers, jobs = _parsed()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=managers, jobs=jobs
        )
        rows = list(
            await s.scalars(select(Manager).where(Manager.tenant_id == tenant))
        )

    assert rows
    for row in rows:
        assert row.source == ConfidenceSource.HUMAN_VERIFIED.value
        assert row.art14_outstanding is False
        assert row.source_detail.startswith("aifind:")


async def test_nothing_is_written_to_the_shared_corpus() -> None:
    """The boundary. A customer's book of business is not a public fact."""
    from app.domain.hub.models import HubCompany, HubJobPosting

    companies, managers, jobs = _parsed()
    async with SessionLocal() as s:
        before_companies = await s.scalar(select(func.count(HubCompany.id)))
        before_postings = await s.scalar(select(func.count(HubJobPosting.id)))
        await importer.import_aifind(
            s,
            tenant_id=uuid.uuid4(),
            companies=companies,
            managers=managers,
            jobs=jobs,
        )
        assert await s.scalar(select(func.count(HubCompany.id))) == before_companies
        assert await s.scalar(select(func.count(HubJobPosting.id))) == before_postings


async def test_another_workspace_sees_none_of_it() -> None:
    companies, managers, jobs = _parsed()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        await importer.import_aifind(
            s, tenant_id=mine, companies=companies, managers=managers, jobs=jobs
        )
        count = await s.scalar(
            select(func.count(Manager.id)).where(Manager.tenant_id == theirs)
        )
    assert count == 0
