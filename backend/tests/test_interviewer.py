"""The interviewer agent and the gates in front of it.

What these pin, most important first:

1. The feature is OFF unless every gate opens: the operator switch, the
   allowlist, and a workspace admin's consent to the CURRENT terms.
2. No question is asked and nothing extracted without the candidate's
   explicit consent to the current notice — and the candidate can always
   withdraw, even after the workspace switched the feature off.
3. Every value the interview writes is backed by the candidate's own words,
   re-derivable from them, and never overwrites what is already on file.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.interviewer import Answer, InterviewerAgent, InterviewerInput
from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.common.enums import ConfidenceSource
from app.domain.features import service as features
from app.domain.interviews import service as interviews
from app.domain.interviews.script import (
    CANDIDATE_NOTICE_VERSION,
    QUESTIONS,
    QUESTIONS_BY_KEY,
    parse_money,
    read_answer,
)
from app.domain.verification.schemas import ProposedChange
from app.domain.verification.service import list_receipts

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
TERMS = features.FEATURES["interviewer"].terms_version

ANSWERS = {
    "motivation": "Ich möchte mehr Verantwortung für Architektur übernehmen.",
    "technical_profile": "Java (Experte), Spring Boot, Kafka; MariaDB bekannt.",
    "salary_minimum": "Unter 92.000 € wechsle ich nicht.",
    "salary_expectation": "Ideal wären 100k.",
    "notice_period": "3 Monate zum Quartalsende",
    "employment_form": "Nur Festanstellung bitte.",
    "willing_to_relocate": "Nein, Remote oder München.",
    "interview_availability": "Mittwoch/Donnerstag ab 11 Uhr",
    "other_processes": "Ein Prozess, zweites Gespräch nächste Woche.",
}


@pytest.fixture
def api():
    from app.main import app as fastapi_app

    return AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t")


@pytest.fixture
def switch_on(monkeypatch):
    monkeypatch.setattr(settings, "interviewer_enabled", True)
    monkeypatch.setattr(settings, "interviewer_allowed_tenants", "")


async def _candidate(api, **fields) -> str:
    r = await api.post("/api/v1/candidates", json={"full_name": "Jana Beispiel", **fields})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _enable(api) -> None:
    r = await api.post("/api/v1/features/interviewer/consent", json={"terms_version": TERMS})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True


async def _consented_interview(api, candidate_id: str) -> str:
    r = await api.post("/api/v1/interviews", json={"candidate_id": candidate_id})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "awaiting_consent" and body["notice"]
    r = await api.post(
        f"/api/v1/interviews/{body['id']}/consent",
        json={"notice_version": body["notice_version"], "confirmed": True},
    )
    assert r.status_code == 200, r.text
    return body["id"]


async def _answer_all(api, interview_id: str, answers: dict[str, str]) -> dict:
    body = {}
    for q in QUESTIONS:
        r = await api.post(
            f"/api/v1/interviews/{interview_id}/answers",
            json={"text": answers.get(q.key, "keine Angabe")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
    return body


# --- 1. the workspace gate ---------------------------------------------------


async def test_off_by_default(api) -> None:
    async with api:
        status = (await api.get("/api/v1/features")).json()
        interviewer = next(f for f in status if f["key"] == "interviewer")
        assert interviewer["available"] is False and interviewer["enabled"] is False

        cid = await _candidate(api)
        r = await api.post("/api/v1/interviews", json={"candidate_id": cid})
        assert r.status_code == 403
        # Nor can an admin opt in while the operator switch is off.
        r = await api.post(
            "/api/v1/features/interviewer/consent", json={"terms_version": TERMS}
        )
        assert r.status_code == 403


async def test_allowlist_excludes_other_workspaces(api, monkeypatch) -> None:
    monkeypatch.setattr(settings, "interviewer_enabled", True)
    monkeypatch.setattr(settings, "interviewer_allowed_tenants", str(uuid.uuid4()))
    async with api:
        r = await api.post(
            "/api/v1/features/interviewer/consent", json={"terms_version": TERMS}
        )
        assert r.status_code == 403
    monkeypatch.setattr(settings, "interviewer_allowed_tenants", f" {TENANT} ,x")
    async with SessionLocal() as s:
        st = await features.status(s, tenant_id=TENANT, key="interviewer")
    assert st.available is True and st.enabled is False


async def test_available_is_not_enabled_until_an_admin_consents(api, switch_on) -> None:
    async with api:
        cid = await _candidate(api)
        r = await api.post("/api/v1/interviews", json={"candidate_id": cid})
        assert r.status_code == 403
        assert "Administrator" in r.json()["detail"]

        stale = await api.post(
            "/api/v1/features/interviewer/consent", json={"terms_version": "1999-01-01"}
        )
        assert stale.status_code == 409

        await _enable(api)
        r = await api.post("/api/v1/interviews", json={"candidate_id": cid})
        assert r.status_code == 201

    async with SessionLocal() as s:
        receipts = await list_receipts(s, tenant_id=TENANT)
    assert any(r.subject_type == "feature" and "enabled" in r.summary for r in receipts)


async def test_new_terms_need_new_consent(api, switch_on, monkeypatch) -> None:
    async with api:
        await _enable(api)
    bumped = features.FeatureDef(
        **{**features.FEATURES["interviewer"].__dict__, "terms_version": "2099-01-01"}
    )
    monkeypatch.setitem(features.FEATURES, "interviewer", bumped)
    async with SessionLocal() as s:
        st = await features.status(s, tenant_id=TENANT, key="interviewer")
    assert st.available and not st.enabled and "erneut" in (st.reason or "")


async def test_revoking_closes_the_gate_but_not_withdrawal(api, switch_on) -> None:
    async with api:
        await _enable(api)
        cid = await _candidate(api)
        iid = await _consented_interview(api, cid)
        await api.post(f"/api/v1/interviews/{iid}/answers", json={"text": "Neugier."})

        r = await api.delete("/api/v1/features/interviewer/consent")
        assert r.json()["enabled"] is False

        assert (await api.post(f"/api/v1/interviews/{iid}/answers", json={"text": "x"})).status_code == 403
        assert (await api.post(f"/api/v1/interviews/{iid}/complete")).status_code == 403
        # The candidate's right to withdraw does not depend on the switch.
        r = await api.post(f"/api/v1/interviews/{iid}/withdraw")
        assert r.status_code == 200
        assert r.json()["status"] == "withdrawn" and r.json()["turns"] == []


# --- 2. the candidate gate ---------------------------------------------------


async def test_no_question_without_candidate_consent(api, switch_on) -> None:
    async with api:
        await _enable(api)
        cid = await _candidate(api)
        iid = (await api.post("/api/v1/interviews", json={"candidate_id": cid})).json()["id"]

        r = await api.post(f"/api/v1/interviews/{iid}/answers", json={"text": "hallo"})
        assert r.status_code == 409
        r = await api.post(
            f"/api/v1/interviews/{iid}/consent",
            json={"notice_version": CANDIDATE_NOTICE_VERSION, "confirmed": False},
        )
        assert r.status_code == 409
        r = await api.post(
            f"/api/v1/interviews/{iid}/consent",
            json={"notice_version": "old", "confirmed": True},
        )
        assert r.status_code == 409

        body = (await api.get(f"/api/v1/interviews/{iid}")).json()
        assert body["status"] == "awaiting_consent" and body["next_question"] is None


# --- 3. the interview itself -------------------------------------------------


async def test_full_interview_writes_evidence_backed_fields(api, switch_on) -> None:
    async with api:
        await _enable(api)
        cid = await _candidate(api)
        iid = await _consented_interview(api, cid)
        last = await _answer_all(api, iid, ANSWERS)
        assert last["next_question"] is None and len(last["turns"]) == len(QUESTIONS)

        done = (await api.post(f"/api/v1/interviews/{iid}/complete")).json()
        assert done["status"] == "completed"
        fields = done["outcome"]["fields"]
        assert fields["salary_minimum"]["committed"] is True
        assert fields["salary_minimum"]["value"] == "92000"
        assert fields["salary_minimum"]["quote"] == "92.000"
        assert fields["employment_form"]["value"] == "festanstellung"
        assert fields["willing_to_relocate"]["value"] == "nein"

        cand = (await api.get(f"/api/v1/candidates/{cid}")).json()
    assert cand["salary_minimum"] == 92000
    assert cand["salary_expectation"] == 100000
    assert cand["notice_period"] == "3 Monate zum Quartalsende"
    assert cand["motivation"].startswith("Ich möchte")
    # What a candidate says is a claim, not evidence.
    assert cand["verification_score"] == 0.0


async def test_conflicts_and_ranges_go_to_a_recruiter(api, switch_on) -> None:
    async with api:
        await _enable(api)
        cid = await _candidate(api, notice_period="6 Wochen")
        iid = await _consented_interview(api, cid)
        await _answer_all(api, iid, {**ANSWERS, "salary_minimum": "so 92-95k"})
        fields = (await api.post(f"/api/v1/interviews/{iid}/complete")).json()["outcome"]["fields"]
        cand = (await api.get(f"/api/v1/candidates/{cid}")).json()

    assert fields["notice_period"]["needs_human_review"] is True
    assert "Recruiter entscheidet" in fields["notice_period"]["reason"]
    assert cand["notice_period"] == "6 Wochen"  # not overwritten

    assert fields["salary_minimum"]["needs_human_review"] is True
    assert cand["salary_minimum"] is None


async def test_interviews_are_tenant_scoped(api, switch_on) -> None:
    async with api:
        await _enable(api)
        cid = await _candidate(api)
        iid = await _consented_interview(api, cid)
    async with SessionLocal() as s:
        with pytest.raises(interviews.NotFound):
            await interviews.get_interview(
                s, tenant_id=uuid.uuid4(), interview_id=uuid.UUID(iid)
            )


# --- the agent's postconditions, directly -------------------------------------


async def test_a_value_not_in_the_candidates_words_fails() -> None:
    tenant, cand, iid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    agent = InterviewerAgent()
    await agent.run(
        InterviewerInput(
            tenant_id=tenant, candidate_id=cand, interview_id=iid,
            answers=[Answer(question_key="salary_minimum", text="mindestens 80k")],
        )
    )

    def check(value: str, field: str = "salary_minimum",
              source: ConfidenceSource = ConfidenceSource.SELF_REPORTED) -> list[bool]:
        change = ProposedChange(
            tenant_id=tenant, entity_type="candidate", entity_id=cand,
            field=field, proposed_value=value, source=source, confidence=0.9,
        )
        return [pc(change)[0] for pc in agent.postconditions()]

    assert all(check("80000"))
    assert not all(check("120000"))  # a model "improving" the number
    assert not all(check("80000", source=ConfidenceSource.HUMAN_VERIFIED))
    assert not all(check("citizen", field="work_permit"))


def test_reading_money() -> None:
    assert parse_money("92.000") == 92000
    assert parse_money("92 000") == 92000
    assert parse_money("92k") == 92000
    assert parse_money("92,5k") == 92500
    assert parse_money("95 Tausend") == 95000
    assert parse_money("3") is None  # years, not salary
    assert parse_money("5000000") is None

    q = QUESTIONS_BY_KEY["salary_expectation"]
    assert read_answer(q, "keine Angabe") is None
    assert read_answer(q, "100").confidence < 0.75  # no unit → a person confirms
    assert read_answer(q, "ca. 110.000 Euro").value == "110000"


def test_the_script_never_asks_for_protected_or_hard_criteria() -> None:
    fields = {q.field for q in QUESTIONS}
    assert not fields & {"work_permit", "date_of_birth", "sex", "country", "nationality"}
