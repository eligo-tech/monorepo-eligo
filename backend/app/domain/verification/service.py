"""Verification service — the commit gate for all agent-proposed changes.

Invariants enforced here (non-negotiable):
  1. Agents never persist changes themselves. They pass a ``ProposedChange``
     to :func:`verify_and_commit`.
  2. Every action appends a ``Receipt``. Receipts are append-only and
     hash-chained per tenant (tamper-evident).
  3. A change is committed only if its postconditions pass AND confidence
     clears the threshold; otherwise it is routed to human review.

This makes "agents propose / verification commits / receipts are append-only"
real in code, not just documentation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.common.enums import ReceiptAction
from app.domain.verification.models import EnrichmentRecord, Receipt
from app.domain.verification.schemas import (
    CommitResult,
    EnrichmentRecordRead,
    ProposedChange,
    ReceiptRead,
)

logger = get_logger(__name__)

# Confidence at/above which an automated write is allowed without human review.
AUTO_COMMIT_CONFIDENCE = 0.75

# A postcondition takes the proposed change and returns (ok, reason).
Postcondition = Callable[[ProposedChange], tuple[bool, str]]

# An optional apply hook performs the *actual* domain write once verified.
ApplyHook = Callable[[AsyncSession, ProposedChange], Awaitable[None]]


def _hash_receipt(
    *,
    receipt_id: uuid.UUID,
    tenant_id: uuid.UUID,
    agent: str,
    action: ReceiptAction | str,
    subject_type: str,
    subject_id: str,
    verified: bool,
    summary: str,
    payload: dict[str, Any],
    prev_hash: str | None,
) -> str:
    """Deterministic SHA-256 over the receipt content + previous hash."""
    # ``action`` is a ``ReceiptAction`` on the write path but a plain string
    # when re-read from the DB (the column is String, not Enum) — normalize.
    action_value = action.value if isinstance(action, ReceiptAction) else action
    material = json.dumps(
        {
            "id": str(receipt_id),
            "tenant_id": str(tenant_id),
            "agent": agent,
            "action": action_value,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "verified": verified,
            "summary": summary,
            "payload": payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def _chain_head(
    session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[int, str] | None:
    """Return ``(chain_index, receipt_hash)`` of this tenant's last receipt.

    Ordered by `chain_index`, not by `created_at`: position is a property of the
    ledger, and deriving it from a timestamp made correctness depend on clock
    resolution.
    """
    result = await session.execute(
        select(Receipt.chain_index, Receipt.receipt_hash)
        .where(Receipt.tenant_id == tenant_id)
        .order_by(desc(Receipt.chain_index))
        .limit(1)
    )
    return result.first()


# Two writers racing resolve in one retry; more only under heavy contention.
_MAX_APPEND_ATTEMPTS = 5


async def append_receipt(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    agent: str,
    action: ReceiptAction,
    subject_type: str,
    subject_id: str,
    verified: bool = False,
    summary: str = "",
    payload: dict[str, Any] | None = None,
) -> Receipt:
    """Append one receipt to the tenant's hash-chained ledger.

    This is the ONLY way receipts are created. There is no update/delete path.
    """
    payload = payload or {}

    # Read the head, claim the next position, and let the DATABASE arbitrate.
    # Reading and inserting are not atomic, so two concurrent appends for one
    # tenant can read the same head; `UNIQUE (tenant_id, chain_index)` turns
    # that into a rejected insert instead of a silently forked ledger that
    # `verify_chain` would later report as tampering. Each attempt runs in a
    # SAVEPOINT so a lost race rolls back only this insert, never the caller's
    # other work in the same transaction.
    for attempt in range(_MAX_APPEND_ATTEMPTS):
        head = await _chain_head(session, tenant_id)
        chain_index = (head[0] + 1) if head else 0
        prev_hash = head[1] if head else None

        receipt_id = uuid.uuid4()
        receipt_hash = _hash_receipt(
            receipt_id=receipt_id,
            tenant_id=tenant_id,
            agent=agent,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            verified=verified,
            summary=summary,
            payload=payload,
            prev_hash=prev_hash,
        )
        receipt = Receipt(
            id=receipt_id,
            tenant_id=tenant_id,
            chain_index=chain_index,
            agent=agent,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            verified=verified,
            summary=summary,
            payload=payload,
            prev_hash=prev_hash,
            receipt_hash=receipt_hash,
            created_at=dt.datetime.now(dt.UTC),
        )
        try:
            async with session.begin_nested():
                session.add(receipt)
                await session.flush()
            break
        except IntegrityError:
            # Someone else took this position. Re-read the head and try again.
            logger.info(
                "receipt append lost a race at index %d (attempt %d) — retrying",
                chain_index,
                attempt + 1,
            )
            if attempt == _MAX_APPEND_ATTEMPTS - 1:
                raise
    logger.info(
        "receipt[%s] agent=%s action=%s subject=%s/%s verified=%s",
        receipt.receipt_hash[:8],
        agent,
        action.value,
        subject_type,
        subject_id,
        verified,
    )
    return receipt


async def verify_and_commit(
    session: AsyncSession,
    *,
    change: ProposedChange,
    agent: str,
    postconditions: list[Postcondition] | None = None,
    apply_hook: ApplyHook | None = None,
    actor: str | None = None,
) -> CommitResult:
    """Verify a proposed change, record it, and commit iff it passes.

    Flow:
      * run every postcondition (deterministic checks: deliverability, format,
        allowed source, ...),
      * check the confidence threshold,
      * persist an ``EnrichmentRecord`` (always — provenance is kept even when
        rejected, per GDPR Art. 14),
      * append a ``VERIFY`` receipt, and a ``WRITE`` receipt if committed,
      * optionally invoke ``apply_hook`` to perform the real domain write.

    ``actor`` identifies the acting human (e.g. the recruiter making a manual
    edit); when set it is recorded in the receipt payload so the append-only,
    tamper-evident ledger itself names *who* made the change — not only *that* a
    human did (GDPR Art. 22 contestability). Agents leave it ``None``; their
    identity is already the ``agent`` field.
    """
    postconditions = postconditions or []

    ok = True
    reasons: list[str] = []
    for check in postconditions:
        passed, reason = check(change)
        if not passed:
            ok = False
        reasons.append(reason)

    confident = change.confidence >= AUTO_COMMIT_CONFIDENCE
    committed = ok and confident
    needs_human_review = not committed
    reason_text = "; ".join(r for r in reasons if r) or (
        "auto-committed" if committed else "routed to human review"
    )
    if ok and not confident:
        reason_text = f"low confidence ({change.confidence:.2f}); {reason_text}"

    verify_payload: dict[str, Any] = {
        "field": change.field,
        "confidence": change.confidence,
        "source": change.source.value,
        "postconditions_ok": ok,
    }
    if actor:
        verify_payload["actor"] = actor

    # VERIFY receipt — records the decision regardless of outcome.
    verify_receipt = await append_receipt(
        session,
        tenant_id=change.tenant_id,
        agent=agent,
        action=ReceiptAction.VERIFY,
        subject_type=change.entity_type,
        subject_id=str(change.entity_id),
        verified=ok,
        summary=f"verify {change.field}: {reason_text}",
        payload=verify_payload,
    )

    record = EnrichmentRecord(
        tenant_id=change.tenant_id,
        entity_type=change.entity_type,
        entity_id=change.entity_id,
        field=change.field,
        proposed_value=change.proposed_value,
        source=change.source,
        source_detail=change.source_detail,
        confidence=change.confidence,
        committed=committed,
        needs_human_review=needs_human_review,
        receipt_id=verify_receipt.id,
    )
    session.add(record)
    await session.flush()

    write_receipt = verify_receipt
    if committed:
        if apply_hook is not None:
            await apply_hook(session, change)
        write_payload: dict[str, Any] = {
            "field": change.field,
            "value": change.proposed_value,
        }
        if actor:
            write_payload["actor"] = actor
        # WRITE receipt — the only receipt that signifies a real mutation.
        write_receipt = await append_receipt(
            session,
            tenant_id=change.tenant_id,
            agent=agent,
            action=ReceiptAction.WRITE,
            subject_type=change.entity_type,
            subject_id=str(change.entity_id),
            verified=True,
            summary=f"write {change.field}={change.proposed_value!r}",
            payload=write_payload,
        )

    return CommitResult(
        committed=committed,
        needs_human_review=needs_human_review,
        reason=reason_text,
        receipt=ReceiptRead.model_validate(write_receipt),
        record=EnrichmentRecordRead.model_validate(record),
    )


async def list_receipts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 100,
) -> list[Receipt]:
    """Read the tenant's receipt ledger, newest first."""
    result = await session.execute(
        select(Receipt)
        .where(Receipt.tenant_id == tenant_id)
        .order_by(desc(Receipt.created_at), desc(Receipt.id))
        .limit(limit)
    )
    return list(result.scalars().all())


