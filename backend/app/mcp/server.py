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
    Effect,
)
from app.core import auth
from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.features import service as features
from app.domain.proposals import service as proposals
from app.domain.tenants import service as tenants
from app.mcp.auth import ClerkOAuthVerifier
from app.mcp.ratelimit import Limiter, RateLimited

#: Asking for this scope is what makes Clerk's consent screen show the
#: organization selector, so the token carries `org_id`.
REQUIRED_SCOPES = ["user:org:read"]

limiter = Limiter()

#: What `/.well-known/oauth-protected-resource/mcp` advertises. Read once, at
#: import, because the SDK builds that route then; `assert_mcp_configured`
#: refuses to boot production when it would be the placeholder.
AUTH_ISSUER = auth._issuer() or "https://invalid.example"


class MCPMisconfigured(RuntimeError):
    """MCP is switched on but cannot work: say so at boot, not per request."""


def assert_mcp_configured() -> None:
    """With MCP on in a real deployment, refuse to start on a config that fails silently.

    Each of these otherwise shows up only as "every login fails" on the
    client: a localhost or plain-http resource URL (every token's `aud` is
    the real URL, so all are refused, and the metadata points Claude at
    localhost), or no Clerk issuer (metadata advertises a placeholder).
    """
    if not settings.mcp_enabled or not settings.is_postgres:
        return
    url = urlparse(settings.mcp_resource_url)
    if url.scheme != "https" or url.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise MCPMisconfigured(
            f"ELIGO_MCP_RESOURCE_URL must be the public https URL users add in Claude, "
            f"not {settings.mcp_resource_url!r}"
        )
    if not auth._issuer():
        raise MCPMisconfigured(
            "MCP needs the Clerk issuer (ELIGO_CLERK_ISSUER or a publishable key)"
        )


INSTRUCTIONS = (
    "Eligo Labs recruiting CRM — the user's workspace: running processes, "
    "candidates, mandates, matches, reports and public market postings. Every "
    "answer lists its sources; cite them. Matches are recommendations for a "
    "human, never decisions. Contact data, salaries and notes are not available "
    "through this connection. You may PROPOSE a process-step update or a "
    "candidate note; nothing changes until a person confirms it in Eligo. Say "
    "so plainly — never tell the user a change was made. Rejecting a candidate, "
    "deleting and sending are not available."
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
            raise ToolError(
                f"AI access is not enabled for this workspace. Eligo says: {exc} "
                "A workspace admin switches it on in Eligo under "
                "Einstellungen → KI-Funktionen."
            ) from None

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
        except proposals.TooManyPending as exc:
            raise ToolError(str(exc)) from None
        except (ActionForbidden, ActionInputInvalid) as exc:
            raise ToolError(str(exc)) from None
    return out.model_dump(mode="json")


def _tool_for(spec: ActionSpec):
    """A function whose signature IS the action's input model, for the SDK's schema."""

    async def call(**kwargs: Any) -> dict:
        # Every argument, defaults included: the registry validates them again.
        return await _run(spec, kwargs)

    params = [
        inspect.Parameter(
            name,
            inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty if field.is_required() else field.default,
            # Constraints (ge/le …) travel with the type so the schema Claude
            # sees states the bounds the registry will enforce.
            annotation=Annotated[
                (field.annotation, *field.metadata, Field(description=field.description))
            ],
        )
        for name, field in spec.input.model_fields.items()
    ]
    call.__signature__ = inspect.Signature(params, return_annotation=dict[str, Any])  # type: ignore[attr-defined]
    call.__name__ = tool_name(spec.name)
    return call


def _transport_security() -> TransportSecuritySettings:
    """Only the resource host. Claude's connectors call from Anthropic's servers,
    not from a browser, so no browser origin needs to be allowed."""
    url = urlparse(settings.mcp_resource_url)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[url.netloc],
        allowed_origins=[f"{url.scheme}://{url.netloc}"],
    )


def build() -> MCPServer:
    srv = MCPServer(
        name="eligo",
        instructions=INSTRUCTIONS,
        token_verifier=ClerkOAuthVerifier(),
        auth=AuthSettings(
            issuer_url=AUTH_ISSUER,
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
            # A read is "safe to run"; a proposal creates a pending row — not
            # read-only, never destructive, and a repeat is a second proposal.
            annotations=ToolAnnotations(
                readOnlyHint=spec.effect is Effect.READ,
                destructiveHint=False,
                idempotentHint=spec.effect is Effect.READ,
            ),
        )
    return srv


server = build()
asgi_app = server.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=_transport_security(),
)

#: The only paths the MCP app answers. Exact, not a prefix mount: a Mount("/")
#: wins over a FastAPI route whose path matched but whose method did not, and
#: turned the API's 405s, trailing-slash redirects and JSON 404s into
#: plain-text 404s.
MCP_PATHS = frozenset({"/mcp", "/mcp/", "/.well-known/oauth-protected-resource/mcp"})


class MCPRoutes:
    """ASGI middleware: send the MCP paths to the MCP app, everything else on."""

    def __init__(self, app) -> None:  # noqa: ANN001 — any ASGI app
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] == "http" and scope["path"] in MCP_PATHS:
            await asgi_app(scope, receive, send)
        else:
            await self.app(scope, receive, send)
