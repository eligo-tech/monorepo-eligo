"""„+ Unternehmen“ on Postgres, as the runtime role, under RLS (ELI-57).

ELI-43 shipped „+ Unternehmen“ with service tests on SQLite; the client
answered "Unternehmen anlegen nicht möglich" the same day. SQLite has no RLS
and no Postgres semantics, so only this file can show the create path as
production runs it. Skipped unless Postgres.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, admin_engine, current_tenant_var, engine
from app.domain.companies.models import Company
from app.domain.tenants.models import Tenant

pytestmark = pytest.mark.skipif(not settings.is_postgres, reason="Postgres only")


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


async def _workspace() -> uuid.UUID:
    tenant = uuid.uuid4()
    with _as(None):
        async with SessionLocal() as s:
            s.add(Tenant(id=tenant, clerk_org_id=f"org_{tenant.hex}", name="HR test"))
            await s.commit()
    return tenant


@contextlib.asynccontextmanager
async def _client(tenant: uuid.UUID):
    """The app as a signed-in person of `tenant` — pinned for RLS the way
    `get_current_actor` pins it."""
    from app.core.auth import ADMIN, Actor, _set_tenant_guc, get_current_actor
    from app.core.database import get_db
    from app.main import app

    async def pinned(db=Depends(get_db)) -> Actor:
        current_tenant_var.set(str(tenant))
        await _set_tenant_guc(db, tenant)
        return Actor(tenant_id=tenant, user_id="user_x", name="Anna Recruiter", role=ADMIN, role_known=True)

    app.dependency_overrides[get_current_actor] = pinned
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


@pytest.mark.parametrize(
    "body",
    [
        # Exactly what the form sends (`newCompanyPayload` + api.createCompany).
        {"is_client": False, "name": "Muster GmbH", "location": None, "website": None, "status": "lead"},
        {"is_client": True, "name": "Muster GmbH", "location": "Nürnberg", "website": "www.muster.de", "status": "client"},
        {"is_client": False, "name": "Muster GmbH", "location": "Berlin", "website": "https://muster.de/karriere", "status": "lead"},
    ],
)
async def test_the_form_creates_a_company_and_its_page_opens(body: dict) -> None:
    tenant = await _workspace()
    body = {**body, "name": f"{body['name']} {uuid.uuid4().hex[:6]}"}

    async with _client(tenant) as c:
        made = await c.post(f"{settings.api_v1_prefix}/companies", json=body)
        assert made.status_code == 201, made.text
        page = await c.get(f"{settings.api_v1_prefix}/companies/{made.json()['id']}/page")
        assert page.status_code == 200, page.text
        listed = await c.get(f"{settings.api_v1_prefix}/companies/overview")
        assert listed.status_code == 200, listed.text

    assert page.json()["company"]["status"] == body["status"]
    assert page.json()["company"]["status_set"] is True
    assert body["name"] in [r["name"] for r in listed.json()]
    with _as(tenant):
        async with SessionLocal() as s:
            rows = (await s.scalars(select(Company).where(Company.tenant_id == tenant))).all()
    assert [r.name for r in rows] == [body["name"]]


async def test_the_same_company_twice_is_a_409_naming_the_first() -> None:
    tenant = await _workspace()
    body = {"is_client": False, "name": f"Doppel AG {uuid.uuid4().hex[:6]}", "location": None, "website": None, "status": "lead"}

    async with _client(tenant) as c:
        first = await c.post(f"{settings.api_v1_prefix}/companies", json=body)
        again = await c.post(f"{settings.api_v1_prefix}/companies", json=body)

    assert first.status_code == 201, first.text
    assert again.status_code == 409, again.text
    assert first.json()["id"] in again.text


async def test_with_an_ort_the_markt_employer_of_that_town_is_linked_on_create() -> None:
    import datetime as dt

    from app.domain.hub.models import EMPLOYER, HubCompany, HubCompanyLink
    from app.domain.hub.resolution import normalize_company_name

    tenant = await _workspace()
    name = f"Grimme Landtechnik {uuid.uuid4().hex[:6]} GmbH"
    now = dt.datetime(2026, 11, 19, tzinfo=dt.UTC)
    with _as(tenant):
        async with SessionLocal() as s:
            hub = HubCompany(
                name=name, normalized_name=normalize_company_name(name), dedupe_key=f"k-{uuid.uuid4()}",
                resolution_basis="name_place", city="Damme", source="bundesagentur", kind=EMPLOYER,
                first_seen_at=now, last_seen_at=now,
            )
            s.add(hub)
            await s.commit()
            hub_id = hub.id

    body = {"is_client": True, "name": name, "location": "Damme", "website": "grimme.de", "status": "client"}
    async with _client(tenant) as c:
        made = await c.post(f"{settings.api_v1_prefix}/companies", json=body)
        assert made.status_code == 201, made.text
        page = await c.get(f"{settings.api_v1_prefix}/companies/{made.json()['id']}/page")
        assert page.status_code == 200, page.text

    with _as(tenant):
        async with SessionLocal() as s:
            link = await s.scalar(select(HubCompanyLink).where(HubCompanyLink.hub_company_id == hub_id))
    assert link is not None and str(link.company_id) == made.json()["id"]
    assert link.relationship == "client"
