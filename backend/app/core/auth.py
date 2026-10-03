"""Authentication & tenant resolution (Clerk).

Verifies a Clerk session JWT (RS256, via Clerk's JWKS), reads the active
**organization** from it, and maps that org to an internal `tenant_id`. That
tenant is then set as a per-transaction Postgres GUC (`app.current_tenant`) so
Row-Level Security can isolate every query at the database layer.

When `settings.auth_enabled` is false the API runs as the default tenant (no
login) — the scaffold/demo/CI default.
"""

from __future__ import annotations

import base64
import functools
import secrets
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import current_tenant_var, get_db
from app.core.logging import get_logger
from app.domain.tenants import service as tenants_service

logger = get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)


def _frontend_api_host() -> str | None:
    """Clerk publishable keys embed the Frontend API host:
    ``pk_test_<base64("host$")>``. Decode it to derive JWKS URL + issuer."""
    pk = settings.clerk_publishable_key
    if not pk:
        return None
    b64 = pk.split("_", 2)[-1]
    try:
        decoded = base64.b64decode(b64 + "=" * (-len(b64) % 4)).decode()
    except Exception:
        return None
    return decoded.rstrip("$") or None


def _issuer() -> str | None:
    if settings.clerk_issuer:
        return settings.clerk_issuer
    host = _frontend_api_host()
    return f"https://{host}" if host else None


@functools.lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    url = settings.clerk_jwks_url or f"https://{_frontend_api_host()}/.well-known/jwks.json"
    return PyJWKClient(url)


def verify_token(token: str) -> dict:
    """Verify a Clerk session JWT and return its claims. Raises on any failure."""
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=_issuer(),
        options={"verify_aud": False, "require": ["exp", "iss"]},
    )


def _org_id(claims: dict) -> str | None:
    """Active-organization id — top-level (`org_id`) or nested (`o.id`, v2 tokens)."""
    return claims.get("org_id") or (claims.get("o") or {}).get("id")


async def _set_tenant_guc(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Scope RLS to this tenant for the request transaction. No-op on SQLite.

    Also drops to the app role so RLS applies even if the connection role is
    BYPASSRLS (Supabase `postgres`). Covers the current transaction; the
    after_begin listener re-applies both on any later transaction."""
    if not settings.is_postgres:
        return
    role = settings.db_app_role
    if role and role.replace("_", "").isalnum():
        await db.execute(text(f'SET LOCAL ROLE "{role}"'))
    await db.execute(
        text("SELECT set_config('app.current_tenant', :t, true)"),
        {"t": str(tenant_id)},
    )


class InsecureConfiguration(RuntimeError):
    """The process is configured to serve real data with no authentication."""


def assert_auth_configured() -> None:
    """Refuse to start a Postgres deployment with authentication switched off.

    `auth_enabled` defaults to False so that tests and the local SQLite demo
    need no setup — and that default is the one fail-open left in the stack.
    With auth off, `get_current_tenant` hands every anonymous caller the
    DEFAULT tenant: no token, no organisation, full read and write. Against the
    scaffold's SQLite file that is a convenience; against the production
    database it would publish one workspace to the internet and mix every
    write into it.

    The failure mode is quiet, which is what makes it dangerous: nothing errors,
    the app simply serves the wrong tenant to whoever asks. A deployment that
    forgets `ELIGO_AUTH_ENABLED` must therefore not come up at all — the same
    stance `get_ingest_tenant` already takes when no machine credential is
    configured (503 rather than "accept whoever asks").

    `ELIGO_ALLOW_INSECURE_NO_AUTH=true` overrides it for a local Postgres, and
    says so in the log every boot.
    """
    if settings.auth_enabled or not settings.is_postgres:
        return
    if settings.allow_insecure_no_auth:
        get_logger(__name__).error(
            "SECURITY: serving %s with authentication DISABLED — every request "
            "is the default tenant. Allowed only by ELIGO_ALLOW_INSECURE_NO_AUTH.",
            settings.safe_database_url,
        )
        return
    raise InsecureConfiguration(
        "refusing to start: ELIGO_AUTH_ENABLED is false and the database is "
        f"Postgres ({settings.safe_database_url}). With auth off every request "
        "is served as the default tenant, so this would expose and corrupt real "
        "workspace data. Set ELIGO_AUTH_ENABLED=true, or "
        "ELIGO_ALLOW_INSECURE_NO_AUTH=true if this database is genuinely a "
        "local one you own."
    )


#: The two things a member of a workspace can be.
#:
#: Deliberately two. Every role scheme grows, and the ones that start with
#: five are guesses about a workload nobody has run yet. These two answer the
#: question that exists today: may this person change how data enters the
#: workspace, or only work the book inside it.
ADMIN = "admin"
RECRUITER = "recruiter"

#: Clerk's own role names that mean "admin here". Clerk writes `org:admin` in
#: v1 tokens and `admin` in v2; custom roles come through as themselves.
_ADMIN_ROLES = {"admin", "owner"}


@dataclass(frozen=True)
class Actor:
    """Who is making this request, as the TOKEN says — never the client.

    The browser used to be asked who it was (`?editor=`), which is not a
    question with a trustworthy answer. Everything attributable now comes
    from the verified JWT.
    """

    tenant_id: uuid.UUID
    #: Clerk user id (`sub`). None in the auth-disabled demo.
    user_id: str | None
    #: What a receipt should call this person.
    name: str
    role: str
    #: False when the token carried no role claim at all. The actor is then
    #: treated as a recruiter — least privilege — and the UI says why, rather
    #: than leaving somebody to wonder which button disappeared.
    role_known: bool

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN


def _role(claims: dict) -> tuple[str, bool]:
    """Clerk's role for the active org → ours. Unknown means recruiter."""
    raw = claims.get("org_role") or (claims.get("o") or {}).get("rol")
    if not raw:
        return RECRUITER, False
    normalized = str(raw).rsplit(":", 1)[-1].strip().lower()
    return (ADMIN if normalized in _ADMIN_ROLES else RECRUITER), True


def _actor_name(claims: dict) -> str:
    """The most human thing the token offers.

    A default Clerk session token carries `sub` and little else; `name` and
    `email` appear only when the session-token template includes them. So a
    receipt may read "user_3Gj…" until that is configured — attributable
    either way, which is the part that matters.
    """
    for key in ("name", "full_name"):
        value = claims.get(key)
        if value:
            return str(value)
    given, family = claims.get("given_name"), claims.get("family_name")
    if given or family:
        return " ".join(part for part in (given, family) if part)
    return str(claims.get("email") or claims.get("sub") or "unbekannt")


async def get_current_actor(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Actor:
    """Resolve WHO and WHICH WORKSPACE, and pin the tenant for RLS.

    auth disabled → the default tenant as an admin, so the local demo and the
    tests are not locked out of their own settings. auth enabled → verify the
    Clerk JWT, require an active organization, map org → tenant (created on
    first sight), and read the role from the same token.
    """
    if not settings.auth_enabled:
        current_tenant_var.set(str(settings.default_tenant_id))
        await _set_tenant_guc(db, settings.default_tenant_id)
        return Actor(
            tenant_id=settings.default_tenant_id,
            user_id=None,
            name="Demo",
            role=ADMIN,
            role_known=False,
        )

    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        claims = verify_token(creds.credentials)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc

    org_id = _org_id(claims)
    if not org_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "no active organization — select an organization to continue",
        )

    tenant = await tenants_service.get_or_create(
        db, clerk_org_id=org_id, name=claims.get("org_slug") or (claims.get("o") or {}).get("slg")
    )
    current_tenant_var.set(str(tenant.id))
    await _set_tenant_guc(db, tenant.id)  # pin the in-flight transaction too

    role, known = _role(claims)
    return Actor(
        tenant_id=tenant.id,
        user_id=claims.get("sub"),
        name=_actor_name(claims),
        role=role,
        role_known=known,
    )


async def get_current_tenant(actor: Actor = Depends(get_current_actor)) -> uuid.UUID:
    """The workspace for this request. Unchanged for every existing caller."""
    return actor.tenant_id


async def require_admin(actor: Actor = Depends(get_current_actor)) -> Actor:
    """Guard the few endpoints that change HOW data enters the workspace.

    Working the book — candidates, mandates, processes, assessments — is
    everybody's job. Connecting a data source, importing a file over the
    record and disconnecting an ATS are not: they rewrite what everyone else
    then works on.
    """
    if not actor.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Nur Administratoren dürfen die Datenquellen dieses Workspace ändern."
            + ("" if actor.role_known else " (Das Token enthält keine Rolle.)"),
        )
    return actor


