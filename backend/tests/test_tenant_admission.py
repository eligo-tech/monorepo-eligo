"""Signing in is not admission.

An organization used to receive a workspace by presenting a token:
`get_or_create` ran on the request path. Nothing leaked — RLS keeps a new
tenant empty and separate — but the refusal was accidental rather than
designed. A stranger saw nothing because their own workspace was blank, not
because anything turned them away, and Clerk's "create organization" button on
the sign-in screen made that a self-service route into the production
database. See ADR 0002 §1.2 (G2).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.tenants import service as tenants_service
from app.domain.tenants.models import Tenant


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def signed_in(monkeypatch):
    """A valid Clerk session for whichever org the bearer token names."""
    from app.core import auth as auth_module

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(
        auth_module,
        "verify_token",
        lambda token: {
            "org_id": token.removeprefix("session-for-"),
            "org_slug": "Acme Recruiting",
            "sub": "user_stranger",
        },
    )


async def _tenant_count() -> int:
    async with SessionLocal() as session:
        return (await session.execute(select(func.count(Tenant.id)))).scalar_one()


async def test_an_unadmitted_organization_is_refused(signed_in) -> None:
    await create_all()
    async with _api() as client:
        resp = await client.get(
            f"{settings.api_v1_prefix}/candidates",
            headers={"Authorization": "Bearer session-for-org_never_seen"},
        )

    assert resp.status_code == 403, resp.text
    assert "Arbeitsbereich" in resp.json()["detail"]


async def test_a_refused_organization_leaves_no_workspace_behind(signed_in) -> None:
    """The refusal must not be a tenant row with a 403 in front of it.

    A workspace created and then denied is still a workspace: it occupies the
    org id, so admitting that organization later silently reuses a row nobody
    decided to create.
    """
    await create_all()
    async with _api() as client:
        await client.get(
            f"{settings.api_v1_prefix}/candidates",
            headers={"Authorization": "Bearer session-for-org_never_seen"},
        )

    assert await _tenant_count() == 0


async def test_an_admitted_organization_is_served(signed_in) -> None:
    await create_all()
    async with SessionLocal() as session:
        await tenants_service.get_or_create(session, clerk_org_id="org_admitted")

    async with _api() as client:
        resp = await client.get(
            f"{settings.api_v1_prefix}/candidates",
            headers={"Authorization": "Bearer session-for-org_admitted"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_the_escape_hatch_still_admits_when_it_is_switched_on(
    signed_in, monkeypatch
) -> None:
    """`ELIGO_AUTO_PROVISION_TENANTS=true` restores the old behaviour.

    Worth a test of its own: an escape hatch nobody exercises is one that has
    quietly stopped working by the time somebody reaches for it during an
    onboarding call.
    """
    await create_all()
    monkeypatch.setattr(settings, "auto_provision_tenants", True)

    async with _api() as client:
        resp = await client.get(
            f"{settings.api_v1_prefix}/candidates",
            headers={"Authorization": "Bearer session-for-org_brand_new"},
        )

    assert resp.status_code == 200, resp.text
    assert await _tenant_count() == 1


async def test_a_renamed_organization_still_resolves_to_its_workspace(
    signed_in,
) -> None:
    """The mapping is the org id; the name is a label that follows it.

    Checked because admission now goes through a different function than
    creation did, and the rename used to be a side effect of `get_or_create`.
    """
    await create_all()
    async with SessionLocal() as session:
        tenant = await tenants_service.get_or_create(
            session, clerk_org_id="org_admitted", name="Old Name"
        )
        tenant_id = tenant.id

    async with _api() as client:
        resp = await client.get(
            f"{settings.api_v1_prefix}/candidates",
            headers={"Authorization": "Bearer session-for-org_admitted"},
        )
    assert resp.status_code == 200

    async with SessionLocal() as session:
        again = await tenants_service.get(session, clerk_org_id="org_admitted")
        assert again is not None
        assert again.id == tenant_id, "a rename must not mint a second workspace"
        assert again.name == "Acme Recruiting"


async def test_a_session_with_no_organization_is_still_refused(monkeypatch) -> None:
    """Unchanged behaviour, pinned: a personal account is not a workspace."""
    from app.core import auth as auth_module

    await create_all()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(auth_module, "verify_token", lambda _t: {"sub": "user_1"})

    async with _api() as client:
        resp = await client.get(
            f"{settings.api_v1_prefix}/candidates",
            headers={"Authorization": "Bearer personal-session"},
        )

    assert resp.status_code == 403
    assert "organization" in resp.json()["detail"]
