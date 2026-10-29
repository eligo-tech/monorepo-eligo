"""Verify Clerk-issued OAuth access tokens for `/mcp` (ADR 0003).

Clerk is the authorization server; this endpoint is only a resource server.
A token is accepted when, and only when:

- Clerk signed it (JWKS), it is unexpired and Clerk issued it;
- its audience is THIS server's resource URL — a token minted for another
  server, or for our old tunnel, is refused (§3.2);
- it is an OAuth grant (`client_id` present) — a browser session token was
  never issued to the AI client and carries no consent for it (§4);
- it names an organization, because the workspace is derived from it.

Admission (is the org a workspace?) is checked per call in `server.py`, not
here, so an unadmitted user gets a readable refusal rather than a login loop.
"""

from __future__ import annotations

import asyncio

import jwt
from mcp.server.auth.provider import AccessToken

from app.core import auth
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _decode(token: str) -> dict:
    key = auth._jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        key.key,
        algorithms=["RS256"],
        issuer=auth._issuer(),
        audience=settings.mcp_resource_url,
        options={"require": ["exp", "iss", "sub", "aud"]},
    )


def _scopes(claims: dict) -> list[str]:
    raw = claims.get("scope") or claims.get("scp") or []
    return raw.split() if isinstance(raw, str) else [str(s) for s in raw]


class ClerkOAuthVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await asyncio.to_thread(_decode, token)
        except Exception as exc:  # any failure is a 401, never a 500
            logger.info("mcp: token refused (%s)", type(exc).__name__)
            return None
        if not claims.get("client_id"):
            logger.info("mcp: refused a token with no client_id (a session token?)")
            return None
        if not auth._org_id(claims):
            logger.info("mcp: refused a token with no org_id")
            return None
        return AccessToken(
            token=token,
            client_id=str(claims["client_id"]),
            scopes=_scopes(claims),
            expires_at=claims.get("exp"),
            subject=claims.get("sub"),
            resource=settings.mcp_resource_url,
            claims=claims,
        )
