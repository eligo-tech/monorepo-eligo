"""The Kandidatenauswertung: one candidate measured against ONE mandate.

`data/examples/KandidatenInfo.txt` is the artefact under test — a real
evaluation of a senior backend candidate against one position. The thing worth
pinning is that it belongs to the APPLICATION: the same person put forward for
a second mandate must start with no verdict, not inherit the first one's score,
strengths and risks. A fit assessment that follows a candidate around is how a
recruiter ends up telling a client something that was true of another job.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.pipeline import service
from app.domain.pipeline.models import Application
from scripts import import_assessment
from app.domain.pipeline.auswertung import parse_auswertung

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
API = "/api/v1/pipeline"


@pytest.fixture
async def two_mandates() -> dict[str, uuid.UUID]:
    """One candidate, two mandates — the case the keying has to get right."""
    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name="EM Software", is_client=True)
        candidate = Candidate(tenant_id=TENANT, full_name="Senior Backend")
        s.add_all([company, candidate])
        await s.flush()
        first = Job(
            tenant_id=TENANT,
            title="Java Dev",
            client_company_id=company.id,
            location="München",
            must_have_skills=["Java", "WildFly"],
            salary_min=80000,
            salary_max=95000,
        )
        second = Job(tenant_id=TENANT, title="Platform Lead", client_company_id=company.id)
        s.add_all([first, second])
        await s.flush()
        apps = [
            Application(
                tenant_id=TENANT,
                candidate_id=candidate.id,
                job_id=job.id,
                status=ApplicationStatus.PRESENTED,
            )
            for job in (first, second)
        ]
        s.add_all(apps)
        await s.commit()
        return {"java": apps[0].id, "platform": apps[1].id, "job": first.id}


async def test_the_verdict_belongs_to_the_mandate_not_the_person(two_mandates) -> None:
    """THE invariant. Assessing a candidate on one job says nothing about
    the same candidate on another — different Muss-Profil, different fit."""
    async with SessionLocal() as s:
        await service.set_assessment(
            s,
            tenant_id=TENANT,
            application_id=two_mandates["java"],
            fit_score=8,
            verdict="Sehr passgenauer Senior-Kandidat für Position 1.",
            strengths=["WildFly inkl. Cluster-Migration"],
            risks=["Gehalt am oberen Rand"],
            technologies=["Java", "Jakarta EE", "WildFly"],
            basis="CV (Kurzversion) + Gesprächstranskript (18.09.2026)",
        )

    async with SessionLocal() as s:
        java = await service.get_assessment(
            s, tenant_id=TENANT, application_id=two_mandates["java"]
        )
        other = await service.get_assessment(
            s, tenant_id=TENANT, application_id=two_mandates["platform"]
        )
    assert java is not None and java.fit_score == 8
    assert other is None, "a verdict leaked onto a second mandate"


async def test_a_second_write_replaces_rather_than_accumulates(two_mandates) -> None:
    """One row per application: re-reading the file after round two must not
    leave yesterday's risks standing next to today's."""
    async with SessionLocal() as s:
        await service.set_assessment(
            s,
            tenant_id=TENANT,
            application_id=two_mandates["java"],
            fit_score=6,
            risks=["Kündigungsfrist unklar"],
        )
        row = await service.set_assessment(
            s,
            tenant_id=TENANT,
            application_id=two_mandates["java"],
            fit_score=8,
            risks=["Gehalt am oberen Rand"],
        )
    assert row.fit_score == 8
    assert row.risks == ["Gehalt am oberen Rand"]


async def test_the_score_stays_on_the_documents_scale(two_mandates) -> None:
    async with SessionLocal() as s:
        with pytest.raises(ValueError):
            await service.set_assessment(
                s, tenant_id=TENANT, application_id=two_mandates["java"], fit_score=80
            )


async def test_an_unknown_application_is_refused(two_mandates) -> None:
    async with SessionLocal() as s:
        with pytest.raises(ValueError):
            await service.set_assessment(
                s, tenant_id=TENANT, application_id=uuid.uuid4(), fit_score=5
            )
        with pytest.raises(ValueError):
            # Right application, wrong tenant — the application is invisible.
            await service.set_assessment(
                s, tenant_id=OTHER, application_id=two_mandates["java"], fit_score=5
            )


async def test_the_cockpit_sees_the_assessment_and_the_suchprofil(two_mandates) -> None:
    """The per-job view needs both halves of a mandate in one call: what is
    being searched for, and how each candidate measures against it."""
    async with SessionLocal() as s:
        await service.set_assessment(
            s,
            tenant_id=TENANT,
            application_id=two_mandates["java"],
            fit_score=8,
            verdict="Deckt das verschärfte Muss vollständig ab.",
            technologies=["WildFly"],
        )
        await service.set_step(
            s,
            tenant_id=TENANT,
            application_id=two_mandates["java"],
            step_key="vorgestellt",
            done_at=None,
            outcome="pass",
        )
        grouped = await service.processes(s, tenant_id=TENANT)

    java = next(g for g in grouped if g["job_title"] == "Java Dev")
    assert java["location"] == "München"
    assert java["must_have_skills"] == ["Java", "WildFly"]
    assert (java["salary_min"], java["salary_max"]) == (80000, 95000)
    candidate = java["candidates"][0]
    assert candidate["assessment"]["fit_score"] == 8
    assert candidate["assessment"]["technologies"] == ["WildFly"]


async def test_an_unassessed_candidate_reads_as_null_not_as_a_zero(
    two_mandates,
) -> None:
    """"Not assessed yet" and "assessed, scored nothing" are different
    statements, and a cockpit that confuses them invents a verdict."""
    async with SessionLocal() as s:
        await service.set_step(
            s,
            tenant_id=TENANT,
            application_id=two_mandates["java"],
            step_key="vorgestellt",
            outcome="pass",
        )
        grouped = await service.processes(s, tenant_id=TENANT)
    assert grouped[0]["candidates"][0]["assessment"] is None


async def test_routes(two_mandates) -> None:
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        app_id = two_mandates["java"]
        assert (await client.get(f"{API}/applications/{app_id}/assessment")).status_code == 404

        written = await client.put(
            f"{API}/applications/{app_id}/assessment",
            json={
                "fit_score": 8,
                "verdict": "Sehr passgenau.",
                "strengths": ["Architektur-Verantwortung real gelebt"],
                "risks": ["Gehalt hoch"],
                "client_summary": "Senior Entwickler und Architekt …",
                "technologies": ["Java", "WildFly"],
                "basis": "CV + Transkript (18.09.2026)",
            },
        )
        assert written.status_code == 200
        assert written.json()["fit_score"] == 8
        assert written.json()["assessed_at"] is not None

        read = await client.get(f"{API}/applications/{app_id}/assessment")
        assert read.json()["strengths"] == ["Architektur-Verantwortung real gelebt"]

        # Out of range is rejected at the contract, not stored and clamped.
        bad = await client.put(
            f"{API}/applications/{app_id}/assessment", json={"fit_score": 11}
        )
        assert bad.status_code == 422

        missing = await client.put(
            f"{API}/applications/{uuid.uuid4()}/assessment", json={"fit_score": 5}
        )
        assert missing.status_code == 404


# --------------------------------------------------------------------------
# Reading the real document
# --------------------------------------------------------------------------

EXAMPLE = (
    pathlib.Path(__file__).parents[2] / "data/examples/KandidatenInfo.txt"
)


@pytest.mark.skipif(not EXAMPLE.exists(), reason="example not in this checkout")
def test_the_real_evaluation_parses_into_its_four_sections() -> None:
    """Against the actual file, because the parse is a claim about it.

    A fixture written from memory would agree with whatever the parser does;
    the recruiter's own document can disagree.
    """
    parsed = parse_auswertung(EXAMPLE.read_text(encoding="utf-8"))
    a = parsed["assessment"]

    assert a["fit_score"] == 8
    assert a["basis"] == "CV (Kurzversion) + Gesprächstranskript (18.09.2026)"
    # Provenance carries its date: the assessment is as old as the interview.
    assert a["assessed_at"].date() == dt.date(2026, 9, 18)

    assert len(a["strengths"]) == 7
    assert a["strengths"][0].startswith("Deckt das verschärfte Muss")
    assert len(a["risks"]) == 7
    assert a["risks"][0].startswith("Gehalt hoch")
    # The risk list ends where the prose resumes — the "Fachliche &
    # professionelle Passung" paragraph is argument, not a risk.
    assert not any(r.startswith("Fachliche") for r in a["risks"])

    assert a["technologies"][:3] == ["Java", "Jakarta EE/J2EE", "WildFly"]
    assert "Microservices-Architektur" in a["technologies"]
    assert a["client_summary"].startswith("Der Kandidat ist ein Senior Software")

    # Section B describes the person, so it lands on the candidate. Every
    # labelled line of it has a column — the three that did not (Schwerpunkte,
    # Technisches Know-how, Weitere relevante Punkte) were silently dropped
    # on every import until migration 0036 gave them one.
    b = parsed["candidate"]
    assert set(b) == {
        "profile_summary",
        "focus_areas",
        "technical_profile",
        "notice_period",
        "motivation",
        "education",
        "interview_availability",
        "other_notes",
        "current_salary",
        "salary_minimum",
        "salary_expectation",
    }
    assert "Mittwoch/Donnerstag" in b["interview_availability"]

    # Schwerpunkte is read as items, and the comma inside the bracket does
    # not split one of them in half.
    assert b["focus_areas"][:2] == ["Java-Enterprise-Architektur", "WildFly/JBoss"]
    assert "Legacy-Modernisierung (Swing/XML → Microservices)" in b["focus_areas"]

    # "Technisches Know-how" stays prose and stays OUT of `skills`: that list
    # feeds the deterministic hard filters, and "MariaDB bekannt (persönlich
    # nicht bevorzugt)" must never arrive there as a skill.
    assert "skills" not in b
    assert b["technical_profile"].startswith("Java (Experte)")

    # "Weitere relevante Punkte" is an open list, kept line by line.
    assert b["other_notes"].count("\n") == 4
    assert b["other_notes"].startswith("Aktuelle Rolle / Arbeitgeber:")

    # Each salary comes from the clause that names it, never from position.
    assert (b["current_salary"], b["salary_minimum"], b["salary_expectation"]) == (
        105_000,
        92_000,
        100_000,
    )
    assert b["education"] == [
        "Fachinformatiker Anwendungsentwicklung (IHK); zahlreiche Zertifizierungen"
        " (zertifizierter Enterprise Architect, JBoss Certified Application"
        " Administrator, Certified Java Programmer u. a.)."
    ]


def test_a_document_that_stops_after_section_a_still_imports() -> None:
    """Half a file is not an error. A parser that insisted on all four
    sections would be bypassed, and then nothing would be captured at all."""
    parsed = parse_auswertung(
        "Kandidatenauswertung\n"
        "Grundlage: CV\n\n"
        "A. Passungsbewertung zur Position\n"
        "Gesamtbewertung: 5 / 10\n\n"
        "Kurzfazit: Solide, aber nicht senior genug.\n"
    )
    assert parsed["assessment"]["fit_score"] == 5
    assert parsed["assessment"]["verdict"] == "Solide, aber nicht senior genug."
    assert parsed["assessment"]["strengths"] == []
    assert parsed["assessment"]["client_summary"] is None
    assert parsed["candidate"] == {}


async def test_the_importer_refuses_to_guess_the_candidate(two_mandates) -> None:
    """The example is anonymised and the tracker holds real people. Naming
    the wrong one would attach invented claims to a named person, so an
    unknown name is a hard stop rather than a nearest match."""
    parsed = {"assessment": {"fit_score": 8}, "candidate": {}}
    with pytest.raises(SystemExit):
        await import_assessment.load(
            parsed,
            tenant_id=TENANT,
            company="EM Software",
            job="Java Dev",
            candidate="Jemand Anderes",
        )


async def test_the_importer_writes_both_halves(two_mandates) -> None:
    parsed = {
        "assessment": {"fit_score": 8, "technologies": ["WildFly"]},
        "candidate": {"interview_availability": "Mi/Do ab 11 Uhr"},
    }
    result = await import_assessment.load(
        parsed,
        tenant_id=TENANT,
        company="EM Software",
        job="Java Dev",
        candidate="Senior Backend",
    )
    assert result["application"] == str(two_mandates["java"])

    async with SessionLocal() as s:
        row = await service.get_assessment(
            s, tenant_id=TENANT, application_id=two_mandates["java"]
        )
        candidate = await s.scalar(
            select(Candidate).where(Candidate.full_name == "Senior Backend")
        )
    assert row.fit_score == 8 and row.technologies == ["WildFly"]
    assert candidate.interview_availability == "Mi/Do ab 11 Uhr"


# --------------------------------------------------------------------------
# Pasting the document into the cockpit
# --------------------------------------------------------------------------


@pytest.mark.skipif(not EXAMPLE.exists(), reason="example not in this checkout")
async def test_pasting_the_document_fills_the_form_and_stores_nothing() -> None:
    """The paste box proposes; the recruiter commits.

    A parse that wrote straight to the record would put salary figures it
    lifted out of a sentence into the columns a hard filter reads, with
    nobody having looked at them. So the endpoint returns the fields and
    changes no row — which is also what makes it safe to paste a draft.
    """
    from app.main import app as fastapi_app

    text = EXAMPLE.read_text(encoding="utf-8")
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        response = await client.post(f"{API}/auswertung/parse", json={"text": text})
    assert response.status_code == 200
    body = response.json()

    assert body["assessment"]["fit_score"] == 8
    assert len(body["assessment"]["strengths"]) == 7
    assert body["assessment"]["technologies"][0] == "Java"
    assert body["profile"]["focus_areas"][1] == "WildFly/JBoss"
    assert body["profile"]["salary_minimum"] == 92_000
    assert body["profile"]["other_notes"].startswith("Aktuelle Rolle")

    # Nothing was written: no assessment row exists for anybody.
    async with SessionLocal() as s:
        from app.domain.pipeline.models import ApplicationAssessment

        rows = (await s.execute(select(ApplicationAssessment))).scalars().all()
    assert rows == []


async def test_pasting_something_that_is_not_the_template_is_not_an_error() -> None:
    """An empty answer is the honest one. Raising would mean a recruiter who
    pasted the wrong half of a document loses the window they typed in."""
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        response = await client.post(
            f"{API}/auswertung/parse", json={"text": "Guten Tag, anbei mein Lebenslauf."}
        )
    assert response.status_code == 200
    assert response.json()["assessment"]["fit_score"] is None
    assert response.json()["profile"]["profile_summary"] is None


async def test_the_process_carries_the_person_as_well_as_the_fit(two_mandates) -> None:
    """The cockpit opens a candidate's card with the summary already in hand.

    Section B holds across mandates, so it is read off the candidate and
    appears identically on BOTH of this person's runs — the opposite of the
    assessment, which is per mandate on purpose.
    """
    async with SessionLocal() as s:
        candidate = await s.scalar(
            select(Candidate).where(Candidate.tenant_id == TENANT)
        )
        candidate.profile_summary = "Senior Software Entwickler & Architekt."
        candidate.focus_areas = ["Java-Enterprise-Architektur", "WildFly/JBoss"]
        candidate.technical_profile = "Java (Experte), WildFly, JPA/Hibernate."
        candidate.other_notes = "Sprachkenntnisse: Deutsch, Englisch."
        # An ATS import leaves education as dicts; the cockpit reads a line.
        candidate.education = [{"degree": "Fachinformatiker AE", "year": "2003"}]
        await s.commit()

        grouped = await service.processes(s, tenant_id=TENANT)

    profiles = [c["profile"] for job in grouped for c in job["candidates"]]
    assert len(profiles) == 2
    assert {p["profile_summary"] for p in profiles} == {
        "Senior Software Entwickler & Architekt."
    }
    assert profiles[0]["focus_areas"] == [
        "Java-Enterprise-Architektur",
        "WildFly/JBoss",
    ]
    assert profiles[0]["education"] == ["Fachinformatiker AE · 2003"]


async def test_a_score_outside_the_scale_does_not_lose_the_rest_of_the_document() -> None:
    """"12 / 10" is somebody being emphatic, not a reason to refuse the paste.

    The score comes back empty — clamping it to 10 would put a number in
    front of a recruiter that the document does not contain — and every
    other field is still filled.
    """
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        response = await client.post(
            f"{API}/auswertung/parse",
            json={
                "text": (
                    "A. Passungsbewertung zur Position\n"
                    "Gesamtbewertung: 12 / 10\n\n"
                    "Kurzfazit: Ausnahmekandidat.\n"
                )
            },
        )
    assert response.status_code == 200
    assert response.json()["assessment"]["fit_score"] is None
    assert response.json()["assessment"]["verdict"] == "Ausnahmekandidat."
