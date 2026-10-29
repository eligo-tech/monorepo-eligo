"""The MCP endpoint, end to end over HTTP: who gets in, and what they get.

Tokens are real RS256 JWTs signed with a test key, shaped like the ones Clerk
issued to Claude in the spike (ADR 0003 §2): `typ: at+jwt`, `client_id`,
`scope`, `org_id`, `aud` = the resource URL. Every refusal has a control next
to it that passes, so a server that refused everything could not turn this
file green.

Separate from `test_no_open_endpoints.py`, which walks FastAPI's routes and
cannot see a mounted ASGI app.
"""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.actions.core import REGISTRY
from app.core import auth
from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ReceiptAction
from app.domain.features import service as features
from app.domain.tenants import service as tenants
from app.domain.tenants.models import Tenant
from app.domain.verification.models import Receipt
from app.mcp import server as mcp

ISSUER = "https://clerk.eligolabs.example"
RESOURCE = settings.mcp_resource_url  # what the server was built with
BASE = RESOURCE.rsplit("/mcp", 1)[0]
ORG = "org_admitted"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _StubJWKS:
    def get_signing_key_from_jwt(self, token: str):
        class _K:
            key = _KEY.public_key()

        return _K()


@pytest.fixture(autouse=True)
def _clerk(monkeypatch):
    monkeypatch.setattr(auth, "_jwks_client", lambda: _StubJWKS())
    monkeypatch.setattr(auth, "_issuer", lambda: ISSUER)
    monkeypatch.setattr(settings, "mcp_enabled", True)
    monkeypatch.setattr(settings, "mcp_allowed_tenants", "")
    mcp.limiter.reset()


def _token(**overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "iat": now,
        "nbf": now,
        "exp": now + 300,
        "sub": "user_1",
        "org_id": ORG,
        "aud": RESOURCE,
        "client_id": "TsCnqZKIJmVBnGy2",
        "scope": "user:org:read offline_access",
        "jti": "oat_1",
    }
    typ = overrides.pop("typ", "at+jwt")
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"typ": typ, "kid": "k1"})


async def _rpc(method: str, params: dict | None = None, *, token: str | None = None):
    from app.main import app

    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-11-25",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    # The SDK runs its session manager once per process (in the app lifespan);
    # each test has its own event loop, so the once-only flag is cleared here.
    manager = mcp.server.session_manager
    manager._has_started = False
    async with manager.run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            return await client.post("/mcp", json=body, headers=headers)


async def _call(tool: str, args: dict | None = None, *, token: str | None = None) -> dict:
    response = await _rpc(
        "tools/call", {"name": tool, "arguments": args or {}}, token=token or _token()
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _text(result: dict) -> str:
    return " ".join(c.get("text", "") for c in result.get("content", []))


async def _admit(*, consent: bool = True) -> uuid.UUID:
    async with SessionLocal() as s:
        tenant = await tenants.get_or_create(s, clerk_org_id=ORG, name="Admitted GmbH")
        await s.commit()
        if consent:
            await features.accept(
                s,
                tenant_id=tenant.id,
                key="mcp",
                terms_version=features.FEATURES["mcp"].terms_version,
                actor_name="Admin",
            )
        return tenant.id


# --- authentication ----------------------------------------------------------


async def test_no_token_is_401_pointing_at_the_resource_metadata() -> None:
    response = await _rpc("tools/list")
    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]


async def test_the_resource_metadata_names_this_url_and_clerk() -> None:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        response = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json()["resource"] == RESOURCE


@pytest.mark.parametrize(
    "bad",
    [
        {"aud": "https://elsewhere.example/mcp"},  # minted for another server
        {"aud": None},  # no audience at all
        {"org_id": None},  # no workspace to scope to
        {"client_id": None, "typ": "JWT"},  # a browser session token
        {"exp": int(time.time()) - 10},
    ],
    ids=["wrong-aud", "no-aud", "no-org", "session-token", "expired"],
)
async def test_a_token_that_is_not_ours_is_401(bad) -> None:
    assert (await _rpc("tools/list", token=_token(**bad))).status_code == 401


