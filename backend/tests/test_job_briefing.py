"""Briefing-Bewertung (ELI-47): which of the ten briefing points are geklärt.

Deterministic, no model: a point counts when its field holds a real value.
The score travels with every job payload, so the mandate page reads it from
the same response that carries the fields — one definition, in the backend.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.companies.models import Company
from app.domain.jobs import briefing, service
from app.domain.jobs.models import Job
from app.domain.jobs.schemas import JobCreate, JobRead, JobUpdate
from app.domain.managers.models import Manager
from app.domain.verification.models import EnrichmentRecord

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
API = "/api/v1/jobs"

ALL_KEYS = [
    "tasks",
    "must_have",
    "nice_to_have",
    "salary",
    "location",
    "start",
    "team_size",
    "contact",
    "interview_process",
    "vacancy_reason",
]


def _job(**fields) -> Job:
    base = dict(
        tenant_id=TENANT,
        title="Java Dev",
        must_have_skills=[],
        nice_to_have_skills=[],
        required_certifications=[],
    )
    base.update(fields)
    return Job(**base)


def test_the_ten_points_are_fixed_and_ordered() -> None:
    assert [p.key for p in briefing.POINTS] == ALL_KEYS


def test_an_empty_mandate_has_nothing_clarified() -> None:
    result = briefing.assess(_job())
    assert (result.done, result.total) == (0, 10)
    assert result.missing == ALL_KEYS


def test_blank_text_and_blank_list_items_do_not_count() -> None:
    result = briefing.assess(
        _job(
            tasks="   ",
            must_have_skills=["", "  "],
            team_size="—",
            location="",
            vacancy_reason="-",
        )
    )
    assert result.done == 0


def test_a_complete_briefing_scores_ten_of_ten() -> None:
    result = briefing.assess(
        _job(
            tasks="Plattform bauen",
            must_have_skills=["Java"],
            nice_to_have_skills=["Kafka"],
            salary_max=95000,
            location="München · 2 Tage remote",
            start_date="zum 1. März",
            team_size="6 Entwickler",
            manager_id=uuid.uuid4(),
            interview_process="2 Runden: Fachgespräch, Case",
            vacancy_reason="Neue Stelle (Wachstum)",
        )
    )
    assert (result.done, result.total, result.missing) == (10, 10, [])


def test_one_side_of_the_band_is_a_salary_frame() -> None:
    assert "salary" not in briefing.assess(_job(salary_min=60000)).missing
    assert "salary" in briefing.assess(_job()).missing


async def test_the_api_returns_the_score_and_new_fields_are_editable_with_receipts() -> None:
    async with SessionLocal() as s:
        row = await service.create_job(s, data=JobCreate(tenant_id=TENANT, title="Java Dev"))
        job_id = row.id

    from app.main import app as fastapi_app

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t") as client:
        before = await client.get(f"{API}/{job_id}")
        assert before.status_code == 200
        assert before.json()["briefing"] == {"done": 0, "total": 10, "missing": ALL_KEYS}

        patched = await client.patch(
            f"{API}/{job_id}",
            json={
                "tasks": "Plattform bauen",
                "nice_to_have_skills": ["Kafka"],
                "start_date": "sofort",
                "team_size": "6",
                "interview_process": "2 Runden",
                "vacancy_reason": "Nachfolge",
            },
        )
        assert patched.status_code == 200
        body = patched.json()
        assert body["tasks"] == "Plattform bauen"
        assert body["nice_to_have_skills"] == ["Kafka"]
        assert body["briefing"]["done"] == 6
        assert body["briefing"]["missing"] == ["must_have", "salary", "location", "contact"]

        listed = await client.get(API)
        assert listed.json()[0]["briefing"]["done"] == 6

    # Same verified path as every other mandate field: one record per field.
    async with SessionLocal() as s:
        fields = set(
            (
                await s.execute(
                    select(EnrichmentRecord.field).where(
                        EnrichmentRecord.entity_type == "job",
                        EnrichmentRecord.entity_id == job_id,
                    )
                )
            ).scalars()
        )
    assert {
        "tasks",
        "nice_to_have_skills",
        "start_date",
        "team_size",
        "interview_process",
        "vacancy_reason",
    } <= fields


async def test_free_text_points_are_bounded() -> None:
    import pytest
    from pydantic import ValidationError

    for field in ("tasks", "interview_process", "vacancy_reason"):
        with pytest.raises(ValidationError):
            JobUpdate(**{field: "x" * 4001})
        with pytest.raises(ValidationError):
            JobCreate(title="Dev", **{field: "x" * 4001})
        JobUpdate(**{field: "x" * 4000})


async def test_nice_to_have_cannot_be_nulled() -> None:
    async with SessionLocal() as s:
        row = await service.create_job(
            s, data=JobCreate(tenant_id=TENANT, title="Dev", nice_to_have_skills=["Go"])
        )
        updated = await service.update_job(
            s, tenant_id=TENANT, job_id=row.id, patch=JobUpdate(nice_to_have_skills=None)
        )
    assert updated.nice_to_have_skills == ["Go"]


async def test_a_copy_keeps_the_role_but_not_this_search_s_timing_or_reason() -> None:
    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name="EM Software", is_client=True)
        s.add(company)
        await s.flush()
        manager = Manager(tenant_id=TENANT, full_name="Frau X", company_id=company.id)
        s.add(manager)
        await s.commit()
        row = await service.create_job(
            s,
            data=JobCreate(
                tenant_id=TENANT,
                title="Dev",
                client_company_id=company.id,
                manager_id=manager.id,
                tasks="Plattform",
                nice_to_have_skills=["Go"],
                team_size="6",
                interview_process="2 Runden",
                start_date="sofort",
                vacancy_reason="Nachfolge",
            ),
        )
        copy = await service.copy_job(s, tenant_id=TENANT, job_id=row.id)
    read = JobRead.model_validate(copy)
    assert (read.tasks, read.nice_to_have_skills, read.team_size, read.interview_process) == (
        "Plattform",
        ["Go"],
        "6",
        "2 Runden",
    )
    assert read.start_date is None and read.vacancy_reason is None
    assert set(read.briefing.missing) == {"must_have", "salary", "location", "start", "vacancy_reason"}
