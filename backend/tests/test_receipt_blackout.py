"""Blacking out a receipt during an erasure — and nothing else (GDPR Art. 17).

Receipts are append-only: a database trigger refuses every UPDATE and DELETE.
Receipts written before 2026-11-02 still carry personal values, so an erasure
must be able to remove them. The one exception the trigger allows:

* summary becomes the fixed marker, payload becomes exactly
  `{"erased_by": <ERASE receipt id>}`;
* every other column — the hash included — stays as it was;
* that ERASE receipt exists in the same workspace and lists this receipt.

`verify_chain` then accepts a blacked-out row only if its ERASE receipt names
it with that exact hash; the links between receipts are checked for every row.
These run on SQLite; tests/test_receipt_blackout_postgres.py repeats the
database-side cases on Postgres as the runtime role.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import DatabaseError

from app.core.database import SessionLocal, create_all
from app.domain.common.enums import ReceiptAction
from app.domain.verification import service
from app.domain.verification.models import Receipt


async def _receipts(s, tenant: uuid.UUID, n: int = 3) -> list[Receipt]:
    out = []
    for i in range(n):
        out.append(
            await service.append_receipt(
                s,
                tenant_id=tenant,
                agent="test",
                action=ReceiptAction.WRITE,
                subject_type="candidate",
                subject_id="c-1",
                verified=True,
                summary=f"write email='person{i}@example.org'",
                payload={"field": "email", "value": f"person{i}@example.org"},
            )
        )
    await s.commit()
    return out


async def test_an_erasure_blacks_out_exactly_the_named_receipts_and_the_chain_holds() -> None:
    await create_all()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        rows = await _receipts(s, tenant)
        erase = await _licensed(s, tenant, [rows[0].id, rows[2].id])
        s.expire_all()
        got = {r.id: r for r in (await s.execute(
            Receipt.__table__.select().where(Receipt.tenant_id == tenant)
        )).mappings()}
        ok, why = await service.verify_chain(s, tenant_id=tenant)

    assert got[rows[0].id]["summary"] == service.BLACKOUT_SUMMARY
    assert got[rows[0].id]["payload"] == {"erased_by": str(erase.id)}
    assert got[rows[1].id]["summary"].startswith("write email=")  # not named, untouched
    assert got[rows[2].id]["summary"] == service.BLACKOUT_SUMMARY
    assert "person0@example.org" not in str(got[erase.id]["payload"])  # ids + hashes only
    assert ok, why


async def _licensed(s, tenant: uuid.UUID, ids: list[uuid.UUID]) -> Receipt:
    """A blackout as the erasure service does it: ERASE receipt, then the
    request log row that names it — the pair `verify_chain` requires."""
    import datetime as dt

    from app.domain.erasure.models import ErasureRequest

    request_id = uuid.uuid4()
    erase = await service.erase_receipts(
        s, tenant_id=tenant, receipt_ids=ids, request_id=request_id, subject_type="candidate"
    )
    s.add(ErasureRequest(id=request_id, tenant_id=tenant, subject_type="candidate",
                         reason="erasure", requested_on=dt.date(2026, 11, 1), counts={},
                         erase_receipt_id=erase.id))
    await s.commit()
    return erase


async def _refused(statement, params=None) -> None:
    async with SessionLocal() as s:
        with pytest.raises(DatabaseError):
            await s.execute(statement, params or {})
            await s.commit()


async def test_any_other_change_to_a_receipt_is_still_refused() -> None:
    await create_all()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        rows = await _receipts(s, tenant, 1)
    await _refused(update(Receipt).where(Receipt.id == rows[0].id).values(summary="edited"))


async def test_a_blackout_no_erase_receipt_lists_is_refused() -> None:
    await create_all()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        rows = await _receipts(s, tenant, 2)
        erase = await service.erase_receipts(
            s, tenant_id=tenant, receipt_ids=[rows[0].id],
            request_id=uuid.uuid4(), subject_type="candidate",
        )
        await s.commit()
    # rows[1] is not on that ERASE receipt's list.
    await _refused(
        update(Receipt).where(Receipt.id == rows[1].id).values(
            summary=service.BLACKOUT_SUMMARY, payload={"erased_by": str(erase.id)},
            updated_at=Receipt.updated_at,
        )
    )


async def test_a_blackout_cannot_also_change_another_column() -> None:
    await create_all()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        rows = await _receipts(s, tenant, 1)
        # The ERASE receipt lists the row, so only the extra change can refuse it.
        erase = await service.append_receipt(
            s, tenant_id=tenant, agent="erasure", action=ReceiptAction.ERASE,
            subject_type="erasure_request", subject_id=str(uuid.uuid4()), verified=True,
            summary="erasure", payload={"redacted": {str(rows[0].id): rows[0].receipt_hash}},
        )
        await s.commit()
    await _refused(
        update(Receipt).where(Receipt.id == rows[0].id).values(
            summary=service.BLACKOUT_SUMMARY, payload={"erased_by": str(erase.id)},
            updated_at=Receipt.updated_at, agent="someone-else",
        )
    )


async def test_another_workspaces_erase_receipt_cannot_black_out_mine() -> None:
    await create_all()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        rows = await _receipts(s, mine, 1)
        foreign = await service.append_receipt(
            s, tenant_id=theirs, agent="erasure", action=ReceiptAction.ERASE,
            subject_type="erasure_request", subject_id=str(uuid.uuid4()), verified=True,
            summary="erasure", payload={"redacted": {str(rows[0].id): rows[0].receipt_hash}},
        )
        await s.commit()
    await _refused(
        update(Receipt).where(Receipt.id == rows[0].id).values(
            summary=service.BLACKOUT_SUMMARY, payload={"erased_by": str(foreign.id)},
            updated_at=Receipt.updated_at,
        )
    )


async def test_a_blackout_that_bypassed_the_trigger_is_caught_by_verify_chain() -> None:
    """Someone with DDL rights drops the trigger and blacks out a receipt no
    ERASE receipt lists. The chain check must not take the marker on trust."""
    await create_all()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        rows = await _receipts(s, tenant, 2)
        await s.execute(text("DROP TRIGGER receipts_no_update"))
        await s.execute(
            update(Receipt).where(Receipt.id == rows[1].id).values(
                summary=service.BLACKOUT_SUMMARY, payload={"erased_by": str(uuid.uuid4())},
                updated_at=Receipt.updated_at,
            )
        )
        await s.commit()
        ok, why = await service.verify_chain(s, tenant_id=tenant)
    # Put the guard back for every later test sharing this database file.
    from app.domain.verification.models import _SQLITE_APPEND_ONLY

    async with SessionLocal() as s:
        for statement in _SQLITE_APPEND_ONLY:
            await s.execute(text(statement))
        await s.commit()
    assert not ok and str(rows[1].id) in why


def test_the_migration_installs_the_same_trigger_function_as_create_all() -> None:
    """Existing databases get the function from 0050, fresh ones from the model.
    If the two drift, CI (create_all) and production (migrated) enforce
    different rules on the one table whose rules matter most."""
    import importlib.util
    from pathlib import Path

    from app.domain.verification.models import BLACKOUT_SUMMARY, PG_APPEND_ONLY_FUNCTION

    path = Path(__file__).parents[1] / "migrations/versions/0050_tenant_erasure.py"
    spec = importlib.util.spec_from_file_location("m0050", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.FUNCTION == PG_APPEND_ONLY_FUNCTION
    assert module._MARKER == BLACKOUT_SUMMARY


async def test_an_erase_receipt_no_request_backs_does_not_verify() -> None:
    """The app role can append receipts, so it can write an ERASE receipt for
    itself. The trigger lets that blackout through — it cannot see intent —
    but the chain check must not: a licence counts only when the request log
    names it."""
    await create_all()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        rows = await _receipts(s, tenant, 2)
        forged = await service.erase_receipts(
            s, tenant_id=tenant, receipt_ids=[rows[0].id],
            request_id=uuid.uuid4(), subject_type="candidate",
        )
        await s.commit()
        ok, why = await service.verify_chain(s, tenant_id=tenant)
    assert not ok and str(forged.id) in why


async def test_an_erase_receipt_cannot_black_out_itself_or_another_erase_receipt() -> None:
    await create_all()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        rows = await _receipts(s, tenant, 1)
        first = await _licensed(s, tenant, [rows[0].id])
    async with SessionLocal() as s:
        second = await service.append_receipt(
            s, tenant_id=tenant, agent="erasure", action=ReceiptAction.ERASE,
            subject_type="erasure_request", subject_id=str(uuid.uuid4()), verified=True,
            summary="erasure", payload={"redacted": {str(first.id): first.receipt_hash}},
        )
        await s.commit()
    await _refused(
        update(Receipt).where(Receipt.id == first.id).values(
            summary=service.BLACKOUT_SUMMARY, payload={"erased_by": str(second.id)},
            updated_at=Receipt.updated_at,
        )
    )


async def test_a_licence_that_is_not_a_map_reads_as_tampering_not_a_crash() -> None:
    await create_all()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        rows = await _receipts(s, tenant, 1)
        bad = await service.append_receipt(
            s, tenant_id=tenant, agent="erasure", action=ReceiptAction.ERASE,
            subject_type="erasure_request", subject_id=str(uuid.uuid4()), verified=True,
            summary="erasure", payload={"redacted": [str(rows[0].id)]},
        )
        await s.execute(text("DROP TRIGGER receipts_no_update"))
        await s.execute(
            update(Receipt).where(Receipt.id == rows[0].id).values(
                summary=service.BLACKOUT_SUMMARY, payload={"erased_by": str(bad.id)},
                updated_at=Receipt.updated_at,
            )
        )
        await s.commit()
        ok, why = await service.verify_chain(s, tenant_id=tenant)
    from app.domain.verification.models import _SQLITE_APPEND_ONLY

    async with SessionLocal() as s:
        for statement in _SQLITE_APPEND_ONLY:
            await s.execute(text(statement))
        await s.commit()
    assert not ok

