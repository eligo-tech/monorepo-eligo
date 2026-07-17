"""Seed / mock data loader.

Run:  python -m app.seed

Creates a demo tenant's companies, jobs, candidates, and pipeline applications
so the frontend can point at a live API. Idempotent-ish: it wipes and reloads
the demo tenant's rows each run.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import delete

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.common.enums import (
    ApplicationStatus,
    PipelineStage,
    WorkPermitStatus,
)
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.pipeline.models import Application

TENANT = settings.default_tenant_id


async def _wipe(session) -> None:
    for model in (Application, Job, Candidate, Company):
        await session.execute(delete(model).where(model.tenant_id == TENANT))


async def seed() -> None:
    await create_all()
    async with SessionLocal() as session:
        await _wipe(session)

        acme = Company(
            tenant_id=TENANT,
            name="Acme Manufacturing GmbH",
            domain="acme.example",
            industry="Industrial",
            location="Munich",
            is_client=True,
        )
        session.add(acme)
        await session.flush()

        job = Job(
            tenant_id=TENANT,
            title="Senior Backend Engineer",
            client_company_id=acme.id,
            location="Munich",
            location_radius_km=50,
            must_have_skills=["python", "postgresql", "fastapi"],
            required_certifications=[],
            requires_work_permit=True,
            salary_min=70000,
            salary_max=95000,
            salary_currency="EUR",
            status="open",
        )
        job2 = Job(
            tenant_id=TENANT,
            title="Data Platform Lead",
            client_company_id=acme.id,
            location="Berlin",
            location_radius_km=None,
            must_have_skills=["python", "spark"],
            required_certifications=[],
            requires_work_permit=True,
            salary_min=90000,
            salary_max=120000,
        )
        session.add_all([job, job2])
        await session.flush()

        alice = Candidate(
            tenant_id=TENANT,
            full_name="Alice Schneider",
            email="alice.schneider@example.com",
            phone="+49 170 0000001",
            current_title="Backend Engineer",
            current_company="Zeta Software",
            location="Munich",
            skills=["python", "postgresql", "fastapi", "docker"],
            work_history=[{"company": "Zeta Software", "years": 4}],
            salary_expectation=88000,
            availability_weeks=6,
            work_permit=WorkPermitStatus.CITIZEN,
            verification_score=0.8,
        )
        bob = Candidate(
            tenant_id=TENANT,
            full_name="Bob Meier",
            email="bob.meier@example.com",
            phone="+49 170 0000002",
            current_title="Software Engineer",
            current_company="Helios AG",
            location="Hamburg",
            skills=["python", "django"],
            salary_expectation=99000,  # exceeds job1 cap -> filtered
            availability_weeks=12,
            work_permit=WorkPermitStatus.PERMANENT,
            verification_score=0.5,
        )
        carla = Candidate(
            tenant_id=TENANT,
            full_name="Carla Duarte",
            email="carla.duarte@example.com",
            phone="+49 170 0000003",
            current_title="Senior Python Engineer",
            current_company="NimbusData",
            location="Munich",
            skills=["python", "postgresql", "fastapi", "spark", "kubernetes"],
            salary_expectation=90000,
            availability_weeks=4,
            work_permit=WorkPermitStatus.WORK_VISA,
            verification_score=0.9,
        )
        session.add_all([alice, bob, carla])
        await session.flush()

        now = dt.datetime.now(dt.timezone.utc).isoformat()
        session.add_all(
            [
                Application(
                    tenant_id=TENANT,
                    candidate_id=alice.id,
                    job_id=job.id,
                    status=ApplicationStatus.SCREENED,
                    stage=PipelineStage.SHORT_LIST,
                    history=[{"at": now, "event": "created"}],
                ),
                Application(
                    tenant_id=TENANT,
                    candidate_id=carla.id,
                    job_id=job.id,
                    status=ApplicationStatus.SOURCED,
                    stage=PipelineStage.LONG_LIST,
                    history=[{"at": now, "event": "created"}],
                ),
                Application(
                    tenant_id=TENANT,
                    candidate_id=bob.id,
                    job_id=job2.id,
                    status=ApplicationStatus.SOURCED,
                    stage=PipelineStage.BEWERBUNG,
                    history=[{"at": now, "event": "created"}],
                ),
            ]
        )

        await session.commit()
        print(f"Seeded tenant {TENANT}: 1 company, 2 jobs, 3 candidates, "
              f"3 applications.")


if __name__ == "__main__":
    asyncio.run(seed())