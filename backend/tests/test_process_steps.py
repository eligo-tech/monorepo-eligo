"""The recruiter's tracker as data: nine steps, dates, and green/red verdicts.

Half of these run against the REAL document in `docs/process_design`, because
the mapping this code performs is a claim about that file — decoded from cell
fill colours, not headers — and a fixture I wrote myself could not falsify it.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import uuid
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus, PipelineStage
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.pipeline import service
from app.domain.pipeline.models import Application
from scripts.import_process_sheet import parse_sheet

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
SHEET = (
    pathlib.Path(__file__).parents[2]
    / "docs/process_design/Prozess_Recruiter_Cockpit_MVP.md.docx"
)


# --------------------------------------------------------------------------
# Reading the real tracker
# --------------------------------------------------------------------------


@pytest.mark.skipif(not SHEET.exists(), reason="process sheet not in this checkout")
def test_the_real_sheet_parses_to_its_16_candidates() -> None:
    rows = parse_sheet(SHEET, year=2026)
    assert len(rows) == 16
    assert {r["company"] for r in rows} == {
        "EM Software", "SSI", "KVB", "Computacenter", "Sixt", "KurtzErsa",
    }  # GOSA carries no candidates in this sheet


@pytest.mark.skipif(not SHEET.exists(), reason="process sheet not in this checkout")
def test_three_interview_rounds_survive_the_import() -> None:
    """Turgut Kaymal is the furthest-along candidate: presented 28.07., then
    three appointments. "IvT" is the recruiter's shorthand for Interviewtermin,
    so the third round is a step of its own rather than a lost cell."""
    row = next(
        r for r in parse_sheet(SHEET, year=2026) if r["candidate"] == "Turgut Kaymal"
    )
    steps = {s["step_key"]: s for s in row["steps"]}
    assert row["company"] == "SSI" and row["job"] == "Data 1442"
    # The sheet's clock is Berlin's: "14.08. um 10:30 Uhr" is 10:30 local,
    # which is 08:30 UTC. Storing 10:30 UTC would move every appointment.
    berlin = ZoneInfo("Europe/Berlin")
    assert steps["vorgestellt"]["done_at"].astimezone(berlin).date() == dt.date(2026, 7, 28)
    assert steps["interview"]["scheduled_at"] == dt.datetime(2026, 8, 14, 10, 30, tzinfo=berlin)
    assert steps["finaltermin"]["scheduled_at"] == dt.datetime(2026, 9, 17, 16, 0, tzinfo=berlin)
    assert steps["interviewtermin_3"]["scheduled_at"] == dt.datetime(2026, 9, 22, 8, 30, tzinfo=berlin)
    assert steps["feedback-1"]["outcome"] == "pass"


@pytest.mark.skipif(not SHEET.exists(), reason="process sheet not in this checkout")
def test_red_cells_become_outcomes_not_silence() -> None:
    """Three candidates are out in the sheet. A red cell is the reason a row
    stops moving, so it has to arrive as data — otherwise they read as stalled."""
    rows = {r["candidate"]: r for r in parse_sheet(SHEET, year=2026)}
    out = {
        name: [s["step_key"] for s in row["steps"] if s.get("outcome") == "out"]
        for name, row in rows.items()
        if any(s.get("outcome") == "out" for s in row["steps"])
    }
    assert out == {
        "Heiko Heitland": ["feedback-1"],          # client said no after presentation
        "Okan Karakaya": ["feedback-1"],
        "Alexander Rohleder": ["interview", "feedback-2"],  # no after the interview
    }


@pytest.mark.skipif(not SHEET.exists(), reason="process sheet not in this checkout")
def test_an_on_site_note_is_kept_beside_the_time() -> None:
    """"22.09 um 16:30 Uhr vor Ort" — the time is data, "vor Ort" is the note."""
    row = next(
        r for r in parse_sheet(SHEET, year=2026) if r["candidate"] == "Michael Hausl"
    )
    interview = next(s for s in row["steps"] if s["step_key"] == "interview")
    assert interview["scheduled_at"] == dt.datetime(
        2026, 9, 22, 16, 30, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert interview["note"] == "vor Ort"


@pytest.mark.skipif(not SHEET.exists(), reason="process sheet not in this checkout")
def test_company_headings_are_given_not_guessed() -> None:
    """Companies and mandates are indistinguishable in the file. Told that
    "Data 1442" is a company, the parser must believe it — which is the proof
    that nothing is being inferred from formatting."""
    rows = parse_sheet(SHEET, year=2026, companies=("EM Software", "Data 1442"))
    turgut = next(r for r in rows if r["candidate"] == "Turgut Kaymal")
    assert turgut["company"] == "Data 1442"


# --------------------------------------------------------------------------
# Steps in the record
# --------------------------------------------------------------------------


@pytest.fixture
async def application() -> uuid.UUID:
    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name="SSI", is_client=True)
        candidate = Candidate(tenant_id=TENANT, full_name="Turgut Kaymal")
        s.add_all([company, candidate])
        await s.flush()
        job = Job(tenant_id=TENANT, title="Data 1442", client_company_id=company.id)
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
        return app.id


async def test_the_board_stage_follows_the_checklist(application) -> None:
    """`Application.stage` is derived, never set twice: a Kanban column that
    disagrees with the process it summarises is worse than no column."""
    async with SessionLocal() as s:
        await service.set_step(
            s, tenant_id=TENANT, application_id=application,
            step_key="vorgestellt", done_at=dt.datetime(2026, 7, 28, tzinfo=dt.UTC),
        )
        app = await service.get_application(s, tenant_id=TENANT, application_id=application)
        assert app.stage == PipelineStage.PRESENTED

        await service.set_step(
            s, tenant_id=TENANT, application_id=application,
            step_key="interview", scheduled_at=dt.datetime(2026, 8, 14, 10, 30, tzinfo=dt.UTC),
        )
        await s.refresh(app)
        assert app.stage == PipelineStage.INTERVIEW

        await service.set_step(
            s, tenant_id=TENANT, application_id=application,
            step_key="vertrag", done_at=dt.datetime(2026, 9, 30, tzinfo=dt.UTC),
        )
        await s.refresh(app)
        assert app.stage == PipelineStage.PLACED


async def test_a_red_verdict_ends_the_process(application) -> None:
    async with SessionLocal() as s:
        await service.set_step(
            s, tenant_id=TENANT, application_id=application,
            step_key="vorgestellt", done_at=dt.datetime(2026, 9, 3, tzinfo=dt.UTC),
        )
        await service.set_step(
            s, tenant_id=TENANT, application_id=application,
            step_key="feedback-1", outcome="out",
        )
        app = await service.get_application(s, tenant_id=TENANT, application_id=application)
        assert app.stage == PipelineStage.REJECTED


async def test_setting_a_step_twice_updates_it(application) -> None:
    """The tracker is a checklist someone re-ticks, not an event log."""
    async with SessionLocal() as s:
        await service.set_step(
            s, tenant_id=TENANT, application_id=application,
            step_key="interview", scheduled_at=dt.datetime(2026, 9, 1, 9, 0, tzinfo=dt.UTC),
        )
        await service.set_step(
            s, tenant_id=TENANT, application_id=application,
            step_key="interview", scheduled_at=dt.datetime(2026, 9, 2, 11, 0, tzinfo=dt.UTC),
            note="verschoben",
        )
        steps = await service.list_steps(s, tenant_id=TENANT, application_id=application)
    assert len(steps) == 1
    # SQLite drops the tzinfo a timezone-aware column keeps on Postgres.
    assert steps[0].scheduled_at.replace(tzinfo=dt.UTC) == dt.datetime(
        2026, 9, 2, 11, 0, tzinfo=dt.UTC
    )
    assert steps[0].note == "verschoben"


async def test_unknown_steps_and_verdicts_are_refused(application) -> None:
    async with SessionLocal() as s:
        with pytest.raises(ValueError):
            await service.set_step(
                s, tenant_id=TENANT, application_id=application, step_key="kaffee",
            )
        with pytest.raises(ValueError):
            await service.set_step(
                s, tenant_id=TENANT, application_id=application,
                step_key="vorgestellt", outcome="vielleicht",
            )


async def test_steps_are_ordered_as_the_process_doc_orders_them(application) -> None:
    """Termin vor Vorbereitung — you agree the appointment, then prepare for it.
    The cockpit mock had these the other way round."""
    async with SessionLocal() as s:
        for key in ("vorbereitung", "interview", "vorgestellt", "interviewtermin_3", "finaltermin"):
            await service.set_step(
                s, tenant_id=TENANT, application_id=application, step_key=key,
            )
        steps = await service.list_steps(s, tenant_id=TENANT, application_id=application)
    assert [s.step_key for s in steps] == [
        "vorgestellt", "interview", "vorbereitung", "finaltermin", "interviewtermin_3",
    ]


async def test_processes_group_by_mandate(application) -> None:
    async with SessionLocal() as s:
        await service.set_step(
            s, tenant_id=TENANT, application_id=application,
            step_key="vorgestellt", done_at=dt.datetime(2026, 7, 28, tzinfo=dt.UTC),
        )
        await service.set_step(
            s, tenant_id=TENANT, application_id=application,
            step_key="finaltermin", scheduled_at=dt.datetime(2026, 9, 17, 16, 0, tzinfo=dt.UTC),
        )
        entries = await service.processes(s, tenant_id=TENANT)
        assert await service.processes(s, tenant_id=OTHER) == []

    assert len(entries) == 1
    entry = entries[0]
    assert (entry["job_title"], entry["company_name"]) == ("Data 1442", "SSI")
    candidate = entry["candidates"][0]
    assert candidate["candidate_name"] == "Turgut Kaymal"
    assert candidate["presented_at"].date() == dt.date(2026, 7, 28)
    # What the recruiter needs on Monday: the soonest appointment still open.
    assert candidate["next_appointment"] == dt.datetime(2026, 9, 17, 16, 0, tzinfo=dt.UTC)


async def test_an_assigned_candidate_appears_before_being_presented(
    application,
) -> None:
    """Assignment is the start of the work, not the presentation.

    The sheet begins at the presentation because a sheet has nowhere to put
    someone before that. The cockpit does — the Qualifikationsgespräch, the
    documents and the client text all happen in between — so the candidate
    shows up as soon as they are put on the mandate, with every step still
    open and `presented_at` null.
    """
    async with SessionLocal() as s:
        [job] = await service.processes(s, tenant_id=TENANT)
        [person] = job["candidates"]
        assert person["presented_at"] is None
        assert person["steps"] == [], "nothing ticked yet"
        assert person["step_order"][0] == "vorgestellt"


async def test_routes(application) -> None:
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        set_step = await client.patch(
            f"/api/v1/pipeline/applications/{application}/steps/interview",
            json={"scheduled_at": "2026-09-14T10:30:00Z", "note": "vor Ort"},
        )
        assert set_step.status_code == 200
        assert set_step.json()["label"] == "Interviewtermin"

        listed = (await client.get("/api/v1/pipeline/processes")).json()
        assert listed[0]["job_title"] == "Data 1442"
        assert [s["step_key"] for s in listed[0]["candidates"][0]["steps"]] == ["interview"]

        unknown = await client.patch(
            f"/api/v1/pipeline/applications/{application}/steps/kaffee", json={}
        )
        assert unknown.status_code == 404


async def test_a_value_can_be_taken_back(application) -> None:
    """A cancelled interview must be removable, not just overwritable —
    omitting a field means "leave it alone", so clearing needs its own word."""
    async with SessionLocal() as s:
        await service.set_step(
            s, tenant_id=TENANT, application_id=application, step_key="interview",
            scheduled_at=dt.datetime(2026, 9, 21, 10, 0, tzinfo=dt.UTC), note="vor Ort",
        )
        await service.set_step(
            s, tenant_id=TENANT, application_id=application, step_key="interview",
            clear=["scheduled_at", "note"],
        )
        steps = await service.list_steps(s, tenant_id=TENANT, application_id=application)
    assert steps[0].scheduled_at is None and steps[0].note is None


async def test_clearing_an_unknown_field_is_refused(application) -> None:
    async with SessionLocal() as s:
        with pytest.raises(ValueError):
            await service.set_step(
                s, tenant_id=TENANT, application_id=application,
                step_key="interview", clear=["outcome"],
            )


async def test_the_write_answers_with_a_timezone(application) -> None:
    """A client compares what came back against what it sent. SQLite drops the
    tzinfo a timezone-aware column keeps on Postgres, so without normalising
    the two look like different instants and a good save reads as a failure."""
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        sent = "2026-11-05T12:30:00Z"
        body = (
            await client.patch(
                f"/api/v1/pipeline/applications/{application}/steps/interview",
                json={"scheduled_at": sent},
            )
        ).json()
    returned = dt.datetime.fromisoformat(body["scheduled_at"])
    assert returned.tzinfo is not None
    assert returned == dt.datetime(2026, 11, 5, 12, 30, tzinfo=dt.UTC)
