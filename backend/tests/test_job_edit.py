"""Editing a mandate — the Suchprofil, with a receipt.

A mandate's band and radius are not display fields: `apply_hard_filters`
excludes candidates on them. Widening a cap changes who a client is shown, so
the edit path is the verified one, and the numbers are checked against the
row that will exist rather than the payload that arrived.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.companies.models import Company
from app.domain.jobs import service
from app.domain.jobs.models import Job
from app.domain.jobs.schemas import JobCreate, JobUpdate
from app.domain.verification.models import EnrichmentRecord, Receipt

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
API = "/api/v1/jobs"


@pytest.fixture
async def job() -> uuid.UUID:
    async with SessionLocal() as s:
        row = await service.create_job(
            s,
            data=JobCreate(
                tenant_id=TENANT, title="Java Dev", salary_min=None, salary_max=None
            ),
        )
        return row.id


async def test_setting_a_band_is_recorded_as_a_verified_change(job) -> None:
    async with SessionLocal() as s:
        updated = await service.update_job(
            s,
            tenant_id=TENANT,
            job_id=job,
            patch=JobUpdate(salary_min=85000, salary_max=95000),
            editor="dimafadeev",
        )
    assert (updated.salary_min, updated.salary_max) == (85000, 95000)

    async with SessionLocal() as s:
        receipts = (
            await s.execute(select(Receipt).where(Receipt.tenant_id == TENANT))
        ).scalars().all()
        records = (
            await s.execute(
                select(EnrichmentRecord).where(
                    EnrichmentRecord.entity_type == "job",
                    EnrichmentRecord.entity_id == job,
                )
            )
        ).scalars().all()

    # The trail answers "who moved the cap, to what, and when".
    assert receipts, "a cap moved without leaving a receipt"
    assert {r.subject_type for r in receipts} == {"job"}
    changed = {record.field: record.proposed_value for record in records}
    assert changed == {"salary_min": "85000", "salary_max": "95000"}
    assert all(record.source == "human_verified" for record in records)
    assert all("dimafadeev" in (record.source_detail or "") for record in records)


async def test_a_floor_above_the_ceiling_is_refused(job) -> None:
    async with SessionLocal() as s:
        with pytest.raises(service.InvalidBand):
            await service.update_job(
                s,
                tenant_id=TENANT,
                job_id=job,
                patch=JobUpdate(salary_min=100000, salary_max=90000),
            )


async def test_the_band_is_checked_against_the_resulting_row(job) -> None:
    """Sending only the floor must still be measured against the stored
    ceiling — otherwise a two-step edit walks past the check."""
    async with SessionLocal() as s:
        await service.update_job(
            s, tenant_id=TENANT, job_id=job, patch=JobUpdate(salary_max=90000)
        )
    async with SessionLocal() as s:
        with pytest.raises(service.InvalidBand):
            await service.update_job(
                s, tenant_id=TENANT, job_id=job, patch=JobUpdate(salary_min=100000)
            )


async def test_an_unknown_status_is_refused(job) -> None:
    async with SessionLocal() as s:
        with pytest.raises(service.InvalidBand):
            await service.update_job(
                s, tenant_id=TENANT, job_id=job, patch=JobUpdate(status="vielleicht")
            )


async def test_a_mandate_of_another_tenant_is_invisible(job) -> None:
    async with SessionLocal() as s:
        assert (
            await service.update_job(
                s, tenant_id=OTHER, job_id=job, patch=JobUpdate(salary_max=1)
            )
            is None
        )


async def test_the_client_company_can_be_assigned(job) -> None:
    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name="EM Software", is_client=True)
        s.add(company)
        await s.commit()
        company_id = company.id

    async with SessionLocal() as s:
        updated = await service.update_job(
            s,
            tenant_id=TENANT,
            job_id=job,
            patch=JobUpdate(client_company_id=company_id),
        )
    # Arrives as a string through `model_dump(mode="json")`; the column is a
    # uuid, and SQLite will happily store the string and hand back a mismatch.
    assert updated.client_company_id == company_id
    async with SessionLocal() as s:
        stored = await s.get(Job, job)
    assert stored.client_company_id == company_id


async def test_a_required_field_cannot_be_emptied(job) -> None:
    async with SessionLocal() as s:
        updated = await service.update_job(
            s, tenant_id=TENANT, job_id=job, patch=JobUpdate(title="   ")
        )
    assert updated.title == "Java Dev"


async def test_routes(job) -> None:
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        ok = await client.patch(
            f"{API}/{job}?editor=tester",
            json={"salary_min": 85000, "salary_max": 95000, "location": "München"},
        )
        assert ok.status_code == 200
        assert ok.json()["salary_max"] == 95000 and ok.json()["location"] == "München"

        bad = await client.patch(
            f"{API}/{job}", json={"salary_min": 120000, "salary_max": 90000}
        )
        assert bad.status_code == 422

        missing = await client.patch(f"{API}/{uuid.uuid4()}", json={"status": "open"})
        assert missing.status_code == 404
