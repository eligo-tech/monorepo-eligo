"""ELI-42: the in-app AI evaluation — proposed by a model, checked by code,
committed by a person.

No real model is called: a fake evaluator returns a fixed answer, the way
the extractor tests fake theirs. What is pinned:

* nothing reaches `application_assessments` until a recruiter confirms;
* the checks are deterministic and enforced, not requested: an ungrounded
  technology is not stored, a client text with salary or health data is
  withheld, a score outside 0–10 is dropped, a failed hard filter is flagged;
* confirm stores the CHECKED fields with "KI" provenance and the model name,
  and erases the free text from the proposal; decline stores nothing;
* a recruiter's save after the evaluation makes it stale — never overwritten;
* with no model configured, the feature says so and the copy-prompt remains.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus, WorkPermitStatus
from app.domain.companies.models import Company
from app.domain.documents.models import CandidateDocument
from app.domain.jobs.models import Job
from app.domain.pipeline import service as pipeline
from app.domain.pipeline.evaluation import factory
from app.domain.pipeline.models import Application
from app.domain.proposals.models import AgentProposal
from app.domain.verification.models import Receipt

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
API = "/api/v1"

ANSWER = """\
Kandidatenauswertung
Position: Java Developer / DevSecOps (m/w/d) | KVB München | Vakanz-ID #A-1234
Basis: Suchprofil vom 01.10.2026, Gesprächstranskript vom 03.11.2026, Lebenslauf

A. Passungsbewertung zur Position
Gesamtbewertung: {score} / 10
Kurzfazit: Solider Java-Entwickler mit CI/CD-Erfahrung.
Stärken:
- **Java:** seit 2012 laut Lebenslauf.
Lücken / Risiken:
- **DevSecOps:** im Material nicht belegt.
Fachliche & professionelle Passung: Fachlich passend.
Gehalt: Wunsch 72.000 € vs. Rahmen 60.000–75.000 €.

B. Gesprächszusammenfassung für Datenbank
Zusammenfassung des Profils: Java-Entwickler.
Technisches Know-how: {know_how}
Kündigungsfrist / Verfügbarkeit: 3 Monate

C. Kandidatenzusammenfassung für Kundenvorstellung (KVB)
{client}

D. Relevante Technologien für die Position
{tech}

