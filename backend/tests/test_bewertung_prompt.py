"""ELI-41: the Bewertungs-Prompt — what a recruiter pastes into Claude.

The recruiters evaluate a candidate by copying the job, the briefing, the CV
and the transcript into Claude by hand, against a fixed schema (ELI-42's
"Kandidatenauswertung"). This assembles that prompt from what Eligo already
holds. Deterministic, no model call.

What is worth pinning:

* the schema is reproduced exactly — the four sections A–D, the score line,
  the closing list — because the output is pasted back into Eligo and read
  by `auswertung.parse_auswertung`;
* every source the record holds lands in it — Suchprofil, briefing, the
  client's feedback on THIS candidate, the candidate's notes, documents;
* nothing about anyone else does — another candidate's feedback, a note
  from another mandate, another workspace's application;
* direct identifiers the evaluation does not need (e-mail, phone, street,
  date of birth) are left out of the structured profile;
* the hard criteria arrive already decided by code, labelled as such.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus, WorkPermitStatus
from app.domain.companies.models import Company
from app.domain.documents.models import CandidateDocument
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.pipeline import bewertung
from app.domain.pipeline.models import Application

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
API = "/api/v1/pipeline"


def _client() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture
async def mandate() -> dict[str, uuid.UUID]:
    """The KVB mandate from the ELI-41 screenshot, one candidate on it."""
    when = dt.datetime(2026, 11, 3, 12, tzinfo=dt.UTC)
    async with SessionLocal() as s:
        company = Company(
            tenant_id=TENANT, name="Kassenärztliche Vereinigung Bayerns", is_client=True
        )
        s.add(company)
        await s.flush()
        manager = Manager(
            tenant_id=TENANT,
            company_id=company.id,
            full_name="Lisa-Maria Scheuerich",
            role_title="Recruiter",
        )
        candidate = Candidate(
            tenant_id=TENANT,
            full_name="Max Beispiel",
            email="max@example.org",
            phone="+49 170 1234567",
            street="Geheimweg 7",
            date_of_birth="01.02.1985",
            current_title="Senior Java Developer",
            current_company="Muster AG",
            location="Augsburg",
            skills=["Java", "Spring Boot", "Kubernetes"],
            salary_expectation=72000,
            salary_minimum=68000,
            notice_period="3 Monate zum Quartalsende",
            work_permit=WorkPermitStatus.CITIZEN,
        )
        other = Candidate(tenant_id=TENANT, full_name="Erika Andere")
        s.add_all([manager, candidate, other])
        await s.flush()
        job = Job(
            tenant_id=TENANT,
            title="Java Developer / DevSecOps (m/w/d)",
            client_company_id=company.id,
            manager_id=manager.id,
            location="München oder Augsburg",
            must_have_skills=["Java", "DevSecOps"],
            salary_min=60000,
            salary_max=75000,
        )
        elsewhere = Job(tenant_id=TENANT, title="Anderes Mandat", client_company_id=company.id)
        s.add_all([job, elsewhere])
        await s.flush()
        application = Application(
            tenant_id=TENANT,
            candidate_id=candidate.id,
            job_id=job.id,
            status=ApplicationStatus.PRESENTED,
        )
        s.add(application)
        s.add_all(
            [
                ManagerInteraction(
                    tenant_id=TENANT,
                    manager_id=manager.id,
                    job_id=job.id,
                    interaction_type="briefing",
                    occurred_at=when,
                    summary="Manager legt Wert auf sauberen akademischen Hintergrund. "
                    "Gehalt bis ca. 75.000 €. 2 Tage Office.",
                ),
                ManagerInteraction(
                    tenant_id=TENANT,
                    manager_id=manager.id,
                    job_id=job.id,
                    candidate_id=candidate.id,
                    interaction_type="feedback",
                    occurred_at=when,
                    summary="Kunde: Profil passt, gerne Interview.",
                ),
                ManagerInteraction(
                    tenant_id=TENANT,
                    manager_id=manager.id,
                    job_id=job.id,
                    candidate_id=other.id,
                    interaction_type="feedback",
                    occurred_at=when,
                    summary="Kunde: ANDERE-KANDIDATIN-FEEDBACK",
                ),
                ManagerInteraction(
                    tenant_id=TENANT,
                    candidate_id=candidate.id,
                    interaction_type="candidate_qualification",
                    occurred_at=when,
                    summary="Wechselmotivation: mehr Security-Verantwortung.",
                ),
                ManagerInteraction(
                    tenant_id=TENANT,
                    candidate_id=candidate.id,
                    job_id=elsewhere.id,
                    interaction_type="candidate_call",
                    occurred_at=when,
                    summary="NOTIZ-ZU-ANDEREM-MANDAT",
                ),
                CandidateDocument(
                    tenant_id=TENANT,
                    candidate_id=candidate.id,
                    kind="cv",
                    filename="cv.txt",
                    content_type="text/plain",
                    byte_size=10,
                    content="Lebenslauf: Java seit 2012, Jenkins, SonarQube".encode(),
                ),
                CandidateDocument(
                    tenant_id=TENANT,
                    candidate_id=candidate.id,
                    kind="transkript",
                    filename="gespraech.txt",
                    content_type="text/plain",
                    byte_size=10,
                    content="Transkript: Kündigungsfrist drei Monate".encode(),
                ),
                CandidateDocument(
                    tenant_id=TENANT,
                    candidate_id=candidate.id,
                    kind="zeugnis",
                    filename="zeugnis.png",
                    content_type="image/png",
                    byte_size=4,
                    content=b"\x89PNG",
                ),
            ]
        )
        await s.commit()
        return {"application": application.id, "job": job.id}


# --- the pure builder ---------------------------------------------------------


def _material(**overrides) -> bewertung.EvaluationMaterial:
    base = dict(
        job_title="Java Developer / DevSecOps (m/w/d)",
        client="KVB",
        location="München oder Augsburg",
        vacancy_id="#A-1234",
        candidate_name="Max Beispiel",
    )
    base.update(overrides)
    return bewertung.EvaluationMaterial(**base)


def test_the_prompt_carries_the_schema_exactly() -> None:
    prompt = bewertung.build_prompt(_material())
    for line in (
        "Kandidatenauswertung",
        "Position: Java Developer / DevSecOps (m/w/d) | KVB München oder Augsburg | Vakanz-ID #A-1234",
        "A. Passungsbewertung zur Position",
        "Gesamtbewertung: X / 10",
        "Kurzfazit:",
        "Stärken:",
        "Lücken / Risiken:",
        "Fachliche & professionelle Passung:",
        "Gehalt:",
        "B. Gesprächszusammenfassung für Datenbank",
        "Zusammenfassung des Profils:",
        "Schwerpunkte:",
        "Technisches Know-how:",
        "Kündigungsfrist / Verfügbarkeit:",
        "Gehaltsvorstellung:",
        "Wechselmotivation:",
        "Höchster Abschluss:",
        "Verfügbarkeit für Interviews:",
        "Weitere relevante Punkte:",
        "C. Kandidatenzusammenfassung für Kundenvorstellung (KVB)",
        "D. Relevante Technologien für die Position",
        "Vor der Vorstellung zu klären:",
    ):
        assert line in prompt, f"schema line missing: {line!r}"
    # The order is the document's order.
    order = [
        prompt.index(h)
        for h in ("\nA. ", "\nB. ", "\nC. ", "\nD. ", "\nVor der Vorstellung zu klären:\n")
    ]
    assert order == sorted(order)


def test_the_basis_line_names_only_what_exists() -> None:
    """"Gesprächstranskript vom …" with no transcript would be a source that
    was never read — the provenance line is written by code, not the model."""
    bare = bewertung.build_prompt(_material())
    assert "Gesprächstranskript" not in bewertung.basis_line(_material())
    assert "Basis:" in bare

    full = _material(
        profile_date=dt.date(2026, 10, 1),
        documents=[
            bewertung.SourceDocument("transkript", "g.txt", dt.date(2026, 11, 3), "…"),
            bewertung.SourceDocument("cv", "cv.pdf", dt.date(2026, 10, 2), "…"),
            bewertung.SourceDocument("zeugnis", "z.pdf", dt.date(2026, 10, 2), "…"),
        ],
    )
    assert bewertung.basis_line(full) == (
        "Basis: Suchprofil vom 01.10.2026, Gesprächstranskript vom 03.11.2026, "
        "Lebenslauf und Zeugnisse"
    )


def test_section_c_is_told_to_leave_out_health_and_salary() -> None:
    prompt = bewertung.build_prompt(_material())
    assert "keine Gesundheitsdaten" in prompt
    assert "kein Gehalt" in prompt
    assert "nicht angegeben" in prompt


# --- the endpoint ---------------------------------------------------------------


async def test_the_prompt_holds_every_source_of_this_process(mandate) -> None:
    async with _client() as c:
        res = await c.get(f"{API}/applications/{mandate['application']}/bewertung-prompt")
    assert res.status_code == 200, res.text
    body = res.json()
    prompt = body["prompt"]

    assert "Kassenärztliche Vereinigung Bayerns" in prompt
    assert "Java Developer / DevSecOps (m/w/d)" in prompt
    assert "Lisa-Maria Scheuerich" in prompt
    assert "DevSecOps" in prompt and "60.000–75.000 EUR" in prompt
    assert "Manager legt Wert auf sauberen akademischen Hintergrund" in prompt
    assert "Kunde: Profil passt, gerne Interview." in prompt
    assert "Wechselmotivation: mehr Security-Verantwortung." in prompt
    assert "Lebenslauf: Java seit 2012, Jenkins, SonarQube" in prompt
    assert "Transkript: Kündigungsfrist drei Monate" in prompt
    assert "Senior Java Developer" in prompt and "3 Monate zum Quartalsende" in prompt
    # A scan is named, not silently dropped.
    assert "zeugnis.png" in prompt and "kein Text lesbar" in prompt
    # Hard criteria decided by code, labelled as such.
    assert "Deterministisch geprüft" in prompt
    assert "Gehalt" in prompt and "im Band" in prompt

    assert body["sources"], body
    assert body["chars"] == len(prompt)


async def test_nothing_about_anyone_else_reaches_the_prompt(mandate) -> None:
    async with _client() as c:
        prompt = (
            await c.get(f"{API}/applications/{mandate['application']}/bewertung-prompt")
        ).json()["prompt"]
    assert "ANDERE-KANDIDATIN-FEEDBACK" not in prompt
    assert "NOTIZ-ZU-ANDEREM-MANDAT" not in prompt


async def test_identifiers_the_evaluation_does_not_need_stay_out(mandate) -> None:
    async with _client() as c:
        prompt = (
            await c.get(f"{API}/applications/{mandate['application']}/bewertung-prompt")
        ).json()["prompt"]
    for value in ("max@example.org", "+49 170 1234567", "Geheimweg 7", "01.02.1985"):
        assert value not in prompt, f"{value} leaked into the prompt"


async def test_an_unknown_process_is_404(mandate) -> None:
    async with _client() as c:
        res = await c.get(f"{API}/applications/{uuid.uuid4()}/bewertung-prompt")
    assert res.status_code == 404


# --- the way back: Claude's answer pasted into "Nach dem Gespräch erfassen" ---

#: An answer in the prompt's schema, the way Claude writes it: bold topics,
#: "Lücken / Risiken" with spaces, "Basis:" rather than "Grundlage:", and a
#: closing list after D.
ANSWER = """\
Kandidatenauswertung
Position: Java Developer / DevSecOps (m/w/d) | KVB München oder Augsburg | Vakanz-ID #A-1234
Basis: Suchprofil vom 01.10.2026, Gesprächstranskript vom 03.11.2026, Lebenslauf und Zeugnisse

