"""Who moved this candidate — the token's answer, not the browser's.

`POST /applications/{id}/status` and `/stage` took an `actor` string **from the
request body**, defaulting to `"recruiter"`, and wrote it into the
application's history. `core/auth.py` says of the pattern it replaced: "The
browser used to be asked who it was, which is not a question with a
trustworthy answer." These two endpoints were still asking.

They also recorded only a display name. Two people share a name and a rename
rewrites every line of history holding the old one, so the stable Clerk `sub`
goes in alongside it.
"""

from __future__ import annotations

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus, PipelineStage
from app.domain.jobs.models import Job
from app.domain.pipeline.models import Application
from app.domain.tenants import service as tenants_service

ORG = "org_attribution"


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def signed_in_as_a_named_person(monkeypatch):
    from app.core import auth as auth_module

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(
        auth_module,
        "verify_token",
        lambda _t: {"org_id": ORG, "sub": "user_thomas", "name": "Thomas Bausch"},
    )


async def _an_application() -> str:
    async with SessionLocal() as session:
        tenant = await tenants_service.get_or_create(session, clerk_org_id=ORG)
        candidate = Candidate(tenant_id=tenant.id, full_name="Kandidatin")
        job = Job(tenant_id=tenant.id, title="Mandat", status="open")
        session.add_all([candidate, job])
        await session.flush()
        application = Application(
            tenant_id=tenant.id,
            candidate_id=candidate.id,
            job_id=job.id,
            status=ApplicationStatus.SOURCED,
            stage=PipelineStage.BEWERBUNG,
            created_at=dt.datetime.now(dt.UTC),
        )
        session.add(application)
        await session.commit()
        return str(application.id)


async def test_the_history_names_the_person_on_the_token(
    signed_in_as_a_named_person,
) -> None:
    await create_all()
    application_id = await _an_application()

    async with _api() as client:
        resp = await client.post(
            f"{settings.api_v1_prefix}/pipeline/applications/{application_id}/status",
            headers={"Authorization": "Bearer session"},
            json={"to_status": "screened"},
        )

    assert resp.status_code == 200, resp.text
    entry = resp.json()["history"][-1]
    assert entry["actor"] == "Thomas Bausch"
    # The stable id, which is what a later question actually has to match on.
    assert entry["actor_user_id"] == "user_thomas"


async def test_an_actor_in_the_request_body_is_ignored(
    signed_in_as_a_named_person,
) -> None:
    """The whole point. Sending somebody else's name must change nothing."""
    await create_all()
    application_id = await _an_application()

    async with _api() as client:
        resp = await client.post(
            f"{settings.api_v1_prefix}/pipeline/applications/{application_id}/stage",
            headers={"Authorization": "Bearer session"},
            json={"to_stage": "long_list", "actor": "Jonas Albrecht"},
        )

    assert resp.status_code == 200, resp.text
    entry = resp.json()["history"][-1]
    assert entry["actor"] == "Thomas Bausch", (
        "the request body chose the actor — the browser is being believed"
    )
    assert entry["actor_user_id"] == "user_thomas"
