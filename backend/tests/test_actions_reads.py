"""The read actions an AI client gets: right workspace, sources attached, no contact data.

Two workspaces are seeded. Workspace A's candidate carries values that must
never leave through an AI client — e-mail, phone, salary, free-text notes —
each a unique marker string, so the check is "does the marker appear anywhere
in the serialized output", not "is there a field called email". A renamed
field would pass the second check and fail the first.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest

from app.actions import catalog  # noqa: F401 — registers the actions
from app.actions.core import REGISTRY, ActionContext, ActionNotFound
from app.core.auth import RECRUITER, Actor
from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.hub.models import HubCompany, HubJobPosting
from app.domain.jobs.models import Job
from app.domain.pipeline.models import Application

SECRETS = {
    "email": "anna.marker@secret.example",
    "phone": "+49 170 5550199",
    "notes": "SECRET-NOTE-7731",
    "motivation": "SECRET-MOTIVATION-4410",
    "salary": "98765",
    "street": "Geheimstrasse 12",
}

READS = [
    "candidates.list",
    "candidates.get",
    "jobs.list",
    "jobs.get",
    "matching.for_job",
    "pipeline.processes",
    "reporting.overview",
    "reporting.funnel",
    "market.postings",
]


@pytest.fixture
async def seeded() -> dict:
    a, b = uuid.uuid4(), uuid.uuid4()
    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        anna = Candidate(
            tenant_id=a,
            full_name="Anna Schmidt",
            email=SECRETS["email"],
            phone=SECRETS["phone"],
            street=SECRETS["street"],
            motivation=SECRETS["motivation"],
            other_notes=SECRETS["notes"],
            salary_expectation=int(SECRETS["salary"]),
            current_title="Data Engineer",
            city="Berlin",
            skills=["python", "sql"],
            availability_weeks=2,
            work_permit="citizen",
        )
        bob = Candidate(tenant_id=a, full_name="Bob Weber", city="Hamburg", skills=["java"])
        other = Candidate(tenant_id=b, full_name="Other Workspace Person", skills=["python"])
        job = Job(tenant_id=a, title="Senior Data Engineer", must_have_skills=["python"])
        other_job = Job(tenant_id=b, title="Other Workspace Job")
        s.add_all([anna, bob, other, job, other_job])
        await s.flush()
        s.add(Application(tenant_id=a, candidate_id=anna.id, job_id=job.id, notes=SECRETS["notes"]))
        company = HubCompany(
            name="Public Hiring GmbH",
            normalized_name="public hiring",
            dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place",
            source="test",
            first_seen_at=now,
            last_seen_at=now,
        )
        s.add(company)
        await s.flush()
        s.add(
            HubJobPosting(
                hub_company_id=company.id,
                title="Data Engineer (m/w/d)",
                city="Berlin",
                source="test",
                source_url="https://jobs.example/1",
                external_id="ext-1",
                content_hash="ext-1",
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        await s.commit()
        return {
            "a": a,
            "b": b,
            "anna": anna.id,
            "bob": bob.id,
            "other": other.id,
            "job": job.id,
            "other_job": other_job.id,
        }


def _agent(tenant_id: uuid.UUID) -> Actor:
    return Actor(
        tenant_id=tenant_id,
        user_id="user_1",
        name="Test",
        role=RECRUITER,
        role_known=True,
        kind="agent",
        client_id="client_1",
    )


async def _call(name: str, tenant_id: uuid.UUID, args: dict) -> dict:
    async with SessionLocal() as s:
        out = await REGISTRY.invoke(name, ActionContext(session=s, actor=_agent(tenant_id)), args)
    return out.model_dump(mode="json")


def _args(name: str, seeded: dict) -> dict:
    return {
        "candidates.get": {"candidate_id": str(seeded["anna"])},
        "jobs.get": {"job_id": str(seeded["job"])},
        "matching.for_job": {"job_id": str(seeded["job"])},
    }.get(name, {})


def test_the_catalog_is_exactly_the_approved_reads() -> None:
    assert {s.name for s in REGISTRY.agent_exposed()} == set(READS)


@pytest.mark.parametrize("name", READS)
async def test_every_read_answers_and_names_its_sources(seeded, name) -> None:
    out = await _call(name, seeded["a"], _args(name, seeded))
    assert out["sources"], f"{name} returned no sources"
    for source in out["sources"]:
        assert source["type"] and source["id"]


@pytest.mark.parametrize("name", READS)
async def test_no_read_leaks_contact_data_salary_or_notes(seeded, name) -> None:
    text = json.dumps(await _call(name, seeded["a"], _args(name, seeded)))
    leaked = [k for k, marker in SECRETS.items() if marker in text]
    assert not leaked, f"{name} leaked {leaked}"


@pytest.mark.parametrize("name", READS)
async def test_no_read_shows_another_workspace(seeded, name) -> None:
    text = json.dumps(await _call(name, seeded["a"], _args(name, seeded)))
    for foreign in ("other", "other_job"):
        assert str(seeded[foreign]) not in text
    assert "Other Workspace" not in text


async def test_get_of_another_workspaces_record_is_not_found(seeded) -> None:
    with pytest.raises(ActionNotFound):
        await _call("candidates.get", seeded["a"], {"candidate_id": str(seeded["other"])})
    with pytest.raises(ActionNotFound):
        await _call("jobs.get", seeded["a"], {"job_id": str(seeded["other_job"])})


async def test_candidate_filters_apply_before_the_limit(seeded) -> None:
    out = await _call("candidates.list", seeded["a"], {"skill": "PYTHON", "city": "berlin"})
    assert [c["full_name"] for c in out["candidates"]] == ["Anna Schmidt"]
    out = await _call("candidates.list", seeded["a"], {"available_within_weeks": 1})
    assert out["candidates"] == []  # Anna is 2 weeks out, Bob unknown
    out = await _call("candidates.list", seeded["a"], {"limit": 1})
    assert len(out["candidates"]) == 1 and out["total"] == 2 and out["truncated"]


async def test_matching_keeps_the_hard_filter(seeded) -> None:
    out = await _call("matching.for_job", seeded["a"], {"job_id": str(seeded["job"])})
    names = [m["candidate_name"] for m in out["matches"]]
    assert names == ["Anna Schmidt"]  # Bob lacks the must-have skill


async def test_pipeline_shows_the_process(seeded) -> None:
    out = await _call("pipeline.processes", seeded["a"], {})
    [process] = out["processes"]
    assert process["job_title"] == "Senior Data Engineer"
    assert [c["candidate_name"] for c in process["candidates"]] == ["Anna Schmidt"]