Der Lebenslauf nennt ein Enddatum, das im Zeugnis fehlt.

## A. Passungsbewertung zur Position
**Gesamtbewertung: 7 / 10**
**Kurzfazit:** Solider Java-Entwickler mit Security-Bezug.
**Stärken:**
- **Java:** seit 2012 laut Lebenslauf.
- **CI/CD:** Jenkins und SonarQube im Lebenslauf.
**Lücken / Risiken:**
- **DevSecOps:** im Material nicht belegt.
**Fachliche & professionelle Passung:** Fachlich passend, Security-Tiefe offen.
**Gehalt:** Wunsch 72.000 € vs. Rahmen 60.000–75.000 €.

## B. Gesprächszusammenfassung für Datenbank
Zusammenfassung des Profils: Java-Entwickler mit 12 Jahren Erfahrung.
Schwerpunkte: Backend, CI/CD
Technisches Know-how: Java, Spring Boot, Jenkins; DevSecOps: nicht angegeben
Kündigungsfrist / Verfügbarkeit: 3 Monate zum Quartalsende
Gehaltsvorstellung: Minimum 68.000 €; Wunsch 72.000 €
Wechselmotivation: mehr Security-Verantwortung
Höchster Abschluss: nicht angegeben
Verfügbarkeit für Interviews: nicht erfragt
Weitere relevante Punkte:
- 2 Tage Office möglich