Vor der Vorstellung zu klären:
1. Security-Erfahrung erfragen.
"""


def answer(
    *,
    score: str = "7",
    client: str = "Erfahrener Java-Entwickler mit Schwerpunkt Backend.",
    tech: str = "Java, Jenkins",
    know_how: str = "Java, Jenkins; DevSecOps: nicht angegeben",
) -> str:
    return ANSWER.format(score=score, client=client, tech=tech, know_how=know_how)


class FakeEvaluator:
    name = "fake"
    model = "fake-model-1"

    def __init__(self, text: str | Exception) -> None:
        self.text = text
        self.prompts: list[str] = []

    def evaluate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


@pytest.fixture
def use(monkeypatch):
    """Install a fake evaluator; returns it."""

    def install(text: str | Exception) -> FakeEvaluator:
        fake = FakeEvaluator(text)
        monkeypatch.setattr(factory, "get_evaluator", lambda cfg=None: fake)
        return fake

    return install


def _client() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture
async def process() -> uuid.UUID:
    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name="KVB", is_client=True)
        candidate = Candidate(
            tenant_id=TENANT,
            full_name="Max Beispiel",
            location="München",
            skills=["Java"],
            work_permit=WorkPermitStatus.CITIZEN,
            salary_expectation=72000,
        )
        s.add_all([company, candidate])
        await s.flush()
        job = Job(
            tenant_id=TENANT,
            title="Java Developer / DevSecOps (m/w/d)",
            client_company_id=company.id,
            location="München",
            must_have_skills=["Java", "DevSecOps"],
            salary_min=60000,
            salary_max=75000,
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
        s.add(
            CandidateDocument(
                tenant_id=TENANT,
                candidate_id=candidate.id,
                kind="cv",
                filename="cv.txt",
                content_type="text/plain",
                byte_size=10,
                content="Java seit 2012, Jenkins, SonarQube".encode(),
            )
        )
        await s.commit()
        return app.id


async def _evaluate(app_id: uuid.UUID):
    async with _client() as c:
        return await c.post(f"{API}/pipeline/applications/{app_id}/evaluation")


async def _assessment(app_id: uuid.UUID):
    async with SessionLocal() as s:
        return await pipeline.get_assessment(s, tenant_id=TENANT, application_id=app_id)


# --- degrade without a model ----------------------------------------------------


async def test_without_a_model_the_feature_says_so(process, monkeypatch) -> None:
    monkeypatch.setattr(factory, "get_evaluator", lambda cfg=None: None)
    async with _client() as c:
        status_ = await c.get(f"{API}/pipeline/evaluation/provider")
        res = await c.post(f"{API}/pipeline/applications/{process}/evaluation")
        prompt = await c.get(f"{API}/pipeline/applications/{process}/bewertung-prompt")
    assert status_.json() == {"available": False, "model": None}
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "no_llm"
    assert prompt.status_code == 200, "the copy-prompt is the fallback"


def test_the_default_config_without_a_key_has_no_evaluator() -> None:
    from app.core.config import Settings

    assert factory.get_evaluator(Settings(llm_provider="openai", OPENAI_API_KEY=None)) is None
    assert factory.get_evaluator(Settings(llm_provider="heuristic")) is None


# --- propose, never write -----------------------------------------------------------


async def test_the_evaluation_is_a_proposal_not_a_record(process, use) -> None:
    fake = use(answer())
    res = await _evaluate(process)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "pending"
    assert body["model"] == "fake-model-1"
    assert body["assessment"]["fit_score"] == 7
    assert body["text"].startswith("Kandidatenauswertung")
    assert await _assessment(process) is None, "the model wrote the record"

    # The model was asked the ELI-41 prompt, the same a recruiter copies.
    assert len(fake.prompts) == 1
    assert "D. Relevante Technologien für die Position" in fake.prompts[0]
    assert "Java seit 2012, Jenkins, SonarQube" in fake.prompts[0]

    async with _client() as c:
        again = await c.get(f"{API}/pipeline/applications/{process}/evaluation")
    assert again.status_code == 200 and again.json()["id"] == body["id"]


async def test_a_technology_the_material_does_not_name_is_not_stored(process, use) -> None:
    use(answer(tech="Java, Kubernetes, Jenkins"))
    body = (await _evaluate(process)).json()
    assert body["assessment"]["technologies"] == ["Java", "Jenkins"]
    assert any("Kubernetes" in f for f in body["flags"])


async def test_a_must_have_claimed_without_evidence_is_flagged(process, use) -> None:
    use(answer(know_how="Java, DevSecOps, Jenkins"))
    flags = (await _evaluate(process)).json()["flags"]
    assert any("DevSecOps" in f and "Know-how" in f for f in flags)


async def test_nicht_angegeben_is_not_a_claim(process, use) -> None:
    use(answer())
    flags = (await _evaluate(process)).json()["flags"]
    assert not any("Know-how" in f for f in flags), flags


@pytest.mark.parametrize(
    "client",
    [
        "Erfahrener Entwickler, Gehaltsvorstellung 72.000 €.",
        "Erfahrener Entwickler, Wunsch 72k.",
        "Nach längerer Krankheit wieder voll belastbar.",
        "Nach einem Burnout 2023 neu orientiert.",
    ],
)
async def test_the_client_text_never_carries_salary_or_health(process, use, client) -> None:
    use(answer(client=client))
    body = (await _evaluate(process)).json()
    assert body["assessment"]["client_summary"] is None
    assert body["client_text_withheld"] is True
    assert any("Kundentext" in f for f in body["flags"])


async def test_an_ordinary_client_text_passes(process, use) -> None:
    use(answer(client="Erfahrener Java-Entwickler aus dem Klinikum-IT-Betrieb mit Operations-Fokus."))
    body = (await _evaluate(process)).json()
    assert body["assessment"]["client_summary"].startswith("Erfahrener Java-Entwickler")
    assert body["client_text_withheld"] is False


@pytest.mark.parametrize("score", ["12", "X"])
async def test_a_score_off_the_scale_is_dropped(process, use, score) -> None:
    use(answer(score=score))
    body = (await _evaluate(process)).json()
    assert body["assessment"]["fit_score"] is None
    assert any("Gesamtbewertung" in f for f in body["flags"])


async def test_a_failed_hard_filter_is_flagged_whatever_the_score(process, use) -> None:
    async with SessionLocal() as s:
        app = await pipeline.get_application(s, tenant_id=TENANT, application_id=process)
        cand = await s.get(Candidate, app.candidate_id)
        cand.salary_minimum = 90000  # above the 75k cap: code says no
        await s.commit()
    use(answer(score="9"))
    flags = (await _evaluate(process)).json()["flags"]
    assert any(f.startswith("Harter Filter") for f in flags), flags


async def test_a_failing_model_stores_nothing(process, use) -> None:
    use(RuntimeError("upstream said: Max Beispiel …"))
    res = await _evaluate(process)
    assert res.status_code == 502
    assert "Max Beispiel" not in res.text
    async with SessionLocal() as s:
        assert (await s.execute(select(AgentProposal))).first() is None


# --- the human decides ---------------------------------------------------------------


async def test_confirm_stores_the_checked_evaluation_with_ki_provenance(process, use) -> None:
    use(answer(tech="Java, Kubernetes"))
    proposal = (await _evaluate(process)).json()
    async with _client() as c:
        res = await c.post(f"{API}/proposals/{proposal['id']}/confirm")
    assert res.status_code == 200, res.text

    row = await _assessment(process)
    assert row is not None
    assert row.fit_score == 7
    assert row.technologies == ["Java"], "an ungrounded technology reached the record"
    assert row.verdict.startswith("Solider Java-Entwickler")
    assert row.basis.startswith("KI-Vorschlag (fake-model-1)")

    async with SessionLocal() as s:
        stored = await s.get(AgentProposal, uuid.UUID(proposal["id"]))
        assert stored.status == "confirmed"
        assert stored.args["text"] is None and stored.args["assessment"] is None
        receipts = (await s.execute(select(Receipt))).scalars().all()
        assert any(r.subject_id == proposal["id"] and r.verified for r in receipts)


async def test_decline_stores_nothing_and_erases_the_text(process, use) -> None:
    use(answer())
    proposal = (await _evaluate(process)).json()
    async with _client() as c:
        res = await c.post(f"{API}/proposals/{proposal['id']}/decline")
    assert res.status_code == 200
    assert await _assessment(process) is None
    async with SessionLocal() as s:
        stored = await s.get(AgentProposal, uuid.UUID(proposal["id"]))
        assert stored.args["text"] is None


async def test_a_recruiters_later_save_is_never_overwritten(process, use) -> None:
    use(answer())
    proposal = (await _evaluate(process)).json()
    async with SessionLocal() as s:
        await pipeline.set_assessment(
            s, tenant_id=TENANT, application_id=process, fit_score=4, verdict="Von Hand."
        )
    async with _client() as c:
        res = await c.post(f"{API}/proposals/{proposal['id']}/confirm")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "stale"
    row = await _assessment(process)
    assert row.fit_score == 4 and row.verdict == "Von Hand."


async def test_a_new_evaluation_supersedes_the_open_one(process, use) -> None:
    use(answer(score="6"))
    first = (await _evaluate(process)).json()
    use(answer(score="8"))
    second = (await _evaluate(process)).json()
    async with SessionLocal() as s:
        old = await s.get(AgentProposal, uuid.UUID(first["id"]))
        assert old.status == "stale" and old.args["text"] is None
    async with _client() as c:
        current = (await c.get(f"{API}/pipeline/applications/{process}/evaluation")).json()
    assert current["id"] == second["id"]


async def test_erasing_the_candidate_removes_the_open_evaluation(process, use, monkeypatch) -> None:
    """The proposal holds the model's text about the person (GDPR Art. 17)."""
    import datetime as dt

    from app.core.config import settings
    from app.domain.erasure import service as erasure

    monkeypatch.setattr(settings, "suppression_key", "k" * 32)
    use(answer())
    proposal = (await _evaluate(process)).json()
    async with SessionLocal() as s:
        app = await pipeline.get_application(s, tenant_id=TENANT, application_id=process)
        await erasure.erase_candidate(
            s, tenant_id=TENANT, candidate_id=app.candidate_id, confirm_name="Max Beispiel",
            reason="erasure", requested_on=dt.date(2026, 11, 15),
            actor_user_id="u", actor_name="A",
        )
        await s.commit()
    async with SessionLocal() as s:
        assert await s.get(AgentProposal, uuid.UUID(proposal["id"])) is None


async def test_another_workspace_cannot_evaluate(process, use) -> None:
    use(answer())
    async with _client() as c:
        res = await c.post(f"{API}/pipeline/applications/{uuid.uuid4()}/evaluation")
    assert res.status_code == 404
