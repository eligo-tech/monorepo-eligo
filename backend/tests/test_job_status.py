"""Two mandate states, and the door that only opens one way (ELI-7).

The ticket is three sentences from the recruiters, and two of them are about
what must NOT happen:

* "aktiv / inaktiv" — two words, not three and not four.
* "inaktiv kann nicht wieder geöffnet werden, muss neu angelegt werden."
* "alte jobs als Kopie wiederverwenden."

So the tests here are mostly about the seams: the spellings already in the
record, the one transition that is refused, the nightly import that would
undo it, and what a copy must not take with it.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.common.enums import (
    LIVE_JOB_STATUSES,
    RETIRED_JOB_STATUSES,
    JobStatus,
    job_status_spellings,
    normalise_job_status,
)
from app.domain.companies.models import Company
from app.domain.jobs import service
from app.domain.jobs.models import Job
from app.domain.jobs.schemas import JobCreate, JobUpdate
from app.domain.managers.models import Manager
from app.domain.pipeline.models import Application

TENANT = settings.default_tenant_id
API = f"{settings.api_v1_prefix}/jobs"


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _a_mandate(**kwargs) -> Job:
    """A mandate with a filled-in Suchprofil, which is what a copy is for."""
    async with SessionLocal() as session:
        company = Company(tenant_id=TENANT, name="Kunde GmbH")
        session.add(company)
        await session.flush()
        manager = Manager(
            tenant_id=TENANT, company_id=company.id, full_name="Petra Sommer"
        )
        session.add(manager)
        await session.flush()
        job = await service.create_job(
            session,
            data=JobCreate(
                tenant_id=TENANT,
                title=kwargs.pop("title", "Java Entwickler"),
                client_company_id=company.id,
                manager_id=manager.id,
                location="Nürnberg",
                location_radius_km=50,
                must_have_skills=["Java", "Spring"],
                required_certifications=["SCRUM"],
                requires_work_permit=True,
                salary_min=85000,
                salary_max=95000,
                **kwargs,
            ),
        )
        return job


# --- the vocabulary ------------------------------------------------------


def test_the_two_states_are_the_ones_the_ticket_names() -> None:
    assert [s.value for s in JobStatus] == ["active", "inactive"]


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("open", "active"),  # 61 rows
        ("closed", "inactive"),  # 18 rows, written by the aiFind importer
        ("OPEN", "active"),
        (" closed ", "inactive"),
        ("active", "active"),
        ("inactive", "inactive"),
        (None, "active"),
        ("", "active"),
    ],
)
def test_every_spelling_in_the_record_resolves(stored, expected) -> None:
    assert normalise_job_status(stored) == expected


@pytest.mark.parametrize("stored", sorted(RETIRED_JOB_STATUSES))
def test_a_spelling_nobody_ever_wrote_is_not_quietly_folded(stored) -> None:
    """on_hold / filled / cancelled were in the code and never in the record.

    They pass through unchanged, which is what makes `update_job` able to
    refuse them. Folding `filled` into `inactive` would be tidier and would
    silently discard the only thing the sender said that the record cannot
    hold — the reason it closed.
    """
    assert normalise_job_status(stored) == stored


def test_a_row_that_still_says_open_counts_as_live_business() -> None:
    """`LIVE_JOB_STATUSES` feeds the cockpit's mandate figure and a manager's
    `open_job_count`. Both read the column, so a row migration 0039 has not
    reached must not drop out of "how much is running" — that is a wrong
    number nobody reports, because it looks right.
    """
    assert LIVE_JOB_STATUSES == {"active", "open"}
    assert job_status_spellings("inactive") == {"inactive", "closed"}


def test_the_migration_rewrites_exactly_what_the_normaliser_folds() -> None:
    """Migration 0039 carries its own copy of the mapping, because a
    migration must not import application code that will move on without it.

    Two copies drift. This is the check that notices: the day somebody adds a
    stored spelling to the normaliser, the rows holding it stop being
    rewritten and start depending on a read-time fold forever.
    """
    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0039_jobs_active_or_inactive.py"
    ).read_text()
    rewrite: dict[str, str] | None = None
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "_REWRITE" for t in node.targets
        ):
            rewrite = ast.literal_eval(node.value)
    assert rewrite is not None, "0039 no longer declares _REWRITE"
    assert rewrite == {
        spelling: normalise_job_status(spelling) for spelling in rewrite
    }
    # Every stored spelling the normaliser knows is actually migrated.
    folded = {
        spelling
        for spelling in ("open", "closed")
        if normalise_job_status(spelling) != spelling
    }
    assert folded == set(rewrite)


# --- inactive is a one-way door ------------------------------------------


async def test_an_inactive_mandate_cannot_be_reopened() -> None:
    """The ticket, verbatim: "inaktiv kann nicht wieder geöffnet werden"."""
    await create_all()
    job = await _a_mandate()
    async with SessionLocal() as s:
        await service.update_job(
            s, tenant_id=TENANT, job_id=job.id, patch=JobUpdate(status="inactive")
        )
    async with SessionLocal() as s:
        with pytest.raises(service.ReopeningRefused):
            await service.update_job(
                s, tenant_id=TENANT, job_id=job.id, patch=JobUpdate(status="active")
            )


async def test_a_row_that_still_says_closed_cannot_be_reopened_either() -> None:
    """The check reads the CURRENT value through the normaliser.

    18 mandates say "closed" until migration 0039 runs. Comparing the raw
    column against "inactive" would let every one of them be reopened, and
    the rule would hold only for mandates closed after the deploy.
    """
    await create_all()
    job = await _a_mandate()
    async with SessionLocal() as s:
        row = await s.get(Job, job.id)
        row.status = "closed"  # as the aiFind importer wrote it
        await s.commit()
    async with SessionLocal() as s:
        with pytest.raises(service.ReopeningRefused):
            await service.update_job(
                s, tenant_id=TENANT, job_id=job.id, patch=JobUpdate(status="open")
            )


async def test_reopening_is_a_409_and_not_a_422() -> None:
    """The payload is valid and would be accepted on any other mandate. What
    refuses it is the state this one is in, which is what 409 means."""
    await create_all()
    job = await _a_mandate()
    async with _api() as client:
        closed = await client.patch(f"{API}/{job.id}", json={"status": "inactive"})
        reopened = await client.patch(f"{API}/{job.id}", json={"status": "active"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "inactive"
    assert reopened.status_code == 409, reopened.text


async def test_setting_inactive_on_an_inactive_mandate_is_not_an_error() -> None:
    """The Suchprofil editor sends `status` on every save. If saving a closed
    mandate's salary band tripped the rule, the rule would have made those
    mandates uneditable — which is the bug ELI-7's first half fixed."""
    await create_all()
    job = await _a_mandate(status="inactive")
    async with SessionLocal() as s:
        again = await service.update_job(
            s,
            tenant_id=TENANT,
            job_id=job.id,
            patch=JobUpdate(status="inactive", salary_max=99000),
        )
    assert again is not None
    assert (again.status, again.salary_max) == ("inactive", 99000)


