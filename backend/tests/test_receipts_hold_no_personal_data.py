"""Receipts hold references, never personal values (ARCHITECTURE.md: Audit).

The receipt ledger is append-only and hash-chained over `summary` and
`payload`, so whatever lands there can never be erased without breaking the
chain. Until 2026-11-02 the WRITE receipt carried the value itself
(`write email='anna@…'`), the VERIFY receipt carried free-text postcondition
reasons that can quote a value, and the Art. 14 notice receipt named the
recipient's address. Each test below writes a recognisable secret through the
real path and asserts it is nowhere in the ledger — and still where a
recruiter needs it.
"""

from __future__ import annotations

import json
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ConfidenceSource, ReceiptAction
from app.domain.notices import service as notices
from app.domain.notices.delivery.base import EmailRejected, SentMessage
from app.domain.verification import service as verification
from app.domain.verification.models import EnrichmentRecord, Receipt
from app.domain.verification.schemas import ProposedChange

SECRET = "geheim.person@example.org"


def _text(r: Receipt) -> str:
    return r.summary + " " + json.dumps(r.payload, default=str)


async def _receipts(session, subject_id: str) -> list[Receipt]:
    return list(
        (
            await session.execute(
                select(Receipt).where(Receipt.subject_id == subject_id).order_by(Receipt.chain_index)
            )
        ).scalars()
    )


def _change(tenant: uuid.UUID, entity: uuid.UUID, value: str) -> ProposedChange:
    return ProposedChange(
        tenant_id=tenant,
        entity_type="candidate",
        entity_id=entity,
        field="email",
        proposed_value=value,
        source=ConfidenceSource.HUMAN_VERIFIED,
        confidence=1.0,
    )


async def test_a_committed_write_leaves_no_value_in_the_ledger() -> None:
    await create_all()
    tenant, entity = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        result = await verification.verify_and_commit(
            s, change=_change(tenant, entity, SECRET), agent="test"
        )
        await s.commit()
        assert result.committed
        rows = await _receipts(s, str(entity))

    assert {r.action for r in rows} == {ReceiptAction.VERIFY.value, ReceiptAction.WRITE.value}
    for r in rows:
        assert SECRET not in _text(r), f"{r.action} receipt carries the value: {_text(r)}"


async def test_a_rejection_reason_that_quotes_a_value_stays_out_of_the_ledger() -> None:
    """The interviewer's postcondition says `vorhandener Wert '…'`. A reason is
    free text; it belongs on the deletable provenance record, not the chain."""
    await create_all()
    tenant, entity = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        result = await verification.verify_and_commit(
            s,
            change=_change(tenant, entity, "neu@example.org"),
            agent="test",
            postconditions=[lambda c: (False, f"vorhandener Wert {SECRET!r} — Recruiter entscheidet")],
        )
        await s.commit()
        assert not result.committed
        rows = await _receipts(s, str(entity))
        record = (
            await s.execute(select(EnrichmentRecord).where(EnrichmentRecord.entity_id == entity))
        ).scalar_one()

    assert rows and all(SECRET not in _text(r) for r in rows)
    assert SECRET in (record.reason or ""), "the reason must survive on the record"


async def test_the_history_still_shows_what_was_written() -> None:
    await create_all()
    tenant, entity = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        await verification.verify_and_commit(s, change=_change(tenant, entity, SECRET), agent="test")
        await s.commit()
        history = await verification.history_for(
            s, tenant_id=tenant, entity_type="candidate", entity_id=entity
        )
    assert [h["value"] for h in history] == [SECRET]
    assert history[0]["field"] == "email"


async def test_the_history_of_an_old_receipt_still_reads_its_summary() -> None:
    """Production holds receipts written the old way; they are immutable, so the
    history must keep reading them."""
    await create_all()
    tenant, entity = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        await verification.append_receipt(
            s,
            tenant_id=tenant,
            agent="recruiter",
            action=ReceiptAction.WRITE,
            subject_type="candidate",
            subject_id=str(entity),
            verified=True,
            summary="write current_title='Lead Engineer'",
            payload={"field": "current_title", "source": "human_verified"},
        )
        await s.commit()
        history = await verification.history_for(
            s, tenant_id=tenant, entity_type="candidate", entity_id=entity
        )
    assert [h["value"] for h in history] == ["Lead Engineer"]


async def test_a_value_whose_record_was_erased_shows_nothing() -> None:
    await create_all()
    tenant, entity = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        await verification.verify_and_commit(s, change=_change(tenant, entity, SECRET), agent="test")
        await s.commit()
        for rec in (
            await s.execute(select(EnrichmentRecord).where(EnrichmentRecord.entity_id == entity))
        ).scalars():
            await s.delete(rec)
        await s.commit()
        history = await verification.history_for(
            s, tenant_id=tenant, entity_type="candidate", entity_id=entity
        )
    assert [h["value"] for h in history] == [None]


# --- Art. 14 notices ---------------------------------------------------------


class _Sender:
    name = "recorder"

    async def send(self, *, to, subject, text, reply_to=None) -> SentMessage:
        return SentMessage(provider=self.name, message_id="msg_1")


class _Refuser:
    name = "refuser"

    async def send(self, *, to, subject, text, reply_to=None) -> SentMessage:
        raise EmailRejected(f"Resend 422: invalid recipient {to}")


async def _notice_receipts(monkeypatch, sender) -> list[Receipt]:
    await create_all()
    monkeypatch.setattr(notices, "get_email_sender", lambda cfg=None: sender)
    async with SessionLocal() as s:
        cand = Candidate(tenant_id=settings.default_tenant_id, full_name="Geheim Person", email=SECRET)
        s.add(cand)
        await s.commit()
        cid = cand.id
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"{settings.api_v1_prefix}/candidates/{cid}/notices")
    async with SessionLocal() as s:
        return list(
            (
                await s.execute(select(Receipt).where(Receipt.subject_type == "candidate_notice"))
            ).scalars()
        )


async def test_a_sent_notice_receipt_does_not_name_the_recipient(monkeypatch) -> None:
    rows = await _notice_receipts(monkeypatch, _Sender())
    assert rows
    assert all(SECRET not in _text(r) for r in rows), [_text(r) for r in rows]


async def test_a_failed_notice_receipt_does_not_carry_the_provider_error(monkeypatch) -> None:
    rows = await _notice_receipts(monkeypatch, _Refuser())
    assert rows
    assert all(SECRET not in _text(r) for r in rows), [_text(r) for r in rows]