async def test_control_a_good_token_is_let_in() -> None:
    response = await _rpc("tools/list", token=_token())
    assert response.status_code == 200, response.text


# --- the tool list -------------------------------------------------------------


async def test_the_tools_are_exactly_the_registrys_agent_actions() -> None:
    response = await _rpc("tools/list", token=_token())
    names = {t["name"] for t in response.json()["result"]["tools"]}
    assert names == {mcp.tool_name(s.name) for s in REGISTRY.agent_exposed()}
    assert names >= {"pipeline_processes", "candidates_list"}


async def test_a_tool_carries_its_input_schema() -> None:
    response = await _rpc("tools/list", token=_token())
    tools = {t["name"]: t for t in response.json()["result"]["tools"]}
    props = tools["candidates_list"]["inputSchema"]["properties"]
    assert {"skill", "city", "available_within_weeks", "limit"} <= set(props)
    assert tools["candidates_list"]["annotations"]["readOnlyHint"] is True


# --- admission, consent, the call ----------------------------------------------


async def test_an_unadmitted_org_is_refused_and_never_provisioned(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auto_provision_tenants", True)
    result = await _call("pipeline_processes")
    assert result["isError"] is True
    assert "workspace" in _text(result).lower()
    async with SessionLocal() as s:
        assert (await s.execute(select(Tenant).where(Tenant.clerk_org_id == ORG))).first() is None


async def test_without_admin_consent_the_call_is_refused() -> None:
    await _admit(consent=False)
    result = await _call("pipeline_processes")
    assert result["isError"] is True
    assert "zustimmen" in _text(result)


async def test_the_operator_switch_closes_it_for_everyone(monkeypatch) -> None:
    await _admit()
    monkeypatch.setattr(settings, "mcp_enabled", False)
    assert (await _call("pipeline_processes"))["isError"] is True


async def test_an_admitted_consenting_workspace_gets_its_data_and_a_receipt() -> None:
    tenant_id = await _admit()
    async with SessionLocal() as s:
        s.add(Candidate(tenant_id=tenant_id, full_name="Anna Schmidt", email="a@x.example"))
        s.add(Candidate(tenant_id=uuid.uuid4(), full_name="Somebody Else"))
        await s.commit()

    result = await _call("candidates_list")
    assert result.get("isError") is not True, _text(result)
    data = result["structuredContent"]
    assert [c["full_name"] for c in data["candidates"]] == ["Anna Schmidt"]
    assert "a@x.example" not in str(result)

    async with SessionLocal() as s:
        reads = (
            (
                await s.execute(
                    select(Receipt).where(
                        Receipt.tenant_id == tenant_id, Receipt.action == ReceiptAction.READ
                    )
                )
            )
            .scalars()
            .all()
        )
    [receipt] = reads
    assert receipt.subject_id == "candidates.list"
    assert receipt.actor_user_id == "user_1"
    assert receipt.payload["client_id"] == "TsCnqZKIJmVBnGy2"


async def test_a_bad_argument_is_a_tool_error_not_a_crash() -> None:
    await _admit()
    result = await _call("candidates_get", {"candidate_id": str(uuid.uuid4())})
    assert result["isError"] is True


# --- rate limit ---------------------------------------------------------------


async def test_calls_past_the_per_user_limit_are_refused(monkeypatch) -> None:
    await _admit()
    monkeypatch.setattr(settings, "mcp_rate_limit_per_minute", 2)
    assert (await _call("reporting_funnel")).get("isError") is not True
    assert (await _call("reporting_funnel")).get("isError") is not True
    third = await _call("reporting_funnel")
    assert third["isError"] is True and "limit" in _text(third).lower()
    # Another person in the same workspace is not affected.
    assert (await _call("reporting_funnel", token=_token(sub="user_2"))).get("isError") is not True