async def get_ingest_tenant(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Authorize a MACHINE caller for ingestion. A user token is rejected.

    Ingestion is a scheduled job (ARCHITECTURE.md RULE 1). This dependency used
    to fall back to `get_current_tenant`, which made the rule false: any
    authenticated recruiter could drive arbitrary crawl slices, write the shared
    cross-tenant corpus, deactivate postings globally, and read
    `/hub/crawl-profiles` — the union of every workspace's saved-search terms,
    which is precisely the competitive intelligence the unattributed design
    exists to protect. There is no fallback now: a valid Clerk JWT gets 401.

    Modes, all fail-closed:

      * token configured → it must match, in every environment. A session JWT,
        a wrong token or no token is 401.
      * no token, auth disabled → allowed. Local dev and CI, where every other
        endpoint is open to the default tenant anyway.
      * no token, auth enabled → 503. A production deployment that never
        configured a machine credential must not accept ingestion at all;
        refusing loudly beats silently accepting whoever asks.
    """
    configured = settings.ingest_token
    presented = creds.credentials if creds else None

    if configured:
        if presented and secrets.compare_digest(presented, configured):
            tenant_id = settings.ingest_tenant_id or settings.default_tenant_id
            logger.info("ingest authorized by machine credential (tenant=%s)", tenant_id)
            current_tenant_var.set(str(tenant_id))
            await _set_tenant_guc(db, tenant_id)
            return tenant_id
        # Deliberately identical for "no credential" and "a user's JWT": the
        # response must not tell a caller whether they merely used the wrong
        # KIND of credential.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "ingestion requires a machine credential",
        )

    if settings.auth_enabled:
        logger.error(
            "ingest attempted but ELIGO_INGEST_TOKEN is unset — refusing"
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ingestion is not configured on this deployment",
        )

    # Auth disabled: local dev / CI, where the whole API runs as one tenant.
    tenant_id = settings.ingest_tenant_id or settings.default_tenant_id
    current_tenant_var.set(str(tenant_id))
    await _set_tenant_guc(db, tenant_id)
    return tenant_id


# `get_current_user` lived here: a second, weaker read of the same token that
# returned the Clerk `sub` and nothing else. `get_current_actor` replaces it —
# one identity per request, carrying the name a receipt should show and the
# role the guard needs.
# Annotated dependency used across routers in place of the default-tenant query param.
CurrentTenant = Depends(get_current_tenant)