## C. Kandidatenzusammenfassung für Kundenvorstellung (KVB)
Erfahrener Java-Entwickler mit Schwerpunkt Backend und CI/CD.

## D. Relevante Technologien für die Position
Java, Spring Boot, Jenkins, SonarQube

Vor der Vorstellung zu klären:
1. Security-Erfahrung konkret erfragen.
2. Höchsten Abschluss erfragen.
"""


def test_the_answer_pastes_back_into_the_form() -> None:
    """The prompt's schema is the parser's input. A label the parser cannot
    read is a field the recruiter has to retype."""
    from app.domain.pipeline.auswertung import parse_auswertung

    parsed = parse_auswertung(ANSWER)
    a = parsed["assessment"]
    assert a["fit_score"] == 7
    assert a["verdict"].startswith("Solider Java-Entwickler mit Security-Bezug.")
    assert "Fachlich passend" in a["verdict"]
    assert a["strengths"] == [
        "Java: seit 2012 laut Lebenslauf.",
        "CI/CD: Jenkins und SonarQube im Lebenslauf.",
    ]
    assert a["risks"][0] == "DevSecOps: im Material nicht belegt."
    # The closing questions are open points, not technologies.
    assert "Zu klären: Security-Erfahrung konkret erfragen." in a["risks"]
    assert a["technologies"] == ["Java", "Spring Boot", "Jenkins", "SonarQube"]
    assert a["client_summary"] == (
        "Erfahrener Java-Entwickler mit Schwerpunkt Backend und CI/CD."
    )
    assert a["basis"].startswith("Suchprofil vom 01.10.2026")
    # The conversation's date, not the Suchprofil's: that is when the
    # candidate was assessed.
    assert a["assessed_at"] == dt.datetime(2026, 11, 3, tzinfo=dt.UTC)

    profile = parsed["candidate"]
    assert profile["notice_period"] == "3 Monate zum Quartalsende"
    assert profile["salary_minimum"] == 68000
    assert profile["salary_expectation"] == 72000


def test_a_label_on_its_own_line_still_reads() -> None:
    """Claude sometimes puts the text under the label instead of after it."""
    from app.domain.pipeline.auswertung import parse_auswertung

    text = ANSWER.replace(
        "**Kurzfazit:** Solider", "**Kurzfazit:**\nSolider"
    )
    assert parse_auswertung(text)["assessment"]["verdict"].startswith("Solider")
