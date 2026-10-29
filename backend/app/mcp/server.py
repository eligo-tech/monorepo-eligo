"""The MCP server, generated from the action registry.

One tool per agent-exposed action (`REGISTRY.agent_exposed()`), so the tool
list cannot drift from what the registry allows. Each call:

1. the SDK's bearer middleware has already verified the token (`auth.py`);
2. rate limit per user;
3. org → workspace, READ ONLY — never auto-provisioned, whatever
   `ELIGO_AUTO_PROVISION_TENANTS` says (ADR 0003 §3.4);
4. pin the workspace for RLS, then the `mcp` feature gate (operator switch,
   allowlist, admin consent to the current terms);
5. `REGISTRY.invoke` as an agent actor — which checks the effect, validates
   the input, pins tenant + actor, and writes the READ receipt.

Every refusal comes back as a tool error with a readable reason, so Claude
can tell the user what is missing instead of failing silently.
"""

from __future__ import annotations

import inspect
from typing import Annotated, Any
from urllib.parse import urlparse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from app.actions import catalog  # noqa: F401 — registers the actions
from app.actions.core import (
    REGISTRY,
    ActionContext,
    ActionForbidden,
    ActionInputInvalid,
    ActionNotFound,
    ActionSpec,
)
from app.core import auth
from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.features import service as features
from app.domain.tenants import service as tenants
from app.mcp.auth import ClerkOAuthVerifier
from app.mcp.ratelimit import Limiter, RateLimited

#: Asking for this scope is what makes Clerk's consent screen show the
#: organization selector, so the token carries `org_id`.
REQUIRED_SCOPES = ["user:org:read"]

limiter = Limiter()

INSTRUCTIONS = (
    "Eligo Labs recruiting CRM — read-only access to the user's workspace: "
    "running processes, candidates, mandates, matches, reports and public market "
    "postings. Every answer lists its sources; cite them. Matches are "
    "recommendations for a human, never decisions. Contact data, salaries and "
    "notes are not available through this connection."
)


def tool_name(action_name: str) -> str:
    """`candidates.list` → `candidates_list`: Claude's tool names allow no dots."""
    return action_name.replace(".", "_")


async def _run(spec: ActionSpec, args: dict[str, Any]) -> dict:
    token = get_access_token()
    if token is None:  # the bearer middleware runs first; belt and braces
        raise ToolError("Not authenticated.")
    claims = token.claims or {}
    org_id = auth._org_id(claims)

    try:
        limiter.check(f"{token.subject}")
    except RateLimited as exc:
        raise ToolError(str(exc)) from None

    async with SessionLocal() as db:
        tenant = await tenants.get(db, clerk_org_id=org_id)
        if tenant is None:
            raise ToolError(
                "This organization has no Eligo workspace yet. Ask Eligo Labs to admit "
                f"it (organization {org_id})."
            )
        await auth._set_tenant_guc(db, tenant.id)
        try:
            await features.ensure_enabled(db, tenant_id=tenant.id, key="mcp")
        except features.FeatureDisabled as exc:
            raise ToolError(f"AI access is not enabled for this workspace: {exc}") from None

        actor = auth.Actor(
            tenant_id=tenant.id,
            user_id=token.subject,
            name=auth._actor_name(claims),
            role=auth.RECRUITER,  # least privilege; reads need no more
            role_known=False,
            kind="agent",
            client_id=token.client_id,
        )
        try:
            out = await REGISTRY.invoke(spec.name, ActionContext(session=db, actor=actor), args)
        except ActionNotFound as exc:
            raise ToolError(f"Not found in this workspace: {exc}") from None
        except (ActionForbidden, ActionInputInvalid) as exc:
            raise ToolError(str(exc)) from None
    return out.model_dump(mode="json")


def _tool_for(spec: ActionSpec):
    """A function whose signature IS the action's input model, for the SDK's schema."""

    async def call(**kwargs: Any) -> dict:
        return await _run(spec, {k: v for k, v in kwargs.items() if v is not None})

    params = [
        inspect.Parameter(
            name,
            inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty if field.is_required() else field.default,
            annotation=Annotated[field.annotation, Field(description=field.description)]
            if field.description
            else field.annotation,
        )
        for name, field in spec.input.model_fields.items()
    ]
    call.__signature__ = inspect.Signature(params, return_annotation=dict[str, Any])  # type: ignore[attr-defined]
    call.__name__ = tool_name(spec.name)
    return call


def _transport_security() -> TransportSecuritySettings:
    host = urlparse(settings.mcp_resource_url).netloc
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[host, "localhost:*", "127.0.0.1:*"],
        allowed_origins=[f"https://{host}", "http://localhost:*", "https://claude.ai"],
    )


def build() -> MCPServer:
    srv = MCPServer(
        name="eligo",
        instructions=INSTRUCTIONS,
        token_verifier=ClerkOAuthVerifier(),
        auth=AuthSettings(
            issuer_url=auth._issuer() or "https://invalid.example",
            resource_server_url=settings.mcp_resource_url,
            required_scopes=REQUIRED_SCOPES,
            # The verifier checks `aud` itself (ADR 0003 §3.2).
            validate_token_resource=False,
        ),
    )
    for spec in REGISTRY.agent_exposed():
        srv.add_tool(
            _tool_for(spec),
            name=tool_name(spec.name),
            description=spec.description,
            annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
        )
    return srv


server = build()
asgi_app = server.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=_transport_security(),
)
