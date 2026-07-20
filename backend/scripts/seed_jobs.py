"""Seed a set of realistic open jobs (+ their companies) for the demo.

Loads into the single existing org tenant (or a passed clerk_org_id), so Matching
has real roles to rank the candidate pool against. Idempotent-ish: it wipes
existing jobs/companies for that tenant first, then re-creates.

    .venv/bin/python -m scripts.seed_jobs [clerk_org_id]

Titles/companies are drawn from public Munich AI/ML postings. `requires_work_permit`
is False (the demo candidates have unknown permit) and `location_radius_km` is None,
so the hard filters gate on must-have skills — which is what makes the ranking
visibly differ per role.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import AdminSessionLocal as SessionLocal
from app.core.database import current_tenant_var
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.tenants.models import Tenant

# (title, company, location, must_have_skills, salary_min, salary_max)
JOBS = [
    ("Senior Software Engineer, Applied AI", "NVIDIA", "Munich", ["Python"], None, None),
    ("Senior Agentic AI Engineer (f/m/x)", "BMW Group", "Munich", ["Python"], 90000, 130000),
    ("Team Lead Machine Learning (m/f/x)", "osapiens", "Munich", ["Python"], None, None),
    ("Senior GenAI Architect (m/w/d)", "in-tech GmbH", "Munich", ["Python"], None, None),
    ("Senior Research Engineer (Code World Models)", "JetBrains", "Munich", ["Python"], None, None),
    ("Lead Engineer - Applied AI & Data Products", "SQUER", "Munich", ["TypeScript"], None, None),
    ("AI Tech Lead (Fullstack)", "Headmatch", "Munich", ["TypeScript"], 100000, 160000),
    ("Staff Software Engineer - AI", "Personio", "Munich", ["Python"], None, None),
    ("Software Engineer III, AI/ML", "Google", "Munich", ["Python"], None, None),
    ("Manager, AI Deployment Engineering - Codex", "OpenAI", "Munich", ["Python"], None, None),
    ("Deployed AI Engineer", "Helsing", "Munich", ["Python"], None, None),
    ("Senior AI Platform & MLOps Engineer", "Amoria Bond", "Munich", ["AWS"], None, None),
]


async def _resolve_tenant():
    async with SessionLocal() as s:
        if len(sys.argv) > 1:
            from app.domain.tenants import service as tenants_service
            t = await tenants_service.get_or_create(s, clerk_org_id=sys.argv[1])
            return t.id
        rows = (await s.execute(select(Tenant))).scalars().all()
        if len(rows) == 1:
            return rows[0].id
        if len(rows) > 1:
            sys.exit("multiple org tenants — pass a clerk_org_id explicitly.")
        return settings.default_tenant_id


async def main() -> None:
    tenant_id = await _resolve_tenant()
    current_tenant_var.set(str(tenant_id))  # RLS scope

    async with SessionLocal() as s:
        # fresh: drop this tenant's jobs + companies
        await s.execute(delete(Job))
        await s.execute(delete(Company))
        await s.commit()

        companies: dict[str, Company] = {}
        for _, name, loc, *_ in JOBS:
            if name not in companies:
                companies[name] = Company(tenant_id=tenant_id, name=name, location=loc, is_client=True)
                s.add(companies[name])
        await s.flush()

        for title, name, loc, skills, smin, smax in JOBS:
            s.add(Job(
                tenant_id=tenant_id,
                title=title,
                client_company_id=companies[name].id,
                location=loc,
                location_radius_km=None,          # no location exclusion in the demo
                must_have_skills=skills,
                required_certifications=[],
                requires_work_permit=False,       # demo candidates have unknown permit
                salary_min=smin,
                salary_max=smax,
                status="open",
            ))
        await s.commit()

        n_jobs = await s.scalar(select(func.count()).select_from(Job))
        n_co = await s.scalar(select(func.count()).select_from(Company))
    print(f"seeded {n_jobs} jobs across {n_co} companies for tenant {tenant_id}")


if __name__ == "__main__":
    asyncio.run(main())