# --- the way back: a copy ------------------------------------------------


async def test_a_copy_carries_the_suchprofil() -> None:
    """The band, the radius, the Muss-Kriterien and the Ansprechpartner are
    the hour of work nobody wants to repeat."""
    await create_all()
    source = await _a_mandate()
    async with SessionLocal() as s:
        copy = await service.copy_job(s, tenant_id=TENANT, job_id=source.id)

    assert copy is not None
    assert copy.id != source.id
    for field in service._COPIED_FIELDS:
        assert getattr(copy, field) == getattr(source, field), field


async def test_a_copy_of_a_finished_mandate_arrives_active() -> None:
    """The main case, not an edge one: the role is being worked again."""
    await create_all()
    source = await _a_mandate(status="inactive")
    async with SessionLocal() as s:
        copy = await service.copy_job(s, tenant_id=TENANT, job_id=source.id)
    assert copy.status == "active"
    assert copy.copied_from_job_id == source.id


async def test_a_copy_does_not_carry_the_ats_identity() -> None:
    """`external_id` is unique per (tenant, source, id). A copy holding it
    would make the next nightly import write into the copy instead of the row
    it imported — and the import also sets `status`, so the reopening rule
    would be undone through the back door."""
    await create_all()
    source = await _a_mandate()
    async with SessionLocal() as s:
        row = await s.get(Job, source.id)
        row.external_id, row.external_source = "j1", "aifind"
        await s.commit()
    async with SessionLocal() as s:
        copy = await service.copy_job(s, tenant_id=TENANT, job_id=source.id)
    assert (copy.external_id, copy.external_source) == (None, None)


