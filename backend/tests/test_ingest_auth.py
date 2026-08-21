"""The machine credential for non-interactive ingest.

Ingestion is the platform's first caller that is not a human with a browser
session. These tests pin the contract that makes that safe: the service-token
path exists only when configured, it is compared in constant time, a weak secret
is refused at startup, and it never widens access to anything but ingest.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_GOOD = "t" * 44  # what secrets.token_urlsafe(32) produces, length-wise


def test_a_weak_token_is_refused_at_startup() -> None:
    # A short shared secret is worse than none: it looks like protection while
    # guarding a write endpoint that also makes outbound calls to a public API.
    with pytest.raises(ValidationError):
        Settings(ingest_token="hunter2")


def test_the_machine_path_is_off_unless_configured() -> None:
    assert Settings().ingest_token is None


def test_a_strong_token_is_accepted_and_trimmed() -> None:
    assert Settings(ingest_token=f"  {_GOOD}  ").ingest_token == _GOOD


async def test_service_token_authenticates_ingest(monkeypatch) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core import auth as auth_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "ingest_token", _GOOD)
    monkeypatch.setattr(settings, "auth_enabled", True)

    # Assert the dependency resolves the token WITHOUT reaching Clerk: if it
    # fell through to the human path this would raise.
    def _boom(_token: str) -> dict:
        raise AssertionError("service token must not be verified against Clerk")

    monkeypatch.setattr(auth_module, "verify_token", _boom)

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Wrong token → falls through to the Clerk path, which rejects it.
        wrong = await client.post(
            "/api/v1/hub/ingest",
            json={"source": "nope"},
            headers={"Authorization": f"Bearer {'x' * 44}"},
        )
        assert wrong.status_code == 401

        # Right token → authenticated; the 400 is the *body* being invalid,
        # which proves the request got past auth to the handler.
        right = await client.post(
            "/api/v1/hub/ingest",
            json={"source": "nope"},
            headers={"Authorization": f"Bearer {_GOOD}"},
        )
        assert right.status_code == 400
        assert "unknown hub source" in right.json()["detail"]


async def test_the_service_token_does_not_open_the_rest_of_the_api(monkeypatch) -> None:
    """It is an INGEST credential, not a general-purpose key."""
    from httpx import ASGITransport, AsyncClient

    from app.core import auth as auth_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "ingest_token", _GOOD)
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(
        auth_module, "verify_token", lambda _t: (_ for _ in ()).throw(ValueError("bad"))
    )

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for path in ("/api/v1/hub/companies", "/api/v1/candidates"):
            resp = await client.get(path, headers={"Authorization": f"Bearer {_GOOD}"})
            assert resp.status_code == 401, path
