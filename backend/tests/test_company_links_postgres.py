"""Linking every workspace's companies to Markt, on Postgres, as the runtime
role, under RLS (ELI-33).

The first production run linked 1 company in 1 workspace instead of ~84 in
each: the operator request pins the session to the ingest token's workspace,
so the query listing "every workspace's companies" saw only that one. SQLite
has no RLS, so only this file can show it. Skipped unless Postgres.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, admin_engine, current_tenant_var, engine
from app.domain.companies import market
from app.domain.companies.models import Company
from app.domain.hub.models import EMPLOYER, HubCompany, HubCompanyLink
from app.domain.hub.resolution import normalize_company_name
from app.domain.managers.models import Manager
from app.domain.tenants.models import Tenant

pytestmark = pytest.mark.skipif(not settings.is_postgres, reason="Postgres only")
NOW = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Overrides conftest: the app role may not drop tables; rows are unique per run."""
    yield
    await engine.dispose()
    await admin_engine.dispose()


@contextlib.contextmanager
def _as(tenant: uuid.UUID | None):
    token = current_tenant_var.set(str(tenant) if tenant else None)
    try:
        yield
    finally:
        current_tenant_var.reset(token)


async def _workspace(name: str) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = uuid.uuid4()
    with _as(None):
        async with SessionLocal() as s:
            s.add(Tenant(id=tenant, clerk_org_id=f"org_{tenant.hex}", name=name))
            await s.commit()
    with _as(tenant):
        async with SessionLocal() as s:
            c = Company(tenant_id=tenant, name="uniVersa Versicherungen", source="aifind")
            s.add(c)
            await s.flush()
            s.add(Manager(tenant_id=tenant, company_id=c.id, stage="manager", full_name="Max Mustermann", city="Nürnberg"))
            await s.commit()
            return tenant, c.id


async def test_every_workspace_is_linked_although_the_request_is_pinned_to_one() -> None:
    a, a_company = await _workspace("A")
    b, b_company = await _workspace("B")
    with _as(a):
        async with SessionLocal() as s:
            s.add(HubCompany(
                name="uniVersa Versicherungen", normalized_name=normalize_company_name("uniVersa Versicherungen"), dedupe_key=f"k-{uuid.uuid4()}",
                resolution_basis="name_place", city="Nürnberg", source="bundesagentur", kind=EMPLOYER,
                first_seen_at=NOW, last_seen_at=NOW,
            ))
            await s.commit()
        # As the operator request runs: pinned to the ingest token's workspace.
        result = await market.link_all_workspaces()
        # The pin is the caller's again afterwards.
        assert current_tenant_var.get() == str(a)
    assert result["tenants"] >= 2 and result["linked"] >= 2
    for tenant, company in ((a, a_company), (b, b_company)):
        with _as(tenant):
            async with SessionLocal() as s:
                linked = (await s.scalars(select(HubCompanyLink).where(HubCompanyLink.company_id == company))).all()
        assert len(linked) == 1, tenant


async def test_impressum_totals_count_markt_readings_in_every_workspace_under_rls() -> None:
    """"0 aus Markt" (2026-11-17): the totals read `hub_company_link` (tenant
    table) and `hub_site_checks` (shared corpus) once per workspace, under
    RLS, from a request pinned to the ingest token's workspace. A linked
    company whose Markt employer has a verified Impressum with a VAT id
    counts as "aus Markt" in every workspace, not only the pinned one."""
    from app.domain.companies import impressum
    from app.domain.hub.models import HubSiteCheck

    a, a_company = await _workspace("A")
    b, b_company = await _workspace("B")
    for tenant, company in ((a, a_company), (b, b_company)):
        with _as(tenant):
            async with SessionLocal() as s:
                # A name no workspace company has: the linking test must not
                # find this row (the link here is set by hand).
                name = f"Totals {uuid.uuid4().hex} GmbH"
                hub = HubCompany(
                    name=name, normalized_name=normalize_company_name(name),
                    dedupe_key=f"k-{uuid.uuid4()}", resolution_basis="name_place", city="Nürnberg",
                    source="bundesagentur", kind=EMPLOYER, first_seen_at=NOW, last_seen_at=NOW,
                )
                s.add(hub)
                await s.flush()
                s.add(HubSiteCheck(
                    domain=f"{uuid.uuid4().hex}.de", group_key=f"employer:{hub.id}", hub_company_id=hub.id,
                    status="verified", facts={"vat_id": "DE123456789"}, checked_at=NOW,
                ))
                s.add(HubCompanyLink(tenant_id=tenant, hub_company_id=hub.id, company_id=company))
                await s.commit()
    for tenant in (a, b):
        with _as(tenant):
            async with SessionLocal() as s:
                t = await impressum.totals(s, tenant_id=tenant)
        assert (t["linked"], t["linked_checked"], t["linked_reading"], t["markt"]) == (1, 1, 1, 1), tenant
    with _as(a):  # as the operator request runs: pinned to one workspace
        total = await impressum.totals_all_workspaces()
        assert current_tenant_var.get() == str(a)
    assert total["markt"] >= 2 and total["linked"] >= 2


async def test_markt_queue_sees_every_workspaces_adopted_employers_under_rls() -> None:
    """2026-11-18: the employer Impressum check orders linked employers first.
    The operator request is pinned to one workspace; `hub_company_link` is
    tenant-scoped, so a single pinned query would see only that one's links."""
    from app.domain.hub import employer_sites

    a, a_company = await _workspace("A")
    b, b_company = await _workspace("B")
    hubs = {}
    for tenant, company in ((a, a_company), (b, b_company)):
        with _as(tenant):
            async with SessionLocal() as s:
                name = f"Queue {uuid.uuid4().hex} GmbH"
                hub = HubCompany(
                    name=name, normalized_name=normalize_company_name(name),
                    dedupe_key=f"k-{uuid.uuid4()}", resolution_basis="name_place", city="Nürnberg",
                    source="bundesagentur", kind=EMPLOYER, first_seen_at=NOW, last_seen_at=NOW,
                )
                s.add(hub)
                await s.flush()
                s.add(HubCompanyLink(tenant_id=tenant, hub_company_id=hub.id, company_id=company))
                await s.commit()
                hubs[tenant] = hub.id
    with _as(a):  # as the operator request runs: pinned to one workspace
        linked = await employer_sites.linked_employers()
        assert current_tenant_var.get() == str(a)
    assert {hubs[a], hubs[b]} <= linked
