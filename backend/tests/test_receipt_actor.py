"""Attribution on the receipt ledger: who did it, and does the chain survive.

The ledger recorded *what* happened and never *who*, so "which of our two
recruiters changed this?" had no answer. Adding a column to a hash-chained,
append-only table is the kind of change that can quietly invalidate every row
that came before it, so the compatibility case below matters more than the
feature case: `test_a_receipt_without_an_actor_hashes_exactly_as_before` is the
one that fails if this ships wrong, and it fails for 2,000-odd production rows
at once.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.context import ActorRef, current_actor_var
from app.core.database import SessionLocal
from app.domain.common.enums import ReceiptAction
from app.domain.verification import service
from app.domain.verification.models import Receipt


@pytest.fixture
def tenant() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture(autouse=True)
def _no_ambient_actor():
    """Each test states its own actor; a leaked one would hide a failure."""
    token = current_actor_var.set(None)
    yield
    current_actor_var.reset(token)


async def _append(session, tenant_id, summary: str = "r", **kw) -> Receipt:
    return await service.append_receipt(
        session,
        tenant_id=tenant_id,
        agent="test",
        action=ReceiptAction.VERIFY,
        subject_type="candidate",
        subject_id=str(uuid.uuid4()),
        summary=summary,
        **kw,
    )


# --- the compatibility case -------------------------------------------------


def test_a_receipt_without_an_actor_hashes_exactly_as_before() -> None:
    """The 2,276 receipts already in production must still verify.

    They were hashed before the column existed. If the actor keys were folded
    into the material unconditionally, every one of them would re-hash to a
    different value and `verify_chain` would report the whole ledger as
    tampered — an alarm that is wrong once is switched off forever.
    """
    fixed = dict(
        receipt_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        agent="enrichment",
        action=ReceiptAction.VERIFY,
        subject_type="candidate",
        subject_id="abc",
        verified=True,
        summary="s",
        payload={"a": 1},
        prev_hash=None,
    )
    # The literal is the hash as computed BEFORE this change. Pinning the value
    # rather than comparing two live calls is the point: comparing the function
    # to itself would still pass if the material changed for everyone.
    assert (
        service._hash_receipt(**fixed)
        == "7c7937dc0487f34fc8bd78269edd3ac44a8c0ccd08c4c39d2822ddb416fc3f39"
    )


def test_omitting_the_actor_is_the_same_as_passing_none() -> None:
    fixed = dict(
        receipt_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        agent="a",
        action=ReceiptAction.VERIFY,
        subject_type="candidate",
        subject_id="x",
        verified=False,
        summary="",
        payload={},
        prev_hash=None,
    )
    assert service._hash_receipt(**fixed) == service._hash_receipt(
        **fixed, actor_user_id=None, actor_name=None
    )


def test_the_actor_is_covered_by_the_hash() -> None:
    """Attribution must be as tamper-evident as the rest of the receipt.

    Rewriting who did something is exactly as serious as rewriting what they
    did, so forging it has to break the chain the same way.
    """
    fixed = dict(
        receipt_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        agent="a",
        action=ReceiptAction.VERIFY,
        subject_type="candidate",
        subject_id="x",
        verified=False,
        summary="",
        payload={},
        prev_hash=None,
    )
    thomas = service._hash_receipt(**fixed, actor_user_id="user_1", actor_name="T")
    hanna = service._hash_receipt(**fixed, actor_user_id="user_2", actor_name="H")
    none_at_all = service._hash_receipt(**fixed)
    assert len({thomas, hanna, none_at_all}) == 3


# --- the feature --------------------------------------------------------


async def test_the_request_actor_lands_on_the_receipt(tenant) -> None:
    current_actor_var.set(ActorRef(user_id="user_3H4n", name="Thomas Bausch"))
    async with SessionLocal() as s:
        receipt = await _append(s, tenant)
        await s.commit()
        assert receipt.actor_user_id == "user_3H4n"
        assert receipt.actor_name == "Thomas Bausch"


async def test_a_job_with_no_request_records_no_actor(tenant) -> None:
    """A cron run and an import have no human behind them.

    NULL here is a true statement, not a missing value, and the UI must be
    able to tell the difference between "nobody" and "we forgot".
    """
    async with SessionLocal() as s:
        receipt = await _append(s, tenant)
        await s.commit()
        assert receipt.actor_user_id is None
        assert receipt.actor_name is None


async def test_an_explicit_actor_beats_the_ambient_one(tenant) -> None:
    current_actor_var.set(ActorRef(user_id="user_ambient", name="Ambient"))
    async with SessionLocal() as s:
        receipt = await _append(s, tenant, actor_user_id="user_named", actor_name="N")
        await s.commit()
        assert receipt.actor_user_id == "user_named"


async def test_the_chain_verifies_with_actors_mixed_in(tenant) -> None:
    """The realistic shape: imports and people writing to one ledger.

    A workspace's history is not all-attributed or all-anonymous — a nightly
    import sits between two human edits — so the chain has to hold across the
    boundary, which is where a conditionally-hashed field would break.
    """
    async with SessionLocal() as s:
        current_actor_var.set(ActorRef(user_id="user_1", name="One"))
        await _append(s, tenant, "human")
        current_actor_var.set(None)
        await _append(s, tenant, "import")
        current_actor_var.set(ActorRef(user_id="user_2", name="Two"))
        await _append(s, tenant, "human again")
        await s.commit()

        ok, detail = await service.verify_chain(s, tenant_id=tenant)
        assert ok, detail

        rows = (
            (
                await s.execute(
                    select(Receipt)
                    .where(Receipt.tenant_id == tenant)
                    .order_by(Receipt.chain_index)
                )
            )
            .scalars()
            .all()
        )
        assert [r.actor_user_id for r in rows] == ["user_1", None, "user_2"]
