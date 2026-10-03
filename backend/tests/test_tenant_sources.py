"""Onboarding a workspace's own database — as a product, not an operator task.

Three things these pin, in order of how badly they would hurt:

1. A stored credential never leaves the server. Not in the list, not in the
   read-back, not masked — absent.
2. The import a workspace asks for is PERFORMED by the machine path. The
   request handler writes a timestamp; nothing decrypts a password inside a
   user's request.
3. A second workspace's credential is invisible to the first, enforced below
   the application.
"""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from app.core import secrets
from app.core.database import SessionLocal
from app.domain.tenantsources import service
from app.domain.tenantsources.models import TenantSource
from app.domain.tenantsources.schemas import TenantSourceWrite

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
API = "/api/v1/tenant-sources"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    """A real key, generated per test run — never a fixture string that could
    end up being the one somebody deploys."""
    monkeypatch.setattr(secrets.settings, "secret_key", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


async def _connect(secret: str = "hunter2", tenant: uuid.UUID = TENANT):
    async with SessionLocal() as s:
        return await service.upsert_source(
            s,
            tenant_id=tenant,
            kind="aifind",
            data=TenantSourceWrite(username="recruiter@example.com", secret=secret),
        )


async def test_the_password_is_not_stored_in_the_clear() -> None:
    await _connect(secret="hunter2")
    async with SessionLocal() as s:
        row = (await service.list_sources(s, tenant_id=TENANT))[0]
    assert row.secret_encrypted and "hunter2" not in row.secret_encrypted
    # And it round-trips for the importer that has to replay it.
    assert service.credentials(row) == ("recruiter@example.com", "hunter2")


async def test_the_api_never_returns_the_secret() -> None:
    await _connect()
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        listed = (await client.get(API)).json()

    assert listed[0]["has_secret"] is True
    assert "secret" not in listed[0] and "secret_encrypted" not in listed[0]
    assert "hunter2" not in str(listed)


async def test_a_credential_cannot_be_stored_without_a_server_key(monkeypatch) -> None:
    """Fail-closed: no key means no storage, not storage in the clear."""
    monkeypatch.setattr(secrets.settings, "secret_key", None)
    secrets.reset_cache()
    async with SessionLocal() as s:
        with pytest.raises(service.NotConfigured):
            await service.upsert_source(
                s,
                tenant_id=TENANT,
                kind="aifind",
                data=TenantSourceWrite(username="a@b.de", secret="x"),
            )


async def test_the_username_can_be_fixed_without_retyping_the_password() -> None:
    await _connect(secret="hunter2")
    async with SessionLocal() as s:
        row = await service.upsert_source(
            s,
            tenant_id=TENANT,
            kind="aifind",
            data=TenantSourceWrite(username="corrected@example.com"),
        )
    assert row.username == "corrected@example.com"
    assert service.credentials(row)[1] == "hunter2"


async def test_asking_for_an_import_queues_it_and_imports_nothing() -> None:
    """THE boundary. The handler writes a timestamp; the runner does the work."""
    await _connect()
    async with SessionLocal() as s:
        row = await service.request_import(s, tenant_id=TENANT, kind="aifind")
        first = row.import_requested_at
        assert first is not None
        # Idempotent: pressing twice is one import, not two.
        again = await service.request_import(s, tenant_id=TENANT, kind="aifind")
    assert again.import_requested_at == first


async def test_a_source_without_a_credential_cannot_be_asked_to_run() -> None:
    async with SessionLocal() as s:
        await service.upsert_source(
            s,
            tenant_id=TENANT,
            kind="aifind",
            data=TenantSourceWrite(username="a@b.de"),  # no secret
        )
        with pytest.raises(service.NotConfigured):
            await service.request_import(s, tenant_id=TENANT, kind="aifind")


async def test_a_paused_source_is_skipped_by_the_runner() -> None:
    await _connect()
    async with SessionLocal() as s:
        await service.request_import(s, tenant_id=TENANT, kind="aifind")
        await service.upsert_source(
            s,
            tenant_id=TENANT,
            kind="aifind",
            data=TenantSourceWrite(username="recruiter@example.com", status="disabled"),
        )
        assert await service.pending_imports(s) == []


async def test_one_workspace_cannot_see_anothers_source() -> None:
    await _connect(secret="mine", tenant=TENANT)
    await _connect(secret="theirs", tenant=OTHER)
    async with SessionLocal() as s:
        mine = await service.list_sources(s, tenant_id=TENANT)
        theirs = await service.list_sources(s, tenant_id=OTHER)
    assert len(mine) == 1 and len(theirs) == 1
    assert service.credentials(mine[0])[1] == "mine"
    assert service.credentials(theirs[0])[1] == "theirs"
    # Same kind, two workspaces, two rows — the unique constraint is per tenant.
    assert mine[0].id != theirs[0].id


async def test_a_rotated_server_key_says_so_instead_of_failing_as_a_bad_login(
    monkeypatch,
) -> None:
    row = await _connect(secret="hunter2")
    monkeypatch.setattr(secrets.settings, "secret_key", Fernet.generate_key().decode())
    secrets.reset_cache()
    with pytest.raises(service.NotConfigured) as raised:
        service.credentials(row)
    assert "Schlüssel" in str(raised.value)


async def test_a_failed_run_is_recorded_and_the_request_cleared() -> None:
    """A source that failed must not retry forever on its own."""
    row = await _connect()
    async with SessionLocal() as s:
        await service.request_import(s, tenant_id=TENANT, kind="aifind")
        await service.record_result(
            s, source_id=row.id, ok=False, error="Login abgelehnt"
        )
        after = await service.get_source(s, tenant_id=TENANT, kind="aifind")
    assert after.import_requested_at is None
    assert after.last_error == "Login abgelehnt"
    assert after.last_run_at is not None


async def test_routes(monkeypatch) -> None:
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        caps = (await client.get(f"{API}/capabilities")).json()
        assert caps["kinds"] == ["aifind"] and caps["secrets_configured"] is True

        created = await client.put(
            f"{API}/aifind",
            json={"username": "recruiter@example.com", "secret": "hunter2"},
        )
        assert created.status_code == 200 and created.json()["has_secret"] is True

        queued = await client.post(f"{API}/aifind/import")
        assert queued.status_code == 200 and queued.json()["queued"] is True

        unknown = await client.put(f"{API}/salesforce", json={"username": "a@b.de"})
        assert unknown.status_code == 404

        gone = await client.delete(f"{API}/aifind")
        assert gone.status_code == 204
        assert (await client.get(API)).json() == []


async def test_the_runner_is_machine_only() -> None:
    """Declared in test_operator_endpoints, asserted here from the other side:
    a password is decrypted in that call, so a session must not reach it."""
    from app.core.auth import get_current_tenant, get_ingest_tenant
    from app.domain.tenantsources.router import router

    route = next(
        r for r in router.routes if getattr(r, "path", "").endswith("/run-imports")
    )
    deps = {d.call for d in route.dependant.dependencies}
    assert get_ingest_tenant in deps
    assert get_current_tenant not in deps


async def test_a_detached_row_still_carries_what_the_runner_needs() -> None:
    """The runner closes its session before the slow part; the credential has
    to survive that or every import fails on a lazy load."""
    from app.domain.tenantsources import runner  # noqa: F401 — import is the point

    row = await _connect(secret="hunter2")
    detached = TenantSource(
        id=row.id,
        tenant_id=row.tenant_id,
        kind=row.kind,
        username=row.username,
        secret_encrypted=row.secret_encrypted,
    )
    assert service.credentials(detached) == ("recruiter@example.com", "hunter2")


async def test_a_bad_login_reads_as_a_bad_login() -> None:
    """The workspace must see what to fix.

    The integration raises a plain RuntimeError here on purpose — it never
    echoes the response body, because a failed Keycloak login re-renders the
    form with the username in it. Measured against the real message the source
    produced in a live run.
    """
    from app.domain.tenantsources import runner

    real = RuntimeError(
        "aiFind login did not return an authorization code (HTTP 200) — "
        "check AI_FIND_EMAIL / AI_FIND_PWD"
    )
    assert runner._human_reason(real) == (
        "Login abgelehnt — bitte Benutzername und Passwort prüfen."
    )
    # Anything else still says something, and never a stack trace.
    assert "fehlgeschlagen" in runner._human_reason(ValueError("boom"))
