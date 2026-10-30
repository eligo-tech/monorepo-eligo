"""The REST API accepts browser SESSION tokens only — never OAuth access tokens.

Found by the MCP spike on 2026-10-29. Once OAuth applications were switched on
in the production Clerk instance, a token issued to Claude Code passed
`verify_token`: same signer, same issuer, and no `azp` claim, which
`check_authorized_party` deliberately skips. So a token handed to an AI client
for a read-only connector was a full credential for every REST endpoint,
writes included — past the scopes, the consent gate and the receipts the MCP
path is designed around.

The claims below are the ones that token actually carried (see the spike's
`whoami` output): `typ: at+jwt`, `aud`, `client_id`, `scope`, `org_id`, no
`azp`. The tests sign real JWTs and push them through the real check, and the
first test is the control: a browser session token must still pass, or a
"fix" that rejects everything would turn this file green.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.core import auth
from app.core.config import Settings

ISSUER = "https://clerk.eligolabs.example"
ORIGINS = ["https://eligolabs.com"]
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _StubJWKS:
    """Stands in for Clerk's JWKS endpoint: one key, ours."""

    def get_signing_key_from_jwt(self, token: str):
        class _K:
            key = _KEY.public_key()

        return _K()


@pytest.fixture(autouse=True)
def _clerk(monkeypatch):
    monkeypatch.setattr(
        auth, "settings", Settings(auth_enabled=True, cors_origins=ORIGINS)
    )
    monkeypatch.setattr(auth, "_jwks_client", lambda: _StubJWKS())
    monkeypatch.setattr(auth, "_issuer", lambda: ISSUER)


def _sign(claims: dict, *, typ: str) -> str:
    now = int(time.time())
    body = {"iss": ISSUER, "iat": now, "nbf": now, "exp": now + 300, **claims}
    return jwt.encode(body, _KEY, algorithm="RS256", headers={"typ": typ, "kid": "k1"})


def _session_token() -> str:
    """What the browser sends: Clerk session JWT, minted for our frontend."""
    return _sign(
        {"sub": "user_1", "sid": "sess_1", "azp": ORIGINS[0], "org_id": "org_1"},
        typ="JWT",
    )


def _oauth_token(*, typ: str = "at+jwt") -> str:
    """What Clerk issued to Claude Code — the claims observed in the spike."""
    return _sign(
        {
            "sub": "user_1",
            "org_id": "org_1",
            "aud": "http://localhost:8000/mcp",
            "client_id": "TsCnqZKIJmVBnGy2",
            "scope": "user:org:read offline_access",
            "jti": "oat_1",
        },
        typ=typ,
    )


def test_control_a_browser_session_token_still_passes() -> None:
    claims = auth.verify_token(_session_token())
    assert claims["sub"] == "user_1"


@pytest.mark.parametrize("typ", ["at+jwt", "application/at+jwt", "AT+JWT"])
def test_an_oauth_access_token_is_refused(typ: str) -> None:
    # Clerk sends `at+jwt`; RFC 9068 also allows the full media type, and
    # header values are case-insensitive.
    with pytest.raises(auth.OAuthTokenRefused) as raised:
        auth.verify_token(_oauth_token(typ=typ))
    # The message must say what kind of token this is, so a 401 in the logs
    # points at "an AI client called the REST API", not at a broken login.
    assert "OAuth access token" in str(raised.value)


def test_an_oauth_token_without_the_at_jwt_header_is_still_refused() -> None:
    # Defence in depth: the header is metadata. A `client_id` claim is what
    # makes it an OAuth grant, and a session token never carries one.
    with pytest.raises(auth.OAuthTokenRefused):
        auth.verify_token(_oauth_token(typ="JWT"))


def test_the_rest_api_answers_401_to_an_oauth_token() -> None:
    # The observable: what a client actually gets back from a REST endpoint.
    from app.main import app

    client = TestClient(app)  # no lifespan: the 401 must come before any DB work
    response = client.get(
        "/api/v1/candidates",
        headers={"Authorization": f"Bearer {_oauth_token()}"},
    )
    assert response.status_code == 401
    assert "OAuth access token" in response.json()["detail"]


@pytest.mark.parametrize("action", ["confirm", "decline"])
def test_an_ai_client_cannot_decide_a_proposal(action: str) -> None:
    # PR 4: the token Claude holds must not reach the one door that applies a
    # proposal. Named explicitly rather than inherited from the global check.
    from app.main import app

    client = TestClient(app)
    response = client.post(
        f"/api/v1/proposals/00000000-0000-0000-0000-000000000001/{action}",
        headers={"Authorization": f"Bearer {_oauth_token()}"},
    )
    assert response.status_code == 401
