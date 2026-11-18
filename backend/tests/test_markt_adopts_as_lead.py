"""ELI-36: "Übernehmen" on a Markt card makes the company a Lead, not a client.

Adopting a public employer is interest turned into a record — a prospect.
A company becomes a client by winning a mandate, never by being picked from
the market. Migration 0075 resets the companies adopted before the fix that
have no mandate yet.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import uuid

import pytest
from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.domain.companies.models import Company
from app.domain.hub import service
from app.domain.hub.models import HubCompany, HubCompanyLink
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager

TENANT = uuid.uuid4()


async def _corpus(name: str) -> uuid.UUID:
    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        row = HubCompany(
            name=name,
            normalized_name=name.lower(),
            dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place",
            city="Berlin",
            source="bundesagentur",
            first_seen_at=now,
            last_seen_at=now,
        )
        s.add(row)
        await s.commit()
        return row.id


@pytest.fixture
async def corpus_company() -> uuid.UUID:
    return await _corpus("Bayoonet AG")


async def test_the_markt_adopt_route_creates_a_lead_not_a_client(corpus_company) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.auth import get_current_tenant
    from app.core.config import settings
    from app.main import app

    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"{settings.api_v1_prefix}/hub/companies/{corpus_company}/adopt", json={"manager": None}
            )
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)
    assert resp.status_code == 201, resp.text

    async with SessionLocal() as s:
        company = await s.get(Company, uuid.UUID(resp.json()["company_id"]))
        link = await s.scalar(select(HubCompanyLink).where(HubCompanyLink.company_id == company.id))
    assert company.is_client is False
    assert link.relationship == "prospect"


async def test_adoption_defaults_to_prospect(corpus_company) -> None:
    """Every caller that does not say otherwise gets a lead — being picked
    from the market is never what makes a company a client."""
    async with SessionLocal() as s:
        company, link, _ = await service.adopt_company(s, tenant_id=TENANT, hub_company_id=corpus_company)
    assert company.is_client is False
    assert link.relationship == "prospect"


# --- the data fix ---------------------------------------------------------


def _migration():
    path = pathlib.Path(__file__).resolve().parents[1] / "migrations/versions/0075_markt_adoptions_are_leads.py"
    spec = importlib.util.spec_from_file_location("m0075", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _adopted_as_client(name: str) -> tuple[uuid.UUID, uuid.UUID]:
    """The pre-fix state: adopted from Markt, flagged client."""
    hub_id = await _corpus(name)
    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name=name, is_client=True, source="hub:bundesagentur")
        s.add(company)
        await s.flush()
        link = HubCompanyLink(
            tenant_id=TENANT, hub_company_id=hub_id, company_id=company.id, relationship="client"
        )
        s.add(link)
        await s.commit()
        return company.id, link.id


async def test_the_migration_resets_markt_clients_without_a_mandate() -> None:
    no_mandate, no_mandate_link = await _adopted_as_client("Ohne Mandat GmbH")
    with_mandate, with_mandate_link = await _adopted_as_client("Mit Mandat GmbH")
    with_manager, with_manager_link = await _adopted_as_client("Mit Manager GmbH")
    only_a_lead, only_a_lead_link = await _adopted_as_client("Nur Lead GmbH")
    async with SessionLocal() as s:
        s.add(Job(tenant_id=TENANT, title="Koch (m/w/d)", client_company_id=with_mandate))
        # A contact promoted "Zu Managern" is the ELI-33 rule for Kunde.
        s.add(Manager(tenant_id=TENANT, company_id=with_manager, full_name="A B", stage="manager"))
        # A bus-dev contact (still a lead) does not make the company a client.
        s.add(Manager(tenant_id=TENANT, company_id=only_a_lead, full_name="C D", stage="bus_dev"))
        # An imported client (not from Markt) is none of this fix's business.
        imported = Company(tenant_id=TENANT, name="Import AG", is_client=True, source="datei-import")
        s.add(imported)
        await s.commit()
        imported_id = imported.id

    m = _migration()
    assert m.downgrade() is None
    for _ in range(2):  # idempotent: a second run changes nothing
        async with SessionLocal() as s:
            for stmt in m.STATEMENTS:
                await s.execute(text(stmt))
            await s.commit()

    async with SessionLocal() as s:
        assert (await s.get(Company, no_mandate)).is_client is False
        assert (await s.get(HubCompanyLink, no_mandate_link)).relationship == "prospect"
        assert (await s.get(Company, with_mandate)).is_client is True
        assert (await s.get(HubCompanyLink, with_mandate_link)).relationship == "client"
        assert (await s.get(Company, with_manager)).is_client is True
        assert (await s.get(HubCompanyLink, with_manager_link)).relationship == "client"
        assert (await s.get(Company, only_a_lead)).is_client is False
        assert (await s.get(HubCompanyLink, only_a_lead_link)).relationship == "prospect"
        assert (await s.get(Company, imported_id)).is_client is True
