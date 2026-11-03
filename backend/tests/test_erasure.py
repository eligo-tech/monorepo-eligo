"""Erasing a person inside a workspace (GDPR Art. 17/21), and keeping them erased.

Builds one candidate with something in every table that refers to a person —
CV, process and its steps, assessment, match result, notice, note, interview,
provenance, an open AI proposal, receipts in the old format that carry their
e-mail — next to a second candidate in the same workspace and one in another
workspace. Erasing the first must remove all of theirs, black out their
receipts with the chain still verifying, log the request without naming them,
and leave the other two exactly as they were.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ConfidenceSource, ReceiptAction
from app.domain.companies.models import Company
from app.domain.documents.models import CandidateDocument
from app.domain.erasure import service as erasure
from app.domain.erasure.models import ErasureRequest, TenantSuppression
from app.domain.interviews.models import Interview
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.matching.models import MatchReceipt
from app.domain.notices.models import CandidateNotice
from app.domain.pipeline.models import Application, ApplicationAssessment, ProcessStep
from app.domain.proposals.models import AgentProposal
from app.domain.verification import service as verification
from app.domain.verification.models import BLACKOUT_SUMMARY, EnrichmentRecord, Receipt
from app.domain.verification.schemas import ProposedChange

EMAIL = "Erika.Muster@Example.org"
KEY = "k" * 40


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(settings, "suppression_key", KEY)


async def _person(s, tenant: uuid.UUID, name: str, email: str, ext: str) -> dict:
    company = Company(tenant_id=tenant, name=f"Kunde {name}")
    s.add(company)
    await s.flush()
    job = Job(tenant_id=tenant, title="Backend", client_company_id=company.id)
    cand = Candidate(
        tenant_id=tenant, full_name=name, email=email,
        external_source="aifind", external_id=ext, merged_identities=[f"recruitee:{ext}"],
    )
    s.add_all([job, cand])
    await s.flush()
    app_ = Application(tenant_id=tenant, candidate_id=cand.id, job_id=job.id)
    s.add(app_)
    await s.flush()
    rows = [
        ProcessStep(tenant_id=tenant, application_id=app_.id, step_key="cv_sent"),
        ApplicationAssessment(tenant_id=tenant, application_id=app_.id),
        MatchReceipt(tenant_id=tenant, candidate_id=cand.id, job_id=job.id, passed_hard_filters=True),
        CandidateDocument(tenant_id=tenant, candidate_id=cand.id, filename="cv.pdf",
                          byte_size=4, content=b"%PDF"),
        CandidateNotice(tenant_id=tenant, candidate_id=cand.id, email=email,
                        token=uuid.uuid4().hex, subject="s", body="b"),
        ManagerInteraction(tenant_id=tenant, candidate_id=cand.id, interaction_type="note",
                           occurred_at=dt.datetime.now(dt.UTC), summary=f"Telefonat mit {name}"),
        Interview(tenant_id=tenant, candidate_id=cand.id, script_version="v1", started_by="T"),
        AgentProposal(tenant_id=tenant, kind="step", tool="pipeline.propose_step",
                      title=f"{name} · Backend", args={"application_id": str(app_.id)}),
    ]
    s.add_all(rows)
    await s.flush()
    # Provenance + a receipt in the format production still holds.
    await verification.verify_and_commit(
        s, agent="test",
        change=ProposedChange(tenant_id=tenant, entity_type="candidate", entity_id=cand.id,
                              field="email", proposed_value=email,
                              source=ConfidenceSource.HUMAN_VERIFIED, confidence=1.0),
    )
    await verification.append_receipt(
        s, tenant_id=tenant, agent="recruiter", action=ReceiptAction.WRITE,
        subject_type="candidate", subject_id=str(cand.id), verified=True,
        summary=f"write email={email!r}", payload={"field": "email", "value": email},
    )
    await verification.append_receipt(
        s, tenant_id=tenant, agent="notices", action=ReceiptAction.ASSERT,
        subject_type="candidate_notice", subject_id=str(rows[4].id), verified=True,
        summary=f"Art.-14-Benachrichtigung an {email} versandt",
        payload={"candidate_id": str(cand.id)},
    )
    return {"candidate": cand.id, "application": app_.id, "job": job.id}


async def _count(s, model, **where) -> int:
    q = select(func.count()).select_from(model)
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return (await s.execute(q)).scalar_one()


async def _ledger_text(s, tenant) -> str:
    rows = (await s.execute(select(Receipt).where(Receipt.tenant_id == tenant))).scalars()
    return " ".join(r.summary + json.dumps(r.payload) for r in rows)


async def _world():
    await create_all()
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        erika = await _person(s, tenant, "Erika Muster", EMAIL, "ext-1")
        max_ = await _person(s, tenant, "Max Bleibt", "max@example.org", "ext-2")
        twin = await _person(s, other_tenant, "Erika Muster", EMAIL, "ext-1")
        await s.commit()
    return tenant, other_tenant, erika, max_, twin


async def _erase(tenant, candidate_id, name="Erika Muster"):
    async with SessionLocal() as s:
        req = await erasure.erase_candidate(
            s, tenant_id=tenant, candidate_id=candidate_id, confirm_name=name,
            reason="erasure", requested_on=dt.date(2026, 11, 1),
            actor_user_id="user_admin", actor_name="A. Admin",
        )
        await s.commit()
        return req


PER_CANDIDATE = [
    (Application, "candidate_id"), (MatchReceipt, "candidate_id"),
    (CandidateDocument, "candidate_id"), (CandidateNotice, "candidate_id"),
    (ManagerInteraction, "candidate_id"), (Interview, "candidate_id"),
]


async def test_erasing_a_candidate_removes_everything_that_refers_to_them() -> None:
    tenant, _, erika, _, _ = await _world()
    await _erase(tenant, erika["candidate"])
    async with SessionLocal() as s:
        assert await s.get(Candidate, erika["candidate"]) is None
        for model, col in PER_CANDIDATE:
            assert await _count(s, model, **{col: erika["candidate"]}) == 0, model.__tablename__
        assert await _count(s, ProcessStep, application_id=erika["application"]) == 0
        assert await _count(s, ApplicationAssessment, application_id=erika["application"]) == 0
        assert await _count(s, EnrichmentRecord, entity_id=erika["candidate"]) == 0
        proposals = (await s.execute(select(AgentProposal).where(AgentProposal.tenant_id == tenant))).scalars()
        assert all(str(erika["application"]) not in json.dumps(p.args) for p in proposals)


async def test_their_receipts_are_blacked_out_and_the_chain_still_verifies() -> None:
    tenant, _, erika, _, _ = await _world()
    req = await _erase(tenant, erika["candidate"])
    async with SessionLocal() as s:
        text = await _ledger_text(s, tenant)
        ok, why = await verification.verify_chain(s, tenant_id=tenant)
        blacked = await _count(s, Receipt, summary=BLACKOUT_SUMMARY)
    assert EMAIL not in text and EMAIL.lower() not in text
    assert "Erika" not in text
    assert ok, why
    assert blacked >= 3
    assert req.counts["receipts_blacked_out"] >= 3


async def test_everyone_else_is_untouched() -> None:
    tenant, other_tenant, erika, max_, twin = await _world()
    await _erase(tenant, erika["candidate"])
    async with SessionLocal() as s:
        assert await s.get(Candidate, max_["candidate"]) is not None
        assert await s.get(Candidate, twin["candidate"]) is not None
        for model, col in PER_CANDIDATE:
            assert await _count(s, model, **{col: max_["candidate"]}) == 1, model.__tablename__
            assert await _count(s, model, **{col: twin["candidate"]}) == 1, model.__tablename__
        assert "max@example.org" in await _ledger_text(s, tenant)
        assert EMAIL in await _ledger_text(s, other_tenant)
        ok, why = await verification.verify_chain(s, tenant_id=other_tenant)
    assert ok, why


async def test_the_request_log_and_the_suppression_list_name_nobody() -> None:
    tenant, _, erika, _, _ = await _world()
    req = await _erase(tenant, erika["candidate"])
    async with SessionLocal() as s:
        log = await s.get(ErasureRequest, req.id)
        keys = (await s.execute(select(TenantSuppression).where(TenantSuppression.tenant_id == tenant))).scalars().all()
    stored = json.dumps({c.name: str(getattr(log, c.name)) for c in ErasureRequest.__table__.columns})
    stored += json.dumps([[k.kind, k.digest] for k in keys])
    for value in (EMAIL, EMAIL.lower(), "Erika", "ext-1", str(erika["candidate"])):
        assert value not in stored, value
    assert log.requested_on == dt.date(2026, 11, 1)
    assert log.executed_by_name == "A. Admin"
    # aifind:ext-1, recruitee:ext-1 (merged), e-mail.
    assert sorted(k.kind for k in keys) == ["email", "import_id", "import_id"]


async def test_a_name_that_does_not_match_erases_nothing() -> None:
    tenant, _, erika, _, _ = await _world()
    with pytest.raises(erasure.NameMismatch):
        await _erase(tenant, erika["candidate"], name="Max Bleibt")
    async with SessionLocal() as s:
        assert await s.get(Candidate, erika["candidate"]) is not None


async def test_another_workspaces_candidate_cannot_be_erased_from_here() -> None:
    tenant, _, _, _, twin = await _world()
    with pytest.raises(erasure.NotFound):
        await _erase(tenant, twin["candidate"])


async def test_without_a_key_nothing_is_erased(monkeypatch) -> None:
    tenant, _, erika, _, _ = await _world()
    monkeypatch.setattr(settings, "suppression_key", None)
    with pytest.raises(erasure.NotConfigured):
        await _erase(tenant, erika["candidate"])
    async with SessionLocal() as s:
        assert await s.get(Candidate, erika["candidate"]) is not None


async def test_the_fingerprint_matches_however_the_address_is_written() -> None:
    tenant = uuid.uuid4()
    assert erasure.digest(tenant, "email", " Erika.Muster@EXAMPLE.org ") == erasure.digest(
        tenant, "email", "erika.muster@example.org"
    )
    assert erasure.digest(tenant, "email", "a@b.de") != erasure.digest(uuid.uuid4(), "email", "a@b.de")


# --- contacts ----------------------------------------------------------------


async def test_erasing_a_contact_keeps_their_mandates_and_unlinks_them() -> None:
    await create_all()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        company = Company(tenant_id=tenant, name="Kunde")
        s.add(company)
        await s.flush()
        boss = Manager(tenant_id=tenant, company_id=company.id, full_name="Hans Chef",
                       email="hans@kunde.de", external_source="aifind", external_id="m-1")
        s.add(boss)
        await s.flush()
        job = Job(tenant_id=tenant, title="CTO", client_company_id=company.id, manager_id=boss.id)
        note = ManagerInteraction(tenant_id=tenant, manager_id=boss.id, interaction_type="note",
                                  occurred_at=dt.datetime.now(dt.UTC), summary="Budget im November")
        s.add_all([job, note])
        await verification.append_receipt(
            s, tenant_id=tenant, agent="recruiter", action=ReceiptAction.WRITE,
            subject_type="manager", subject_id=str(boss.id), verified=True,
            summary="write email='hans@kunde.de'", payload={"field": "email", "value": "hans@kunde.de"},
        )
        await s.commit()
        ids = (boss.id, job.id, note.id)
    async with SessionLocal() as s:
        await erasure.erase_manager(
            s, tenant_id=tenant, manager_id=ids[0], confirm_name="Hans Chef", reason="objection",
            requested_on=dt.date(2026, 11, 2), actor_user_id="u", actor_name="A",
        )
        await s.commit()
    async with SessionLocal() as s:
        assert await s.get(Manager, ids[0]) is None
        assert await s.get(ManagerInteraction, ids[2]) is None
        kept = await s.get(Job, ids[1])
        assert kept is not None and kept.manager_id is None
        assert "hans@kunde.de" not in await _ledger_text(s, tenant)
        ok, why = await verification.verify_chain(s, tenant_id=tenant)
    assert ok, why


# --- the next import ---------------------------------------------------------


def _export(*candidates, managers=(), companies=()):
    from app.domain.atsimport.connectors.base import AtsExport

    return AtsExport(companies=list(companies), managers=list(managers), candidates=list(candidates))


async def _import(tenant, export):
    from app.domain.atsimport import service as importer

    async with SessionLocal() as s:
        return await importer.import_export(s, tenant_id=tenant, export=export, source="aifind")


async def _names(tenant) -> set[str]:
    async with SessionLocal() as s:
        rows = (await s.execute(select(Candidate.full_name).where(Candidate.tenant_id == tenant))).all()
    return {r for (r,) in rows}


async def test_the_next_import_does_not_bring_an_erased_candidate_back() -> None:
    from app.domain.atsimport.connectors.base import SourcedCandidate

    tenant, other_tenant, erika, _, _ = await _world()
    await _erase(tenant, erika["candidate"])
    summary = await _import(tenant, _export(
        SourcedCandidate(external_id="ext-1", full_name="Erika Muster"),          # same import id
        SourcedCandidate(external_id="new-9", full_name="E. Muster", email=EMAIL.upper()),  # same address
        SourcedCandidate(external_id="new-10", full_name="Neu Person", email="neu@example.org"),
    ))
    names = await _names(tenant)
    assert "Erika Muster" not in names and "E. Muster" not in names
    assert "Neu Person" in names
    assert summary.candidates_suppressed == 2
    assert summary.candidates_created == 1
    # The suppression is this workspace's: the other one imports her as before.
    await _import(other_tenant, _export(SourcedCandidate(external_id="new-11", full_name="Erika Neu", email=EMAIL)))
    assert "Erika Neu" in await _names(other_tenant)


async def test_the_next_import_does_not_bring_an_erased_contact_back() -> None:
    from app.domain.atsimport.connectors.base import SourcedCompany, SourcedManager, SourcedNote

    await create_all()
    tenant = uuid.uuid4()
    acme = SourcedCompany(external_id="co-1", name="Kunde")
    note = SourcedNote(external_id="n-1", category="note", text="Budget", created_at=None)
    hans = SourcedManager(external_id="m-1", full_name="Hans Chef", company_external_id="co-1",
                          email="hans@kunde.de", notes=[note])
    await _import(tenant, _export(managers=[hans], companies=[acme]))
    async with SessionLocal() as s:
        boss = (await s.execute(select(Manager).where(Manager.tenant_id == tenant))).scalar_one()
        await erasure.erase_manager(
            s, tenant_id=tenant, manager_id=boss.id, confirm_name="Hans Chef", reason="erasure",
            requested_on=dt.date(2026, 11, 2), actor_user_id="u", actor_name="A",
        )
        await s.commit()
    summary = await _import(tenant, _export(managers=[hans], companies=[acme]))
    async with SessionLocal() as s:
        assert await _count(s, Manager, tenant_id=tenant) == 0
        assert await _count(s, ManagerInteraction, tenant_id=tenant) == 0
    assert summary.managers_suppressed == 1


async def test_an_import_refuses_to_run_when_it_cannot_check_the_list(monkeypatch) -> None:
    from app.domain.atsimport.connectors.base import SourcedCandidate

    tenant, _, erika, _, _ = await _world()
    await _erase(tenant, erika["candidate"])
    monkeypatch.setattr(settings, "suppression_key", None)
    with pytest.raises(erasure.NotConfigured):
        await _import(tenant, _export(SourcedCandidate(external_id="ext-1", full_name="Erika Muster")))
    assert "Erika Muster" not in await _names(tenant)


async def test_a_workspace_without_erasures_imports_without_a_key(monkeypatch) -> None:
    from app.domain.atsimport.connectors.base import SourcedCandidate

    await create_all()
    tenant = uuid.uuid4()
    monkeypatch.setattr(settings, "suppression_key", None)
    summary = await _import(tenant, _export(SourcedCandidate(external_id="x", full_name="Ohne Schlüssel")))
    assert summary.candidates_created == 1


# --- a person added again by hand ---------------------------------------------


def _client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_adding_an_erased_candidate_by_hand_is_refused_with_the_date() -> None:
    tenant = settings.default_tenant_id
    await create_all()
    async with SessionLocal() as s:
        erika = await _person(s, tenant, "Erika Muster", EMAIL, f"ext-{uuid.uuid4()}")
        await s.commit()
    await _erase(tenant, erika["candidate"])
    async with _client() as c:
        resp = await c.post(f"{settings.api_v1_prefix}/candidates",
                            json={"full_name": "Erika M.", "email": EMAIL.lower()})
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "suppressed"
    assert detail["requested_on"] == "2026-11-01"
    assert EMAIL.lower() not in resp.text  # the answer does not echo the address


async def test_confirming_that_they_came_back_creates_them_and_lifts_only_the_address() -> None:
    from app.domain.atsimport.connectors.base import SourcedCandidate

    tenant = settings.default_tenant_id
    await create_all()
    ext = f"ext-{uuid.uuid4()}"
    async with SessionLocal() as s:
        erika = await _person(s, tenant, "Erika Muster", EMAIL, ext)
        await s.commit()
    await _erase(tenant, erika["candidate"])
    async with _client() as c:
        resp = await c.post(f"{settings.api_v1_prefix}/candidates",
                            json={"full_name": "Erika M.", "email": EMAIL,
                                  "override_suppression": True})
    assert resp.status_code == 201, resp.text
    async with SessionLocal() as s:
        keys = (await s.execute(select(TenantSuppression).where(
            TenantSuppression.tenant_id == tenant,
            TenantSuppression.digest == erasure.digest(tenant, "email", EMAIL)))).scalars().all()
    assert keys and all(k.lifted_at is not None for k in keys)
    # The old ATS record — the data she asked to have deleted — stays out.
    summary = await _import(tenant, _export(SourcedCandidate(external_id=ext, full_name="Erika Muster", email=EMAIL)))
    assert summary.candidates_suppressed == 1


async def test_adding_an_erased_contact_by_hand_is_refused() -> None:
    await create_all()
    tenant = settings.default_tenant_id
    async with SessionLocal() as s:
        company = Company(tenant_id=tenant, name=f"Kunde {uuid.uuid4()}")
        s.add(company)
        await s.flush()
        boss = Manager(tenant_id=tenant, company_id=company.id, full_name="Hans Chef",
                       email="hans.chef@kunde.de")
        s.add(boss)
        await s.commit()
        ids = (company.id, boss.id)
    async with SessionLocal() as s:
        await erasure.erase_manager(s, tenant_id=tenant, manager_id=ids[1], confirm_name="hans chef",
                                    reason="erasure", requested_on=dt.date(2026, 11, 2),
                                    actor_user_id="u", actor_name="A")
        await s.commit()
    async with _client() as c:
        resp = await c.post(f"{settings.api_v1_prefix}/managers",
                            json={"company_id": str(ids[0]), "full_name": "H. Chef",
                                  "email": "Hans.Chef@kunde.de"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "suppressed"


# --- the endpoints -----------------------------------------------------------


async def _api_person(name: str) -> uuid.UUID:
    await create_all()
    async with SessionLocal() as s:
        p = await _person(s, settings.default_tenant_id, name, f"{uuid.uuid4().hex}@example.org",
                          f"ext-{uuid.uuid4()}")
        await s.commit()
    return p["candidate"]


BODY = {"confirm_name": "Api Person", "reason": "erasure", "requested_on": "2026-11-01"}


async def test_an_admin_erases_through_the_api_and_sees_it_in_the_log() -> None:
    cid = await _api_person("Api Person")
    async with _client() as c:
        resp = await c.post(f"{settings.api_v1_prefix}/erasure/candidates/{cid}", json=BODY)
        log = await c.get(f"{settings.api_v1_prefix}/erasure/requests")
    assert resp.status_code == 201, resp.text
    assert resp.json()["counts"]["candidates"] == 1
    assert resp.json()["id"] in [r["id"] for r in log.json()]
    assert str(cid) not in log.text


async def test_a_recruiter_cannot_erase() -> None:
    from app.core.auth import RECRUITER, Actor, get_current_actor
    from app.main import app

    cid = await _api_person("Api Person")
    app.dependency_overrides[get_current_actor] = lambda: Actor(
        tenant_id=settings.default_tenant_id, user_id="u_rec", name="R", role=RECRUITER, role_known=True
    )
    try:
        async with _client() as c:
            resp = await c.post(f"{settings.api_v1_prefix}/erasure/candidates/{cid}", json=BODY)
            log = await c.get(f"{settings.api_v1_prefix}/erasure/requests")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403 and log.status_code == 403
    async with SessionLocal() as s:
        assert await s.get(Candidate, cid) is not None


async def test_the_api_refuses_a_wrong_name_and_a_missing_key(monkeypatch) -> None:
    cid = await _api_person("Api Person")
    async with _client() as c:
        wrong = await c.post(f"{settings.api_v1_prefix}/erasure/candidates/{cid}",
                             json={**BODY, "confirm_name": "Someone Else"})
        monkeypatch.setattr(settings, "suppression_key", None)
        unset = await c.post(f"{settings.api_v1_prefix}/erasure/candidates/{cid}", json=BODY)
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "name_mismatch"
    assert unset.status_code == 503 and unset.json()["detail"]["code"] == "erasure_not_configured"
    async with SessionLocal() as s:
        assert await s.get(Candidate, cid) is not None


async def test_editing_someone_else_to_an_erased_address_is_refused_too() -> None:
    """Create was guarded; an edit setting the same address is the same act."""
    tenant = settings.default_tenant_id
    await create_all()
    async with SessionLocal() as s:
        erika = await _person(s, tenant, "Erika Muster", EMAIL, f"ext-{uuid.uuid4()}")
        other = await _person(s, tenant, "Max Bleibt", f"{uuid.uuid4().hex}@example.org", f"ext-{uuid.uuid4()}")
        company = Company(tenant_id=tenant, name=f"Kunde {uuid.uuid4()}")
        s.add(company)
        await s.flush()
        boss = Manager(tenant_id=tenant, company_id=company.id, full_name="Hans Neu")
        s.add(boss)
        await s.commit()
        boss_id = boss.id
    await _erase(tenant, erika["candidate"])
    base = settings.api_v1_prefix
    async with _client() as c:
        cand = await c.patch(f"{base}/candidates/{other['candidate']}", json={"email": EMAIL})
        mgr = await c.patch(f"{base}/managers/{boss_id}", json={"email": EMAIL.lower()})
        ok = await c.patch(f"{base}/candidates/{other['candidate']}",
                           json={"email": EMAIL, "override_suppression": True})
    assert cand.status_code == 409 and cand.json()["detail"]["code"] == "suppressed"
    assert mgr.status_code == 409
    assert ok.status_code == 200, ok.text


async def test_the_log_shows_when_a_suppression_was_lifted_and_by_whom() -> None:
    """Lifting lets a person back in, so the admin must be able to see it."""
    from app.core.context import ActorRef, current_actor_var

    tenant = settings.default_tenant_id
    await create_all()
    email = f"{uuid.uuid4().hex}@example.org"
    async with SessionLocal() as s:
        p = await _person(s, tenant, "Lift Person", email, f"ext-{uuid.uuid4()}")
        await s.commit()
    req = await _erase(tenant, p["candidate"], name="Lift Person")
    token = current_actor_var.set(ActorRef(user_id="u_rec", name="R. Recruiter"))
    try:
        async with SessionLocal() as s:
            await erasure.guard_readd(s, tenant_id=tenant, email=email, override=True)
            await s.commit()
    finally:
        current_actor_var.reset(token)
    async with _client() as c:
        rows = (await c.get(f"{settings.api_v1_prefix}/erasure/requests")).json()
    row = next(r for r in rows if r["id"] == str(req.id))
    assert row["lifted"] == 1
    assert row["last_lifted_by"] == "R. Recruiter"
    assert row["last_lifted_at"] is not None


async def test_the_cv_preview_says_the_address_belongs_to_someone_erased(monkeypatch) -> None:
    """So the recruiter is asked BEFORE saving — a refused save would run the
    (paid, nondeterministic) extraction again."""
    from app.domain.documents import parser
    from app.domain.documents import service as documents
    from app.agents.document_extraction import ExtractedField
    from app.domain.documents.extraction.base import CVSections

    tenant = settings.default_tenant_id
    await create_all()
    email = f"{uuid.uuid4().hex}@example.org"
    async with SessionLocal() as s:
        p = await _person(s, tenant, "Cv Person", email, f"ext-{uuid.uuid4()}")
        await s.commit()
    await _erase(tenant, p["candidate"], name="Cv Person")
    text = f"Cv Person\n{email}\nBackend Engineer\n" * 3
    monkeypatch.setattr(parser, "pdf_to_text", lambda content: text)
    monkeypatch.setattr(documents, "_run_extractor", lambda t: (
        [ExtractedField(field="full_name", value="Cv Person", confidence=0.99),
         ExtractedField(field="email", value=email.upper(), confidence=0.99)],
        CVSections(), "fake"))
    async with SessionLocal() as s:
        preview = await documents.extract_cv(s, filename="cv.pdf", content=b"%PDF", tenant_id=tenant, persist=False)
        clean = await documents.extract_cv(s, filename="cv.pdf", content=b"%PDF", tenant_id=uuid.uuid4(), persist=False)
    assert str(preview.suppressed_on) == "2026-11-01"
    assert clean.suppressed_on is None


async def test_a_requested_on_date_in_the_future_is_refused() -> None:
    cid = await _api_person("Api Person")
    async with _client() as c:
        resp = await c.post(f"{settings.api_v1_prefix}/erasure/candidates/{cid}",
                            json={**BODY, "requested_on": "2099-01-01"})
    assert resp.status_code == 422
    async with SessionLocal() as s:
        assert await s.get(Candidate, cid) is not None
