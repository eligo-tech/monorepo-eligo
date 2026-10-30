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


async def test_a_proposal_stays_in_the_workspace_that_made_it() -> None:
    """PR 4: workspace A's proposal is invisible to B and cannot be decided by B.

    Created through /mcp as A's AI client; read and confirmed as B on the
    runtime role. On Postgres, B's pinned transaction must see zero of A's rows
    (RLS), not merely be filtered by the service's WHERE clause.
    """
    from sqlalchemy import select

    from app.core.database import SessionLocal, current_tenant_var
    from app.domain.proposals import service as proposals
    from app.domain.proposals.models import AgentProposal

    suffix = uuid.uuid4().hex[:8]
    org_a, org_b = f"org_pa_{suffix}", f"org_pb_{suffix}"
    tenant_a = await _workspace(org_a, f"Clara {suffix}")
    tenant_b = await _workspace(org_b, f"Dirk {suffix}")

    listed = await _call("candidates_list", {"limit": 100}, token=_token(org_id=org_a))
    [clara] = [c for c in listed["structuredContent"]["candidates"]
               if c["full_name"] == f"Clara {suffix}"]
    made = await _call("notes_propose_candidate_note",
                       {"candidate_id": clara["id"], "text": "Start im März"},
                       token=_token(org_id=org_a))
    assert made.get("isError") is not True, made
    proposal_id = uuid.UUID(made["structuredContent"]["id"])

    token = current_tenant_var.set(str(tenant_b))
    try:
        async with SessionLocal() as s:
            # Raw query, no tenant filter: only RLS stands between B and A's row.
            seen = (await s.execute(select(AgentProposal.id))).scalars().all()
            assert proposal_id not in seen
            with pytest.raises(proposals.ProposalNotFound):
                await proposals.confirm(s, tenant_id=tenant_b, proposal_id=proposal_id,
                                        user_id="intruder", name="B")
    finally:
        current_tenant_var.reset(token)

    # Control: A's own pinned session sees it.
    token = current_tenant_var.set(str(tenant_a))
    try:
        async with SessionLocal() as s:
            assert proposal_id in (await s.execute(select(AgentProposal.id))).scalars().all()
    finally:
        current_tenant_var.reset(token)


async def test_a_step_with_dates_confirms_on_postgres_without_false_staleness() -> None:
    """The snapshot is compared as text. On Postgres the step's timestamps come
    back through asyncpg, so a step that already HAS a date is the case that
    could be wrongly refused as stale. Proposed over /mcp, confirmed as A."""
    import datetime as dt

    from sqlalchemy import select

    from app.core.database import SessionLocal, current_tenant_var
    from app.domain.jobs.models import Job
    from app.domain.pipeline import service as pipeline
    from app.domain.pipeline.models import Application, ProcessStep
    from app.domain.proposals import service as proposals

    suffix = uuid.uuid4().hex[:8]
    org = f"org_ps_{suffix}"
    tenant = await _workspace(org, f"Eva {suffix}")
    async with AdminSessionLocal() as s:
        await s.execute(text(_PIN), {"t": str(tenant)})
        cand = (await s.execute(select(Candidate).where(Candidate.tenant_id == tenant))).scalars().first()
        job = Job(tenant_id=tenant, title="Lead")
        s.add(job)
        await s.flush()
        app = Application(tenant_id=tenant, candidate_id=cand.id, job_id=job.id)
        s.add(app)
        await s.commit()
        app_id = app.id
        await s.execute(text(_PIN), {"t": str(tenant)})
        await pipeline.set_step(s, tenant_id=tenant, application_id=app_id, step_key="interview",
                                scheduled_at=dt.datetime(2026, 11, 3, 9, 0, tzinfo=dt.UTC))

    made = await _call("pipeline_propose_step",
                       {"application_id": str(app_id), "step_key": "interview",
                        "done_at": "2026-11-03T10:30:00+01:00", "outcome": "pass"},
                       token=_token(org_id=org))
    assert made.get("isError") is not True, made
    pid = uuid.UUID(made["structuredContent"]["id"])

    token = current_tenant_var.set(str(tenant))
    try:
        async with SessionLocal() as s:
            row = await proposals.confirm(s, tenant_id=tenant, proposal_id=pid, user_id="u", name="A")
            assert row.status == "confirmed"
            step = await s.scalar(select(ProcessStep).where(ProcessStep.application_id == app_id))
            assert step.outcome == "pass" and step.done_at is not None
    finally:
        current_tenant_var.reset(token)
