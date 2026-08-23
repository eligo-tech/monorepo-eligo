"""The receipt ledger's two guarantees, tested rather than asserted.

Both were previously true only by convention:

  * F2 — `append_receipt` read the chain head and then inserted, so two
    concurrent appends for one tenant produced two successors and made a valid
    workload look like tampering.
  * F3 — the model said append-only was "enforced by convention + service
    layer" while `apply_rls.py` granted the runtime role UPDATE and DELETE, so a
    service bug or one stolen credential could rewrite history and recompute
    every hash.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select, update

from app.core.database import SessionLocal
from app.domain.common.enums import ReceiptAction
from app.domain.verification import service
from app.domain.verification.models import Receipt


async def _append(session, tenant_id, summary: str) -> Receipt:
    return await service.append_receipt(
        session,
        tenant_id=tenant_id,
        agent="test",
        action=ReceiptAction.VERIFY,
        subject_type="candidate",
        subject_id=str(uuid.uuid4()),
        summary=summary,
    )


@pytest.fixture
def tenant() -> uuid.UUID:
    return uuid.uuid4()


async def test_positions_are_sequential_from_zero(tenant) -> None:
    async with SessionLocal() as s:
        for i in range(4):
            await _append(s, tenant, f"r{i}")
        await s.commit()
        rows = (
            await s.execute(
                select(Receipt).where(Receipt.tenant_id == tenant).order_by(Receipt.chain_index)
            )
        ).scalars().all()

    assert [r.chain_index for r in rows] == [0, 1, 2, 3]
    assert rows[0].prev_hash is None
    for earlier, later in zip(rows[:-1], rows[1:], strict=True):
        assert later.prev_hash == earlier.receipt_hash

    async with SessionLocal() as s:
        assert await service.verify_chain(s, tenant_id=tenant) == (True, "chain intact")


async def test_two_tenants_have_independent_chains(tenant) -> None:
    other = uuid.uuid4()
    async with SessionLocal() as s:
        await _append(s, tenant, "a")
        await _append(s, other, "b")
        await _append(s, tenant, "c")
        await s.commit()
        mine = (
            await s.execute(
                select(Receipt.chain_index).where(Receipt.tenant_id == tenant)
            )
        ).scalars().all()
        theirs = (
            await s.execute(
                select(Receipt.chain_index).where(Receipt.tenant_id == other)
            )
        ).scalars().all()
    assert sorted(mine) == [0, 1]
    assert sorted(theirs) == [0]


async def test_concurrent_appends_do_not_fork_the_chain(tenant) -> None:
    """F2. Two writers racing must produce a chain, not two heads."""

    async def writer(label: str) -> None:
        async with SessionLocal() as s:
            await _append(s, tenant, label)
            await s.commit()

    await asyncio.gather(*(writer(f"concurrent-{i}") for i in range(6)))

    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(Receipt).where(Receipt.tenant_id == tenant).order_by(Receipt.chain_index)
            )
        ).scalars().all()
        ok, reason = await service.verify_chain(s, tenant_id=tenant)

    assert len(rows) == 6
    # No two receipts claim the same position, and none claims the same parent.
    assert [r.chain_index for r in rows] == [0, 1, 2, 3, 4, 5]
    assert len({r.prev_hash for r in rows}) == 6
    assert ok, reason


async def test_the_database_refuses_to_update_a_receipt(tenant) -> None:
    """F3. Not "the service layer is careful" — the database says no."""
    async with SessionLocal() as s:
        receipt = await _append(s, tenant, "original")
        await s.commit()
        receipt_id = receipt.id

    async with SessionLocal() as s:
        with pytest.raises(Exception, match="append-only"):
            await s.execute(
                update(Receipt).where(Receipt.id == receipt_id).values(summary="rewritten")
            )
            await s.commit()

    async with SessionLocal() as s:
        row = await s.get(Receipt, receipt_id)
    assert row.summary == "original"


async def test_the_database_refuses_to_delete_a_receipt(tenant) -> None:
    async with SessionLocal() as s:
        receipt = await _append(s, tenant, "keep me")
        await s.commit()
        receipt_id = receipt.id

    async with SessionLocal() as s:
        with pytest.raises(Exception, match="append-only"):
            await s.execute(delete(Receipt).where(Receipt.id == receipt_id))
            await s.commit()

    async with SessionLocal() as s:
        assert await s.get(Receipt, receipt_id) is not None


async def test_the_application_has_no_path_that_can_create_a_gap(tenant) -> None:
    """Deletion is what would create a gap, and the database refuses it.

    `verify_chain` checks contiguity as well as hashes, because a hash chain
    alone would not notice a removed row whose successor was re-pointed. This
    asserts the guarantee from the other side: no code path the application has
    can produce the gap in the first place.
    """
    async with SessionLocal() as s:
        for i in range(3):
            await _append(s, tenant, f"r{i}")
        await s.commit()
        middle = (
            await s.execute(
                select(Receipt.id)
                .where(Receipt.tenant_id == tenant, Receipt.chain_index == 1)
            )
        ).scalar_one()

    async with SessionLocal() as s:
        with pytest.raises(Exception, match="append-only"):
            await s.execute(delete(Receipt).where(Receipt.id == middle))
            await s.commit()

    async with SessionLocal() as s:
        ok, reason = await service.verify_chain(s, tenant_id=tenant)
    assert ok, reason
