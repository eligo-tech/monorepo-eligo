"""Two workspaces through `/mcp` on a real Postgres, as the runtime role.

The SQLite suite proves the query layer. This proves the MCP path pins the
workspace for RLS: on Postgres an unpinned transaction sees ZERO rows (fail
closed), so "user A sees exactly A's candidates" is two claims at once —
the GUC was pinned (otherwise nothing), and pinned to A (otherwise B's).

Runs in the CI "RLS on Postgres" job; skipped on SQLite.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AdminSessionLocal, admin_engine, engine
from app.domain.candidates.models import Candidate
from app.domain.features import service as features
from app.domain.tenants import service as tenants
from tests.test_mcp_endpoint import _call, _clerk, _token  # noqa: F401 — _clerk is autouse

pytestmark = pytest.mark.skipif(not settings.is_postgres, reason="RLS exists only on Postgres")

_PIN = "SELECT set_config('app.current_tenant', :t, true)"


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Keep the schema and its policies (see test_rls_postgres.py); dispose pools."""
    yield
    await engine.dispose()
    await admin_engine.dispose()


async def _workspace(org: str, person: str) -> uuid.UUID:
    async with AdminSessionLocal() as s:
        tenant = await tenants.get_or_create(s, clerk_org_id=org, name=org)
        await s.commit()
        await s.execute(text(_PIN), {"t": str(tenant.id)})
        s.add(Candidate(tenant_id=tenant.id, full_name=person))
        await s.commit()
        await s.execute(text(_PIN), {"t": str(tenant.id)})
        await features.accept(
            s,
            tenant_id=tenant.id,
            key="mcp",
            terms_version=features.FEATURES["mcp"].terms_version,
            actor_name="Admin",
        )
        return tenant.id


async def test_each_user_sees_only_their_own_workspace() -> None:
    suffix = uuid.uuid4().hex[:8]
    org_a, org_b = f"org_a_{suffix}", f"org_b_{suffix}"
    await _workspace(org_a, f"Alice {suffix}")
    await _workspace(org_b, f"Bob {suffix}")

    for org, mine, theirs in ((org_a, "Alice", "Bob"), (org_b, "Bob", "Alice")):
        result = await _call("candidates_list", {"limit": 100}, token=_token(org_id=org))
        assert result.get("isError") is not True, result
        names = [c["full_name"] for c in result["structuredContent"]["candidates"]]
        assert f"{mine} {suffix}" in names, f"{org} saw nothing — workspace not pinned"
        assert f"{theirs} {suffix}" not in names, f"{org} saw the other workspace"
