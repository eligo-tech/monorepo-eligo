"""Does the money work — and the distinction the old filter could not make.

`data/examples/KandidatenInfo.txt` does this comparison by hand: "aktuell
>105k; Minimum 92–95k, Wunsch ~100k. Über der GE-Orientierung (~90k) …
ausdrücklich verhandlungs- und stufenmodell-bereit – das entschärft es". That
candidate is scored 8/10 and called a rare full match.

The hard filter used to exclude him outright, because his WISH exceeded the
band. These tests pin the rule that replaced it: only the floor excludes.
"""

from __future__ import annotations

import uuid

from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus, WorkPermitStatus
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.matching.service import apply_hard_filters
from app.domain.matching.salary import salary_fit
from app.domain.pipeline import service as pipeline_service
from app.domain.pipeline.models import Application

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def test_a_wish_above_the_band_is_a_conversation_not_an_exclusion() -> None:
    fit = salary_fit(minimum=92000, wish=100000, job_min=80000, job_max=95000)
    assert fit.status == "negotiable"
    assert fit.excludes is False
    # The sentence says both halves: what is over, and what still fits.
    assert "100.000 €" in fit.detail and "Minimum 92.000 € passt" in fit.detail


def test_only_the_floor_excludes() -> None:
    fit = salary_fit(minimum=98000, wish=110000, job_min=80000, job_max=95000)
    assert fit.status == "above_band" and fit.excludes is True


def test_inside_the_band_says_so_plainly() -> None:
    fit = salary_fit(minimum=70000, wish=90000, job_min=80000, job_max=95000)
    assert fit.status == "fits"
    assert "90.000 € im Band (80.000–95.000 €)" == fit.detail


def test_missing_numbers_never_read_as_a_fit() -> None:
    """An unknown is not a pass. A cockpit that shows "im Band" for a
    candidate who never named a figure has invented the figure."""
    assert salary_fit(minimum=None, wish=None, job_min=80000, job_max=95000).status == (
        "unknown"
    )
    # No ceiling on the mandate means nothing to breach.
    assert salary_fit(minimum=200000, wish=None, job_min=None, job_max=None).status == (
        "unknown"
    )


async def test_the_matcher_keeps_the_negotiable_candidate() -> None:
    """THE regression. Before the floor existed this candidate was dropped."""
    candidate = Candidate(
        tenant_id=TENANT,
        full_name="Senior Backend",
        salary_minimum=92000,
        salary_expectation=100000,
        work_permit=WorkPermitStatus.CITIZEN,
        skills=[],
    )
    job = Job(
        tenant_id=TENANT,
        title="Java Dev",
        salary_min=80000,
        salary_max=95000,
        # Column defaults are applied on INSERT; these objects never reach the
        # DB, so the list fields are spelled out rather than left None.
        must_have_skills=[],
        required_certifications=[],
    )
    assert apply_hard_filters(candidate, job) == []

    candidate.salary_minimum = 98000  # the floor itself is over the ceiling
    failures = apply_hard_filters(candidate, job)
    assert failures and "98000" in failures[0]


async def test_the_per_job_view_shows_the_same_verdict() -> None:
    """One rule, two readers: the cockpit must never say "verhandelbar" for
    someone the matcher dropped."""
    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name="EM Software", is_client=True)
        candidate = Candidate(
            tenant_id=TENANT,
            full_name="Senior Backend",
            salary_minimum=92000,
            salary_expectation=100000,
        )
        s.add_all([company, candidate])
        await s.flush()
        job = Job(
            tenant_id=TENANT,
            title="Java Dev",
            client_company_id=company.id,
            salary_min=80000,
            salary_max=95000,
        )
        s.add(job)
        await s.flush()
        app = Application(
            tenant_id=TENANT,
            candidate_id=candidate.id,
            job_id=job.id,
            status=ApplicationStatus.PRESENTED,
        )
        s.add(app)
        await s.commit()
        await pipeline_service.set_step(
            s, tenant_id=TENANT, application_id=app.id, step_key="vorgestellt",
            outcome="pass",
        )
        grouped = await pipeline_service.processes(s, tenant_id=TENANT)

    fit = grouped[0]["candidates"][0]["salary_fit"]
    assert fit["status"] == "negotiable"
    assert fit["minimum"] == 92000 and fit["wish"] == 100000


async def test_a_candidate_without_figures_carries_no_verdict() -> None:
    async with SessionLocal() as s:
        candidate = Candidate(tenant_id=TENANT, full_name="Ohne Angabe")
        s.add(candidate)
        await s.flush()
        job = Job(tenant_id=TENANT, title="Java Dev", salary_max=95000)
        s.add(job)
        await s.flush()
        app = Application(
            tenant_id=TENANT, candidate_id=candidate.id, job_id=job.id,
            status=ApplicationStatus.PRESENTED,
        )
        s.add(app)
        await s.commit()
        await pipeline_service.set_step(
            s, tenant_id=TENANT, application_id=app.id, step_key="vorgestellt",
            outcome="pass",
        )
        grouped = await pipeline_service.processes(s, tenant_id=TENANT)

    assert grouped[0]["candidates"][0]["salary_fit"] is None
