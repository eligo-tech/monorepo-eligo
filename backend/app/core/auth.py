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


async def get_current_tenant(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Resolve the tenant for this request and pin it for RLS.

    auth disabled → default tenant. auth enabled → verify the Clerk JWT, require
    an active organization, and map org → tenant (created on first sight).
    """
    if not settings.auth_enabled:
        current_tenant_var.set(str(settings.default_tenant_id))
        await _set_tenant_guc(db, settings.default_tenant_id)
        return settings.default_tenant_id

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
    return tenant.id


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


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str | None:
    """Best-effort identity of the acting user (Clerk ``sub`` claim).

    Used to attribute human actions (e.g. a manual candidate edit) in the
    append-only receipt ledger. Returns ``None`` in demo/auth-disabled mode.
    Never raises: authentication is already enforced by ``get_current_tenant``
    on the same request, so this only needs to *read* the identity.
    """
    if not settings.auth_enabled or creds is None:
        return None
    try:
        return verify_token(creds.credentials).get("sub")
    except Exception:
        return None


# Annotated dependency used across routers in place of the default-tenant query param.
CurrentTenant = Depends(get_current_tenant)
