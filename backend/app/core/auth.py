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
    """Scope RLS to this tenant for the request transaction. No-op on SQLite."""
    if settings.is_postgres:
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


# Annotated dependency used across routers in place of the default-tenant query param.
CurrentTenant = Depends(get_current_tenant)
