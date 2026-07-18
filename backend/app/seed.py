"""Seed / mock data loader.

Run:  python -m app.seed

Creates a demo tenant's companies, jobs, candidates, and pipeline applications
so the frontend can point at a live API. Idempotent-ish: it wipes and reloads
the demo tenant's rows each run. Works against the configured database — SQLite
by default, or Supabase/Postgres when ELIGO_DATABASE_URL is set.

The dataset is intentionally spread across every pipeline stage — including
placed and rejected with transition history — so the reporting funnel and
stage-dwell figures are meaningful.
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
NOW = dt.datetime(2026, 7, 17, 12, 0, 0, tzinfo=dt.timezone.utc)

# The linear funnel path, used to synthesise plausible transition history.
_FUNNEL_PATH = [
    ApplicationStatus.SOURCED,
    ApplicationStatus.SCREENED,
    ApplicationStatus.PRESENTED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.PLACED,
]


def _history(reached: ApplicationStatus, *, rejected: bool = False) -> list[dict]:
    """Build a plausible transition history up to ``reached`` (+ rejection)."""
    idx = _FUNNEL_PATH.index(reached)
    entries: list[dict] = []
    for i in range(idx + 1):
        at = (NOW - dt.timedelta(days=30 - i * 5)).isoformat()
        if i == 0:
            entries.append({"at": at, "event": "created"})
        else:
            entries.append({"at": at, "event": "status", "to": _FUNNEL_PATH[i].value})
    if rejected:
        entries.append(
            {"at": NOW.isoformat(), "event": "status", "to": ApplicationStatus.REJECTED.value}
        )
    return entries


async def _wipe(session) -> None:
    for model in (Application, Job, Candidate, Company):
        await session.execute(delete(model).where(model.tenant_id == TENANT))


async def seed() -> None:
    await create_all()
    async with SessionLocal() as session:
        await _wipe(session)

        # -- Companies ----------------------------------------------------
        companies = {
            "acme": Company(
                tenant_id=TENANT, name="Acme Manufacturing GmbH", domain="acme.example",
                industry="Industrial", location="Munich", is_client=True,
            ),
            "trade": Company(
                tenant_id=TENANT, name="Trade Republic", domain="traderepublic.example",
                industry="FinTech", location="Berlin", is_client=True,
            ),
            "helio": Company(
                tenant_id=TENANT, name="Helio Solutions", domain="helio.example",
                industry="Energy", location="Hamburg", is_client=True,
            ),
        }
        session.add_all(companies.values())
        await session.flush()

        # -- Jobs ---------------------------------------------------------
        jobs = {
            "backend": Job(
                tenant_id=TENANT, title="Senior Backend Engineer",
                client_company_id=companies["acme"].id, location="Munich",
                location_radius_km=50, must_have_skills=["python", "postgresql", "fastapi"],
                requires_work_permit=True, salary_min=70000, salary_max=95000, status="open",
            ),
            "data": Job(
                tenant_id=TENANT, title="Data Platform Lead",
                client_company_id=companies["trade"].id, location="Berlin",
                must_have_skills=["python", "spark"], requires_work_permit=True,
                salary_min=90000, salary_max=120000, status="open",
            ),
            "finance": Job(
                tenant_id=TENANT, title="Finance Director",
                client_company_id=companies["trade"].id, location="Frankfurt",
                must_have_skills=["m&a", "valuation"], requires_work_permit=False,
                salary_min=120000, salary_max=180000, status="open",
            ),
            "frontend": Job(
                tenant_id=TENANT, title="Staff Frontend Engineer",
                client_company_id=companies["helio"].id, location="Remote",
                must_have_skills=["typescript", "react"], requires_work_permit=False,
                salary_min=85000, salary_max=115000, status="filled",
            ),
        }
        session.add_all(jobs.values())
        await session.flush()

        # -- Candidates (multi-entry work history) ------------------------
        candidates = {
            c["key"]: Candidate(
                tenant_id=TENANT, full_name=c["name"], email=c["email"], phone=c["phone"],
                current_title=c["title"], current_company=c["company"], location=c["location"],
                skills=c["skills"], work_history=c["work_history"],
                salary_expectation=c["salary"], availability_weeks=c["avail"],
                work_permit=c["permit"], verification_score=c["verify"],
            )
            for c in _candidate_specs()
        }
        session.add_all(candidates.values())
        await session.flush()

        # -- Applications (spread across the funnel) ----------------------
        # (candidate, job, status, stage, furthest-reached, rejected?, days-in-stage)
        plan = [
            ("alice", "backend", ApplicationStatus.PLACED, PipelineStage.PLACED, ApplicationStatus.PLACED, False, 2),
            ("carla", "backend", ApplicationStatus.INTERVIEW, PipelineStage.INTERVIEW, ApplicationStatus.INTERVIEW, False, 5),
            ("bob", "data", ApplicationStatus.SOURCED, PipelineStage.BEWERBUNG, ApplicationStatus.SOURCED, False, 10),
            ("dmitri", "data", ApplicationStatus.SCREENED, PipelineStage.LONG_LIST, ApplicationStatus.SCREENED, False, 7),
            ("elena", "data", ApplicationStatus.PRESENTED, PipelineStage.SHORT_LIST, ApplicationStatus.PRESENTED, False, 4),
            ("farah", "finance", ApplicationStatus.INTERVIEW, PipelineStage.INTERVIEW, ApplicationStatus.INTERVIEW, False, 6),
            ("georg", "finance", ApplicationStatus.PRESENTED, PipelineStage.SHORT_LIST, ApplicationStatus.PRESENTED, False, 3),
            ("hana", "finance", ApplicationStatus.SCREENED, PipelineStage.LONG_LIST, ApplicationStatus.SCREENED, False, 8),
            ("ivan", "finance", ApplicationStatus.SOURCED, PipelineStage.BEWERBUNG, ApplicationStatus.SOURCED, False, 12),
            ("julia", "frontend", ApplicationStatus.PLACED, PipelineStage.PLACED, ApplicationStatus.PLACED, False, 1),
            ("kwame", "frontend", ApplicationStatus.REJECTED, PipelineStage.REJECTED, ApplicationStatus.INTERVIEW, True, 9),
            ("lena", "backend", ApplicationStatus.REJECTED, PipelineStage.REJECTED, ApplicationStatus.SCREENED, True, 14),
            ("dmitri", "finance", ApplicationStatus.SOURCED, PipelineStage.BEWERBUNG, ApplicationStatus.SOURCED, False, 11),
            ("elena", "backend", ApplicationStatus.SCREENED, PipelineStage.LONG_LIST, ApplicationStatus.SCREENED, False, 6),
        ]
        apps = [
            Application(
                tenant_id=TENANT,
                candidate_id=candidates[ck].id,
                job_id=jobs[jk].id,
                status=status,
                stage=stage,
                history=_history(reached, rejected=rejected),
                updated_at=NOW - dt.timedelta(days=days),
            )
            for ck, jk, status, stage, reached, rejected, days in plan
        ]
        session.add_all(apps)

        await session.commit()
        print(
            f"Seeded tenant {TENANT}: {len(companies)} companies, {len(jobs)} jobs, "
            f"{len(candidates)} candidates, {len(apps)} applications."
        )


def _candidate_specs() -> list[dict]:
    """Twelve candidates with realistic, multi-role work histories."""
    P = WorkPermitStatus
    return [
        dict(key="alice", name="Alice Schneider", email="alice.schneider@example.com",
             phone="+49 170 0000001", title="Backend Engineer", company="Zeta Software",
             location="Munich", skills=["python", "postgresql", "fastapi", "docker"],
             work_history=[{"company": "Zeta Software", "title": "Backend Engineer", "years": 4},
                           {"company": "Init GmbH", "title": "Junior Developer", "years": 2}],
             salary=88000, avail=6, permit=P.CITIZEN, verify=0.92),
        dict(key="bob", name="Bob Meier", email="bob.meier@example.com",
             phone="+49 170 0000002", title="Software Engineer", company="Helios AG",
             location="Hamburg", skills=["python", "django"],
             work_history=[{"company": "Helios AG", "title": "Software Engineer", "years": 3}],
             salary=99000, avail=12, permit=P.PERMANENT, verify=0.55),
        dict(key="carla", name="Carla Duarte", email="carla.duarte@example.com",
             phone="+49 170 0000003", title="Senior Python Engineer", company="NimbusData",
             location="Munich", skills=["python", "postgresql", "fastapi", "spark", "kubernetes"],
             work_history=[{"company": "NimbusData", "title": "Senior Python Engineer", "years": 3},
                           {"company": "DataForge", "title": "Data Engineer", "years": 3},
                           {"company": "StartUp X", "title": "Developer", "years": 2}],
             salary=90000, avail=4, permit=P.WORK_VISA, verify=0.9),
        dict(key="dmitri", name="Dmitri Volkov", email="dmitri.volkov@example.com",
             phone="+49 170 0000004", title="Data Engineer", company="Skyline Data",
             location="Berlin", skills=["python", "spark", "airflow", "sql"],
             work_history=[{"company": "Skyline Data", "title": "Data Engineer", "years": 5},
                           {"company": "BI Corp", "title": "Analyst", "years": 2}],
             salary=95000, avail=8, permit=P.CITIZEN, verify=0.87),
        dict(key="elena", name="Elena Rossi", email="elena.rossi@example.com",
             phone="+39 320 0000005", title="Staff Data Engineer", company="Aqua Systems",
             location="Berlin", skills=["python", "spark", "scala", "postgresql"],
             work_history=[{"company": "Aqua Systems", "title": "Staff Data Engineer", "years": 4},
                           {"company": "Metrica", "title": "Data Engineer", "years": 3}],
             salary=105000, avail=10, permit=P.PERMANENT, verify=0.94),
        dict(key="farah", name="Farah Haddad", email="farah.haddad@example.com",
             phone="+49 170 0000006", title="Head of Corporate Finance", company="Vellum Capital",
             location="Frankfurt", skills=["m&a", "valuation", "risk", "modelling"],
             work_history=[{"company": "Vellum Capital", "title": "Head of Corp. Finance", "years": 6},
                           {"company": "Rothschild & Co", "title": "Associate", "years": 4}],
             salary=160000, avail=12, permit=P.CITIZEN, verify=0.96),
        dict(key="georg", name="Georg Bauer", email="georg.bauer@example.com",
             phone="+49 170 0000007", title="Finance Director", company="Meridian AG",
             location="Frankfurt", skills=["m&a", "valuation", "controlling"],
             work_history=[{"company": "Meridian AG", "title": "Finance Director", "years": 5},
                           {"company": "KPMG", "title": "Manager", "years": 5}],
             salary=155000, avail=16, permit=P.CITIZEN, verify=0.89),
        dict(key="hana", name="Hana Kovač", email="hana.kovac@example.com",
             phone="+385 91 0000008", title="Senior FP&A Manager", company="Lumen Group",
             location="Frankfurt", skills=["valuation", "modelling", "controlling"],
             work_history=[{"company": "Lumen Group", "title": "Senior FP&A Manager", "years": 4}],
             salary=120000, avail=8, permit=P.WORK_VISA, verify=0.78),
        dict(key="ivan", name="Ivan Petrov", email="ivan.petrov@example.com",
             phone="+49 170 0000009", title="M&A Analyst", company="Brant & Co",
             location="Frankfurt", skills=["m&a", "modelling"],
             work_history=[{"company": "Brant & Co", "title": "M&A Analyst", "years": 3}],
             salary=110000, avail=6, permit=P.REQUIRES_SPONSORSHIP, verify=0.62),
        dict(key="julia", name="Julia Fischer", email="julia.fischer@example.com",
             phone="+49 170 0000010", title="Staff Frontend Engineer", company="Pixelworks",
             location="Remote", skills=["typescript", "react", "graphql", "vite"],
             work_history=[{"company": "Pixelworks", "title": "Staff Frontend Engineer", "years": 4},
                           {"company": "WebLab", "title": "Frontend Engineer", "years": 3}],
             salary=108000, avail=4, permit=P.CITIZEN, verify=0.91),
        dict(key="kwame", name="Kwame Osei", email="kwame.osei@example.com",
             phone="+44 7700 000011", title="Senior Frontend Engineer", company="Northwind",
             location="London", skills=["typescript", "react", "next.js"],
             work_history=[{"company": "Northwind", "title": "Senior Frontend Engineer", "years": 4},
                           {"company": "Cloudy", "title": "Developer", "years": 2}],
             salary=98000, avail=10, permit=P.WORK_VISA, verify=0.83),
        dict(key="lena", name="Lena Novak", email="lena.novak@example.com",
             phone="+49 170 0000012", title="Backend Developer", company="Grid Labs",
             location="Cologne", skills=["python", "flask"],
             work_history=[{"company": "Grid Labs", "title": "Backend Developer", "years": 2}],
             salary=91000, avail=14, permit=P.PERMANENT, verify=0.5),
    ]


if __name__ == "__main__":
    asyncio.run(seed())