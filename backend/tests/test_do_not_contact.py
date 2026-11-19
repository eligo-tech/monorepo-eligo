"""ELI-32: "Nicht mehr kontaktieren", and a confirmation to the person.

A manager or a candidate who, on a call, says "please do not contact me
again" is marked do-not-contact from the note composer: the record stays, the
call lists stop offering them, a person can undo it, and every step leaves an
append-only receipt that names ids only. On request the person gets a short
confirmation e-mail through the same sender as the Art. 14 notice — and the
erasure dialog can send one too, to the address read BEFORE it is wiped.

The mailer is always faked here: nothing may leave the building from a test.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.companies.models import Company
from app.domain.erasure import do_not_contact
from app.domain.hub import call_list
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.notices import service as notices
from app.domain.notices.delivery.base import EmailNotConfigured, SentMessage
from app.domain.notices.models import CandidateNotice
from app.domain.verification.models import Receipt

TENANT = settings.default_tenant_id
API = settings.api_v1_prefix
NOW = dt.datetime(2026, 11, 11, 9, 0, tzinfo=dt.UTC)


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class _Recorder:
    name = "recorder"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, *, to, subject, text, reply_to=None) -> SentMessage:
        self.sent.append({"to": to, "subject": subject, "text": text})
        return SentMessage(provider=self.name, message_id="msg_42")


@pytest.fixture
def mailer(monkeypatch) -> _Recorder:
    sender = _Recorder()
    monkeypatch.setattr(do_not_contact, "get_email_sender", lambda cfg=None: sender)
    monkeypatch.setattr(do_not_contact, "email_is_configured", lambda cfg=None: True)
    return sender


@pytest.fixture
def no_mailer(monkeypatch) -> None:
    def _unconfigured(cfg=None):
        raise EmailNotConfigured("no email provider is configured")

    monkeypatch.setattr(do_not_contact, "get_email_sender", _unconfigured)
    monkeypatch.setattr(do_not_contact, "email_is_configured", lambda cfg=None: False)


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(settings, "suppression_key", "k" * 40)


async def _manager(email: str | None = "stefan.halama@example.org", **kw) -> uuid.UUID:
    await create_all()
    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name=kw.pop("company", "Halama GmbH"))
        s.add(company)
        await s.flush()
        boss = Manager(tenant_id=TENANT, company_id=company.id, full_name=kw.pop("name", "Stefan Halama"),
                       email=email, stage=kw.pop("stage", "bus_dev"), **kw)
        s.add(boss)
        await s.commit()
        return boss.id


async def _candidate(email: str | None = "jana.keller@example.com") -> uuid.UUID:
    await create_all()
    async with SessionLocal() as s:
        cand = Candidate(tenant_id=TENANT, full_name="Jana Keller", email=email)
        s.add(cand)
        await s.commit()
        return cand.id


async def _receipts(subject_id: str) -> list[Receipt]:
    async with SessionLocal() as s:
        return list((await s.scalars(
            select(Receipt).where(Receipt.tenant_id == TENANT, Receipt.subject_id == subject_id)
            .order_by(Receipt.chain_index)
        )).all())


def _note(**kw) -> dict:
    return {"interaction_type": "business_call", "summary": "Möchte nicht mehr angerufen werden.",
            "do_not_contact": True, **kw}


# --- marking from the note composer --------------------------------------


async def test_a_manager_note_marks_do_not_contact_and_leaves_a_receipt() -> None:
    mid = await _manager()
    async with _api() as c:
        note = await c.post(f"{API}/managers/{mid}/interactions", json=_note())
        read = await c.get(f"{API}/managers/{mid}")
    assert note.status_code == 201, note.text
    assert read.json()["do_not_contact_at"] is not None
    assert read.json()["do_not_contact_reason"] == "requested"
    # The note is saved as usual: that is the history of the request.
    async with SessionLocal() as s:
        rows = (await s.scalars(select(ManagerInteraction).where(ManagerInteraction.manager_id == mid))).all()
    assert [r.summary for r in rows] == ["Möchte nicht mehr angerufen werden."]
    receipts = await _receipts(str(mid))
    assert [r.summary for r in receipts] == ["Nicht mehr kontaktieren vermerkt"]
    # References only — no address, no note text.
    text = receipts[0].summary + json.dumps(receipts[0].payload)
    assert "example.org" not in text and "angerufen" not in text
    assert receipts[0].payload["interaction_id"] == str(rows[0].id)


async def test_a_candidate_note_marks_do_not_contact_with_the_author() -> None:
    cid = await _candidate()
    async with _api() as c:
        note = await c.post(f"{API}/candidates/{cid}/interactions",
                            json=_note(interaction_type="candidate_call"))
        read = await c.get(f"{API}/candidates/{cid}")
    assert note.status_code == 201, note.text
    assert read.json()["do_not_contact_at"] is not None
    receipts = await _receipts(str(cid))
    assert [r.summary for r in receipts] == ["Nicht mehr kontaktieren vermerkt"]
    # A person's action, attributable: the candidate note now carries its author too.
    async with SessionLocal() as s:
        row = (await s.scalars(select(ManagerInteraction).where(ManagerInteraction.candidate_id == cid))).one()
    assert row.actor_name is not None


async def test_an_ordinary_note_marks_nothing() -> None:
    mid = await _manager()
    async with _api() as c:
        await c.post(f"{API}/managers/{mid}/interactions", json={"interaction_type": "note", "summary": "x"})
        read = await c.get(f"{API}/managers/{mid}")
    assert read.json()["do_not_contact_at"] is None
    assert await _receipts(str(mid)) == []


@pytest.mark.parametrize("kind", ["managers", "candidates"])
async def test_a_person_can_make_them_contactable_again(kind) -> None:
    pid = await (_manager() if kind == "managers" else _candidate())
    async with _api() as c:
        await c.post(f"{API}/{kind}/{pid}/interactions",
                     json=_note(interaction_type="note"))
        undo = await c.delete(f"{API}/{kind}/{pid}/do-not-contact")
        read = await c.get(f"{API}/{kind}/{pid}")
    assert undo.status_code == 200, undo.text
    assert undo.json()["do_not_contact_at"] is None
    assert read.json()["do_not_contact_at"] is None
    assert [r.summary for r in await _receipts(str(pid))] == [
        "Nicht mehr kontaktieren vermerkt", "Wieder kontaktierbar",
    ]


# --- off the call lists ----------------------------------------------------


async def test_a_do_not_contact_lead_is_never_due_and_leaves_the_wiedervorlage() -> None:
    mid = await _manager(phone="+49 30 1234567")
    async with SessionLocal() as s:
        s.add(ManagerInteraction(tenant_id=TENANT, manager_id=mid, interaction_type="business_call",
                                 occurred_at=NOW - dt.timedelta(days=1), outcome="call_back",
                                 next_action_at=NOW - dt.timedelta(hours=2)))
        await s.commit()
        before = await call_list.contacts(s, tenant_id=TENANT, now=NOW)
        assert before["rows"][0]["due"] is True
        assert [r["manager_id"] for r in await call_list.follow_ups(s, tenant_id=TENANT, now=NOW)] == [mid]

        boss = await s.get(Manager, mid)
        boss.do_not_contact_at = NOW
        await s.commit()

        page = await call_list.contacts(s, tenant_id=TENANT, now=NOW)
        due = await call_list.contacts(s, tenant_id=TENANT, due_only=True, now=NOW)
        wiedervorlage = await call_list.follow_ups(s, tenant_id=TENANT, now=NOW)
    # Still on the Leads list — with the mark — but nothing is owed to them.
    row = page["rows"][0]
    assert row["do_not_contact_at"] is not None
    assert (row["due"], row["next_action_at"]) == (False, None)
    assert due["rows"] == []
    assert wiedervorlage == []


# --- the confirmation ------------------------------------------------------


@pytest.mark.parametrize("kind", ["managers", "candidates"])
async def test_the_confirmation_goes_out_on_click_and_is_receipted(kind, mailer) -> None:
    pid = await (_manager() if kind == "managers" else _candidate())
    address = "stefan.halama@example.org" if kind == "managers" else "jana.keller@example.com"
    async with _api() as c:
        await c.post(f"{API}/{kind}/{pid}/interactions", json=_note(interaction_type="note"))
        # Marking alone sends nothing — only the button does.
        assert mailer.sent == []
        sent = await c.post(f"{API}/{kind}/{pid}/do-not-contact/confirmation")
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"
    assert [m["to"] for m in mailer.sent] == [address]
    assert "nicht mehr kontaktieren" in mailer.sent[0]["text"]
    last = (await _receipts(str(pid)))[-1]
    assert last.summary == "Bestätigung „Nicht mehr kontaktieren“ versandt"
    assert address not in last.summary + json.dumps(last.payload)
    assert last.payload["provider_message_id"] == "msg_42"


async def test_no_confirmation_for_someone_not_marked_or_without_an_address(mailer) -> None:
    marked_no_mail = await _manager(email=None, name="Ohne Mail")
    unmarked = await _manager(company="Zweite GmbH")
    async with _api() as c:
        await c.post(f"{API}/managers/{marked_no_mail}/interactions", json=_note(interaction_type="note"))
        no_mail = await c.post(f"{API}/managers/{marked_no_mail}/do-not-contact/confirmation")
        not_marked = await c.post(f"{API}/managers/{unmarked}/do-not-contact/confirmation")
    assert no_mail.status_code == 409 and not_marked.status_code == 409
    assert mailer.sent == []


async def test_an_unconfigured_mailer_says_so(no_mailer) -> None:
    mid = await _manager()
    async with _api() as c:
        await c.post(f"{API}/managers/{mid}/interactions", json=_note(interaction_type="note"))
        resp = await c.post(f"{API}/managers/{mid}/do-not-contact/confirmation")
    assert resp.status_code == 503
    assert [r.summary for r in await _receipts(str(mid))] == ["Nicht mehr kontaktieren vermerkt"]


# --- the erasure confirmation ---------------------------------------------


def _erase_body(name: str, **kw) -> dict:
    return {"confirm_name": name, "reason": "erasure", "requested_on": "2026-11-18", **kw}


@pytest.mark.parametrize("kind", ["managers", "candidates"])
async def test_the_erasure_can_confirm_to_the_address_it_erases(kind, mailer) -> None:
    pid = await (_manager() if kind == "managers" else _candidate())
    name = "Stefan Halama" if kind == "managers" else "Jana Keller"
    address = "stefan.halama@example.org" if kind == "managers" else "jana.keller@example.com"
    async with _api() as c:
        resp = await c.post(f"{API}/erasure/{kind}/{pid}", json=_erase_body(name, send_confirmation=True))
    assert resp.status_code == 201, resp.text
    assert resp.json()["confirmation"] == "sent"
    assert [m["to"] for m in mailer.sent] == [address]
    assert "gelöscht" in mailer.sent[0]["text"]
    # The address is gone with the person — not in a receipt, not anywhere.
    async with SessionLocal() as s:
        ledger = (await s.scalars(select(Receipt).where(Receipt.tenant_id == TENANT))).all()
    text = " ".join(r.summary + json.dumps(r.payload) for r in ledger)
    assert address not in text and str(pid) not in text.replace("redacted", "")
    assert any(r.summary == "Bestätigung der Löschung versandt" for r in ledger)


async def test_the_erasure_sends_nothing_unless_asked(mailer) -> None:
    mid = await _manager()
    async with _api() as c:
        resp = await c.post(f"{API}/erasure/managers/{mid}", json=_erase_body("Stefan Halama"))
    assert resp.status_code == 201
    assert resp.json()["confirmation"] is None
    assert mailer.sent == []


async def test_an_erasure_without_a_mailer_still_erases_and_says_so(no_mailer) -> None:
    mid = await _manager()
    async with _api() as c:
        resp = await c.post(f"{API}/erasure/managers/{mid}",
                            json=_erase_body("Stefan Halama", send_confirmation=True))
    assert resp.status_code == 201
    assert resp.json()["confirmation"] == "not_configured"
    async with SessionLocal() as s:
        assert await s.get(Manager, mid) is None


async def test_an_erasure_of_someone_without_an_address_reports_no_email(mailer) -> None:
    mid = await _manager(email=None)
    async with _api() as c:
        resp = await c.post(f"{API}/erasure/managers/{mid}",
                            json=_erase_body("Stefan Halama", send_confirmation=True))
    assert resp.json()["confirmation"] == "no_email"
    assert mailer.sent == []


# --- the Art. 14 notice and the opt-out link ------------------------------


async def test_no_art14_notice_to_a_candidate_marked_do_not_contact(monkeypatch) -> None:
    cid = await _candidate()
    async with SessionLocal() as s:
        cand = await s.get(Candidate, cid)
        cand.do_not_contact_at = NOW
        await s.commit()
        with pytest.raises(notices.NoticeRefused):
            await notices.prepare(s, tenant_id=TENANT, candidate=cand, actor="T", actor_user_id=None)


async def test_saying_no_in_the_opt_in_mail_marks_do_not_contact() -> None:
    cid = await _candidate()
    async with SessionLocal() as s:
        notice = CandidateNotice(tenant_id=TENANT, candidate_id=cid, email="jana.keller@example.com",
                                 token=uuid.uuid4().hex, status="sent", subject="s", body="b")
        s.add(notice)
        await s.commit()
        await notices.record_response(s, notice=notice, opted_in=False)
    async with SessionLocal() as s:
        cand = await s.get(Candidate, cid)
    assert cand.do_not_contact_at is not None
    assert cand.do_not_contact_reason == "opt_out_link"
