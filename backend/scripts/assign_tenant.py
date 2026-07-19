"""Move the demo data from the default tenant into a real Clerk-org tenant.

The seed/repopulate scripts write under the default tenant
(00000000-…-0001). Once Clerk auth is on, you sign in and pick an organization
— that creates a `tenants` row on first API call. Run this to hand the existing
candidates (and their CVs, applications, receipts) to that organization so they
show up in your workspace:

    # after signing in once, with exactly one org so far:
    .venv/bin/python -m scripts.assign_tenant

    # or target a specific org explicitly:
    .venv/bin/python -m scripts.assign_tenant org_xxx

Everything else (a second org) stays empty — which is the isolation proof.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.documents.models import CandidateDocument
from app.domain.matching.models import MatchReceipt
from app.domain.pipeline.models import Application
from app.domain.tenants import service as tenants_service
from app.domain.tenants.models import Tenant
from app.domain.verification.models import EnrichmentRecord, Receipt

# Tenant-scoped tables to re-point.
_MODELS = [Candidate, CandidateDocument, Application, MatchReceipt, EnrichmentRecord, Receipt]


async def _resolve_target(clerk_org_id: str | None):
    async with SessionLocal() as s:
        if clerk_org_id:
            tenant = await tenants_service.get_or_create(s, clerk_org_id=clerk_org_id)
            await s.commit()
            return tenant.id, tenant.clerk_org_id
        rows = (await s.execute(select(Tenant))).scalars().all()
        if not rows:
            sys.exit("no organization tenants yet — sign in and select an org first, then re-run.")
        if len(rows) > 1:
            listing = ", ".join(f"{t.clerk_org_id} ({t.name or '—'})" for t in rows)
            sys.exit(f"multiple orgs exist — pass one explicitly. Found: {listing}")
        return rows[0].id, rows[0].clerk_org_id


async def main() -> None:
    clerk_org_id = sys.argv[1] if len(sys.argv) > 1 else None
    target_id, target_org = await _resolve_target(clerk_org_id)
    default = settings.default_tenant_id
    if target_id == default:
        sys.exit("target resolves to the default tenant — nothing to do.")

    print(f"moving default-tenant data → org {target_org} (tenant {target_id})")
    async with SessionLocal() as s:
        for model in _MODELS:
            result = await s.execute(
                update(model).where(model.tenant_id == default).values(tenant_id=target_id)
            )
            print(f"  {model.__tablename__:22} {result.rowcount} row(s)")
        await s.commit()
    print("done — refresh the app; the data now lives under your organization.")


if __name__ == "__main__":
    asyncio.run(main())