async def test_a_copy_does_not_carry_the_pipeline() -> None:
    """A copy is a fresh search, not a fork of a history that happened to
    other people. Carrying the applications over would put a candidate who
    was rejected last year into a shortlist as if they were proposed today.
    """
    await create_all()
    source = await _a_mandate()
    async with SessionLocal() as s:
        candidate = Candidate(tenant_id=TENANT, full_name="Jana Keller")
        s.add(candidate)
        await s.flush()
        s.add(
            Application(
                tenant_id=TENANT, job_id=source.id, candidate_id=candidate.id
            )
        )
        await s.commit()

    async with SessionLocal() as s:
        copy = await service.copy_job(s, tenant_id=TENANT, job_id=source.id)
        on_copy = (
            await s.execute(
                select(Application).where(Application.job_id == copy.id)
            )
        ).scalars().all()
        on_source = (
            await s.execute(
                select(Application).where(Application.job_id == source.id)
            )
        ).scalars().all()
    assert on_copy == []
    assert len(on_source) == 1


def test_a_copied_list_is_a_new_object() -> None:
    """`must_have_skills` is a mutable list, and the two rows must not share
    the object: appending to one mandate's hard filters would change who a
    DIFFERENT client is shown, from a screen that never mentioned them.

    Tested directly, because it is not observable through the API — every
    write path today REPLACES the list rather than mutating it, so a shared
    object would behave identically until the first `.append`. A test routed
    through `update_job` passes with the guard removed; this one does not.
    """
    original = ["Java", "Spring"]
    assert service._fresh(original) == original
    assert service._fresh(original) is not original
    assert service._fresh("Nürnberg") == "Nürnberg"


async def test_editing_a_copys_criteria_leaves_the_original_alone() -> None:
    """The product property the guard above protects, end to end."""
    await create_all()
    source = await _a_mandate()
    async with SessionLocal() as s:
        copy = await service.copy_job(s, tenant_id=TENANT, job_id=source.id)
        updated = await service.update_job(
            s,
            tenant_id=TENANT,
            job_id=copy.id,
            patch=JobUpdate(must_have_skills=["Kotlin"]),
        )
    assert updated.must_have_skills == ["Kotlin"]
    async with SessionLocal() as s:
        assert (await s.get(Job, source.id)).must_have_skills == ["Java", "Spring"]


async def test_a_copy_can_be_given_a_new_title() -> None:
    await create_all()
    source = await _a_mandate()
    async with SessionLocal() as s:
        copy = await service.copy_job(
            s, tenant_id=TENANT, job_id=source.id, title="  Java Entwickler (2027)  "
        )
    assert copy.title == "Java Entwickler (2027)"


async def test_the_copy_endpoint_needs_no_body() -> None:
    await create_all()
    source = await _a_mandate()
    async with _api() as client:
        created = await client.post(f"{API}/{source.id}/copy")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["id"] != str(source.id)
    assert body["status"] == "active"
    assert body["copied_from_job_id"] == str(source.id)


async def test_copying_a_mandate_that_is_not_in_this_workspace_is_a_404() -> None:
    await create_all()
    async with _api() as client:
        missing = await client.post(f"{API}/{uuid.uuid4()}/copy")
    assert missing.status_code == 404


# --- filtering ------------------------------------------------------------


async def test_the_status_filter_finds_rows_that_still_say_closed() -> None:
    await create_all()
    job = await _a_mandate()
    async with SessionLocal() as s:
        row = await s.get(Job, job.id)
        row.status = "closed"
        await s.commit()

    async with _api() as client:
        inactive = await client.get(API, params={"status": "inactive"})
        active = await client.get(API, params={"status": "active"})

    assert [r["id"] for r in inactive.json()] == [str(job.id)]
    # And it reads back in today's vocabulary, never "closed".
    assert inactive.json()[0]["status"] == "inactive"
    assert str(job.id) not in [r["id"] for r in active.json()]


async def test_the_filter_runs_in_the_database_not_over_the_first_page() -> None:
    """The half of ELI-7 that was missing. The list is capped, so filtering
    what already arrived shows "the inactive ones among the first N" and calls
    them the inactive ones. Ordered by title, so the one wanted row sits
    outside the page on purpose.
    """
    await create_all()
    for title in ("A Mandat", "B Mandat", "C Mandat"):
        await _a_mandate(title=title)
    wanted = await _a_mandate(title="Z Mandat", status="inactive")

    async with _api() as client:
        page = await client.get(API, params={"status": "inactive", "limit": 2})

    assert [r["id"] for r in page.json()] == [str(wanted.id)]