async def verify_chain(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> tuple[bool, str]:
    """Recompute the hash chain and confirm it has not been tampered with."""
    result = await session.execute(
        select(Receipt)
        .where(Receipt.tenant_id == tenant_id)
        .order_by(Receipt.chain_index)
    )
    prev: str | None = None
    expected_index = 0
    for receipt in result.scalars().all():
        # A gap means a receipt was removed. The hash chain alone would not
        # notice: deleting a row and re-pointing its successor is detectable,
        # but a contiguous sequence is what proves nothing was quietly dropped.
        if receipt.chain_index != expected_index:
            return (
                False,
                f"chain gap at index {expected_index} "
                f"(next receipt is {receipt.chain_index})",
            )
        expected_index += 1
        expected = _hash_receipt(
            receipt_id=receipt.id,
            tenant_id=receipt.tenant_id,
            agent=receipt.agent,
            action=receipt.action,
            subject_type=receipt.subject_type,
            subject_id=receipt.subject_id,
            verified=receipt.verified,
            summary=receipt.summary,
            payload=receipt.payload,
            prev_hash=prev,
        )
        if receipt.prev_hash != prev or receipt.receipt_hash != expected:
            return False, f"chain broken at receipt {receipt.id}"
        prev = receipt.receipt_hash
    return True, "chain intact"