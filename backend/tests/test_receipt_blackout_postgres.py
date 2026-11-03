"""The receipt blackout, proved on Postgres as the runtime role.

The SQLite suite (`test_receipt_blackout.py`) exercises a different trigger
language. What production enforces is the plpgsql function from 0049 — under
RLS, as `eligo_app`, which holds UPDATE on `receipts` only because a foreign
key needs it (0024). The trigger is therefore the only thing between the app
role and the ledger, and this file attacks it from there.

Skipped unless the database is Postgres; the CI "RLS on Postgres" and
"upgrade from main" jobs run it as the app role.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.database import SessionLocal, admin_engine, current_tenant_var, engine
from app.domain.common.enums import ReceiptAction
from app.domain.verification import service
from app.domain.verification.models import BLACKOUT_SUMMARY, Receipt

pytestmark = pytest.mark.skipif(not settings.is_postgres, reason="Postgres only")


@pytest.fixture(autouse=True)
async def _fresh_db():
    """No drop/create: the CI job applied the schema, policies and trigger."""
    yield
    await engine.dispose()
    await admin_engine.dispose()


@contextlib.contextmanager
def _as(tenant: uuid.UUID):
    token = current_tenant_var.set(str(tenant))
    try:
        yield
    finally:
        current_tenant_var.reset(token)


async def _write(tenant: uuid.UUID, n: int) -> list[Receipt]:
    with _as(tenant):
        async with SessionLocal() as s:
            rows = [
                await service.append_receipt(
                    s, tenant_id=tenant, agent="test", action=ReceiptAction.WRITE,
                    subject_type="candidate", subject_id="c-1", verified=True,
                    summary=f"write email='p{i}@example.org'",
                    payload={"field": "email", "value": f"p{i}@example.org"},
                )
                for i in range(n)
            ]
            await s.commit()
            return rows


async def _refused(tenant: uuid.UUID, statement, match: str = "append-only") -> None:
    with _as(tenant):
        async with SessionLocal() as s:
            with pytest.raises(DBAPIError, match=match):
                await s.execute(statement)
                await s.commit()


def _blackout(row: Receipt, erase_id: uuid.UUID, **extra):
    return (
        update(Receipt)
        .where(Receipt.id == row.id)
        .values(summary=BLACKOUT_SUMMARY, payload={"erased_by": str(erase_id)},
                updated_at=Receipt.updated_at, **extra)
        .execution_options(synchronize_session=False)
    )


async def test_the_app_role_can_black_out_what_an_erasure_lists_and_the_chain_holds() -> None:
    tenant = uuid.uuid4()
    rows = await _write(tenant, 3)
    with _as(tenant):
        async with SessionLocal() as s:
            import datetime as dt

            from app.domain.erasure.models import ErasureRequest

            request_id = uuid.uuid4()
            erase = await service.erase_receipts(
                s, tenant_id=tenant, receipt_ids=[rows[1].id],
                request_id=request_id, subject_type="candidate",
            )
            s.add(ErasureRequest(id=request_id, tenant_id=tenant, subject_type="candidate",
                                 reason="erasure", requested_on=dt.date(2026, 11, 1), counts={},
                                 erase_receipt_id=erase.id))
            await s.commit()
        async with SessionLocal() as s:
            ok, why = await service.verify_chain(s, tenant_id=tenant)
            summary = (await s.get(Receipt, rows[1].id)).summary
    assert summary == BLACKOUT_SUMMARY
    assert ok, why


async def test_the_app_role_still_cannot_edit_or_delete_a_receipt() -> None:
    tenant = uuid.uuid4()
    rows = await _write(tenant, 1)
    await _refused(tenant, update(Receipt).where(Receipt.id == rows[0].id).values(summary="edited"))
    # DELETE never reaches the trigger: the app role does not hold the
    # privilege at all (0014). Either refusal is a refusal.
    await _refused(
        tenant, delete(Receipt).where(Receipt.id == rows[0].id),
        match="permission denied|append-only",
    )


async def test_a_blackout_no_erasure_lists_is_refused() -> None:
    tenant = uuid.uuid4()
    rows = await _write(tenant, 2)
    with _as(tenant):
        async with SessionLocal() as s:
            erase = await service.erase_receipts(
                s, tenant_id=tenant, receipt_ids=[rows[0].id],
                request_id=uuid.uuid4(), subject_type="candidate",
            )
            await s.commit()
    await _refused(tenant, _blackout(rows[1], erase.id))


async def test_a_listed_blackout_that_also_changes_another_column_is_refused() -> None:
    tenant = uuid.uuid4()
    rows = await _write(tenant, 1)
    with _as(tenant):
        async with SessionLocal() as s:
            erase = await service.append_receipt(
                s, tenant_id=tenant, agent="erasure", action=ReceiptAction.ERASE,
                subject_type="erasure_request", subject_id=str(uuid.uuid4()), verified=True,
                summary="erasure", payload={"redacted": {str(rows[0].id): rows[0].receipt_hash}},
            )
            await s.commit()
    await _refused(tenant, _blackout(rows[0], erase.id, subject_id="someone-else"))
    # The same blackout without the extra change goes through — so the refusal
    # above was the extra column, not something else.
    with _as(tenant):
        async with SessionLocal() as s:
            await s.execute(_blackout(rows[0], erase.id))
            await s.commit()


async def test_another_workspaces_erasure_cannot_black_out_mine() -> None:
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    rows = await _write(mine, 1)
    with _as(theirs):
        async with SessionLocal() as s:
            foreign = await service.append_receipt(
                s, tenant_id=theirs, agent="erasure", action=ReceiptAction.ERASE,
                subject_type="erasure_request", subject_id=str(uuid.uuid4()), verified=True,
                summary="erasure", payload={"redacted": {str(rows[0].id): rows[0].receipt_hash}},
            )
            await s.commit()
    await _refused(mine, _blackout(rows[0], foreign.id))


async def test_a_licence_that_is_a_list_is_refused() -> None:
    """`?` is true for a JSON array element too; the trigger must insist on a map."""
    tenant = uuid.uuid4()
    rows = await _write(tenant, 1)
    with _as(tenant):
        async with SessionLocal() as s:
            bad = await service.append_receipt(
                s, tenant_id=tenant, agent="erasure", action=ReceiptAction.ERASE,
                subject_type="erasure_request", subject_id=str(uuid.uuid4()), verified=True,
                summary="erasure", payload={"redacted": [str(rows[0].id)]},
            )
            await s.commit()
    await _refused(tenant, _blackout(rows[0], bad.id))


async def test_an_erase_receipt_cannot_be_blacked_out() -> None:
    tenant = uuid.uuid4()
    with _as(tenant):
        async with SessionLocal() as s:
            first = await service.append_receipt(
                s, tenant_id=tenant, agent="erasure", action=ReceiptAction.ERASE,
                subject_type="erasure_request", subject_id=str(uuid.uuid4()), verified=True,
                summary="erasure", payload={"redacted": {}},
            )
            await s.flush()
            second = await service.append_receipt(
                s, tenant_id=tenant, agent="erasure", action=ReceiptAction.ERASE,
                subject_type="erasure_request", subject_id=str(uuid.uuid4()), verified=True,
                summary="erasure", payload={"redacted": {str(first.id): first.receipt_hash}},
            )
            await s.commit()
    await _refused(tenant, _blackout(first, second.id))
