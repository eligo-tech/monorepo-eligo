#!/usr/bin/env python
"""Play out `data/examples/KandidatenInfo.txt` as a real mandate.

The document is one anonymised evaluation: a senior backend candidate against
"Senior Backend-Entwickler mit Architekturkenntnissen (Position 1) – GE
Software". Everything it contains — the Suchprofil, the person's
qualification data, the 8/10 assessment — exists in the record as fields
already; nothing of it was in the database, so there was nothing to click.

This creates exactly that: the client, the mandate, the (anonymous)
candidate, their process, and the Kandidatenauswertung. Then Jobs → the job
title → the cockpit's per-job view shows the whole thing.

    python -m scripts.seed_ge_example --tenant <uuid> [--dry-run] [--remove]

Idempotent: matched by name per tenant, so a re-run updates rather than
doubling. `--remove` deletes what it created, because a demo mandate you
cannot take out again is not a demo.

Two values are DERIVED rather than quoted, and both are flagged in the
output: the salary band (the document says the GE orientation is "~90k plus
minus" and that the Budgetrahmen is "nicht angegeben"), and the presentation
date (the Qualifikationsgespräch was 18.09.2026 and the document expects
client feedback "bis ~Dienstag", so the candidate is presented). Change both
in the Mandat editor if they are wrong.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import pathlib
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal, current_tenant_var
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus, EmploymentForm
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.pipeline import service as pipeline_service
from app.domain.pipeline.models import Application
from app.domain.registry import *  # noqa: F401,F403 — register every table
from scripts.import_assessment import parse_assessment

COMPANY = "GE Software"
JOB_TITLE = "Senior Backend-Entwickler mit Architekturkenntnissen (Position 1)"
#: The document is anonymised; the record says so rather than inventing a name.
CANDIDATE = "Senior Backend-Entwickler (anonymisiert)"

EXAMPLE = pathlib.Path(__file__).resolve().parents[2] / "data/examples/KandidatenInfo.txt"

#: Section D of the document, verbatim — the mandate's hard criteria.
MUST_HAVE = [
    "Java", "Jakarta EE/J2EE", "WildFly", "JBoss", "JPA/Hibernate", "REST",
    "Flyway/Liquibase", "GitLab CI/CD", "Oracle/PostgreSQL",
    "Microservices-Architektur",
]

#: Section B, "Technisches Know-how".
SKILLS = [
    "Java", "J2EE/Jakarta EE", "WildFly", "JBoss", "Weblogic", "GlassFish",
    "Tomcat", "Quarkus", "Spring Boot", "Hibernate", "JPA", "JSF", "React",
    "Angular", "TypeScript", "Oracle", "MySQL", "PostgreSQL", "Cassandra",
    "Elasticsearch", "Kafka", "Flyway/Liquibase", "GitLab CI/CD", "Docker",
    "Kubernetes", "Maven", "Git",
]

CANDIDATE_FIELDS = {
    "current_title": "Senior Software Entwickler / Software Architekt",
    "location": "Süddeutschland",
    "total_years_experience": "20+",
    "employment_form": EmploymentForm.FESTANSTELLUNG.value,
    "industries": ["Luftfahrt / Flugsicherung", "Behörden & Verteidigung"],
    "languages": ["Deutsch (Muttersprache)", "Englisch (verhandlungssicher)"],
    "education": [
        "Fachinformatiker Anwendungsentwicklung (IHK)",
        "Zertifizierter Enterprise Architect",
        "JBoss Certified Application Administrator",
        "Certified Java Programmer",
    ],
    "skills": SKILLS,
    "current_salary": 105000,
    "salary_minimum": 92000,
    "salary_expectation": 100000,
    "notice_period": "3 Monate zum Monatsende → Start ~Jahresanfang",
    "availability": "ab ~Jahresanfang",
    "interview_availability": "Mittwoch/Donnerstag ab ca. 11–12 Uhr, bis max. 18 Uhr",
    "other_processes": "Führt parallel mehrere Prozesse und Freelance-Optionen",
    "source": "kandidatenauswertung",
}

#: Derived, not quoted — see the module docstring.
SALARY_MIN, SALARY_MAX = 85000, 95000
PRESENTED_AT = dt.datetime(2026, 9, 18, tzinfo=dt.UTC)


async def _one(session, model, **where):
    return await session.scalar(select(model).filter_by(**where))


async def seed(tenant_id: uuid.UUID) -> dict:
    current_tenant_var.set(str(tenant_id))
    async with SessionLocal() as s:
        company = await _one(s, Company, tenant_id=tenant_id, name=COMPANY)
        if company is None:
            company = Company(
                tenant_id=tenant_id, name=COMPANY, is_client=True,
                source="kandidatenauswertung",
            )
            s.add(company)
            await s.flush()

        job = await _one(s, Job, tenant_id=tenant_id, title=JOB_TITLE)
        if job is None:
            job = Job(tenant_id=tenant_id, title=JOB_TITLE)
            s.add(job)
        job.client_company_id = company.id
        job.location = "München"
        job.must_have_skills = MUST_HAVE
        job.salary_min, job.salary_max = SALARY_MIN, SALARY_MAX
        job.salary_currency = "EUR"
        job.status = "open"
        await s.flush()

        candidate = await _one(s, Candidate, tenant_id=tenant_id, full_name=CANDIDATE)
        if candidate is None:
            candidate = Candidate(tenant_id=tenant_id, full_name=CANDIDATE)
            s.add(candidate)
        for field, value in CANDIDATE_FIELDS.items():
            setattr(candidate, field, value)
        await s.flush()

        application = await _one(
            s, Application, tenant_id=tenant_id,
            candidate_id=candidate.id, job_id=job.id,
        )
        if application is None:
            application = Application(
                tenant_id=tenant_id, candidate_id=candidate.id, job_id=job.id,
                status=ApplicationStatus.PRESENTED,
            )
            s.add(application)
        await s.commit()
        app_id, job_id = application.id, job.id

        # Section B's profile summary belongs on the person, not the mandate.
        parsed = parse_assessment(EXAMPLE.read_text(encoding="utf-8"))
        for field, value in parsed["candidate"].items():
            setattr(candidate, field, value)
        await s.commit()

        await pipeline_service.set_step(
            s, tenant_id=tenant_id, application_id=app_id,
            step_key="vorgestellt", done_at=PRESENTED_AT, outcome="pass",
            actor="seed_ge_example",
        )
        await pipeline_service.set_assessment(
            s, tenant_id=tenant_id, application_id=app_id, **parsed["assessment"]
        )

    return {
        "job_id": str(job_id),
        "application": str(app_id),
        "fit_score": parsed["assessment"]["fit_score"],
        "strengths": len(parsed["assessment"]["strengths"]),
        "risks": len(parsed["assessment"]["risks"]),
    }


async def remove(tenant_id: uuid.UUID) -> dict:
    """Take it out again — rows first, then the client."""
    current_tenant_var.set(str(tenant_id))
    removed = {"applications": 0, "jobs": 0, "candidates": 0, "companies": 0}
    async with SessionLocal() as s:
        job = await _one(s, Job, tenant_id=tenant_id, title=JOB_TITLE)
        candidate = await _one(s, Candidate, tenant_id=tenant_id, full_name=CANDIDATE)
        if job is not None:
            apps = (
                await s.execute(
                    select(Application).where(
                        Application.tenant_id == tenant_id,
                        Application.job_id == job.id,
                    )
                )
            ).scalars().all()
            for application in apps:
                await s.delete(application)  # steps + assessment cascade
                removed["applications"] += 1
            await s.flush()
            await s.delete(job)
            removed["jobs"] += 1
        if candidate is not None:
            await s.delete(candidate)
            removed["candidates"] += 1
        company = await _one(s, Company, tenant_id=tenant_id, name=COMPANY)
        if company is not None:
            await s.delete(company)
            removed["companies"] += 1
        await s.commit()
    return removed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", type=uuid.UUID, required=True)
    ap.add_argument("--remove", action="store_true", help="delete what this created")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not EXAMPLE.exists():
        raise SystemExit(f"{EXAMPLE} not found")

    if args.dry_run:
        parsed = parse_assessment(EXAMPLE.read_text(encoding="utf-8"))
        print(f"würde anlegen: {COMPANY} · {JOB_TITLE}")
        print(f"  Kandidat: {CANDIDATE}")
        print(f"  Muss-Kriterien: {', '.join(MUST_HAVE)}")
        print(f"  Band: {SALARY_MIN}–{SALARY_MAX} € (abgeleitet aus „~90k plus minus“)")
        print(f"  Bewertung: {parsed['assessment']['fit_score']}/10, "
              f"{len(parsed['assessment']['strengths'])} Stärken, "
              f"{len(parsed['assessment']['risks'])} Risiken")
        return

    if args.remove:
        print("entfernt:", asyncio.run(remove(args.tenant)))
        return

    result = asyncio.run(seed(args.tenant))
    print("angelegt:", result)
    print(f"  → Cockpit: #cockpit/{result['job_id']}")


if __name__ == "__main__":
    main()
